from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import student_required, teacher_required
from problems.models import Task
from worksheets.models import Worksheet

from .models import (Assignment, Review, Submission, SubmissionPart,
                     SubmissionPhoto)


# --- Назначение листка ученикам (действие учителя со страницы листка) ---

@teacher_required
@require_POST
def assign_worksheet(request, worksheet_id):
    worksheet = get_object_or_404(
        Worksheet, pk=worksheet_id, owner=request.user)
    student_ids = set(request.POST.getlist('students'))
    # Выбранные группы: назначение всем участникам
    group_ids = request.POST.getlist('groups')
    if group_ids:
        group_student_ids = (request.user.owned_groups
                             .filter(pk__in=group_ids)
                             .values_list('students__id', flat=True))
        student_ids |= {str(pk) for pk in group_student_ids if pk}
    grade_scale = request.POST.get('grade_scale', Assignment.SCALE_WORDS)
    if grade_scale not in dict(Assignment.SCALE_CHOICES):
        grade_scale = Assignment.SCALE_WORDS
    due_at = request.POST.get('due_at') or None

    my_students = request.user.students.filter(
        role='student', user_id__in=student_ids)
    created = 0
    for profile in my_students:
        _, was_created = Assignment.objects.get_or_create(
            worksheet=worksheet, student=profile.user,
            defaults={
                'assigned_by': request.user,
                'grade_scale': grade_scale,
                'due_at': due_at,
            })
        created += was_created
    if created:
        messages.success(request, f'Назначено ученикам: {created}.')
    else:
        messages.info(request, 'Новых назначений нет (уже были назначены).')
    return redirect('worksheet_detail', pk=worksheet.pk)


# --- Кабинет ученика ---

def _student_assignment(request, pk):
    return get_object_or_404(
        Assignment.objects.select_related('worksheet', 'worksheet__owner'),
        pk=pk, student=request.user)


def _assignment_rows(assignment, with_review=False):
    """Строки листка для ученика/учителя: задачи с подпунктами и ответами,
    текстовые элементы — только для отображения."""
    qs = assignment.submissions.prefetch_related('photos', 'parts')
    qs = qs.select_related('review') if with_review \
        else qs.prefetch_related('review')
    submissions = {s.task_id: s for s in qs}
    hidden = set(assignment.hidden_items.values_list('pk', flat=True))
    rows = []
    number = 0
    for item in assignment.worksheet.ordered_items():
        if item.pk in hidden:
            continue
        if item.task_id is None:
            rows.append({'item': item, 'task': None, 'number': None})
            continue
        number += 1
        submission = submissions.get(item.task_id)
        parts = {}
        if submission:
            parts = {p.subitem_id: p for p in submission.parts.all()}
        subitems = item.selected_subitems()
        subrows = [
            {'subitem': s, 'part': parts.get(s.pk),
             'prefix': f'task{item.task_id}_sub{s.pk}'}
            for s in subitems
        ]
        # «Отвечено» — есть текст на задаче/любом подпункте или фото;
        # только по prefetch-данным, без дополнительных запросов
        answered = bool(submission) and bool(
            submission.display_answer
            or any(sr['part'] and sr['part'].display_answer for sr in subrows)
            or submission.photos.all())
        review = getattr(submission, 'review', None) if submission else None
        rows.append({
            'item': item,
            'task': item.task,
            'number': number,
            'prefix': f'task{item.task_id}',
            'submission': submission,
            'review': review,
            'answered': answered,
            'has_comment': bool(review and review.comment),
            'subrows': subrows,
        })
    return rows


def _progress(rows):
    """Счётчики для сайдбара и подтверждения отправки."""
    task_rows = [r for r in rows if r['task'] is not None]
    return {
        'task_rows': task_rows,
        'task_count': len(task_rows),
        'answered_count': sum(1 for r in task_rows if r['answered']),
        'unanswered_numbers': [
            r['number'] for r in task_rows if not r['answered']],
    }


@student_required
def assignment_detail(request, pk):
    assignment = _student_assignment(request, pk)
    rows = _assignment_rows(assignment)
    context = {
        'assignment': assignment,
        'rows': rows,
        'editable': assignment.is_editable_by_student,
    }
    context.update(_progress(rows))
    return render(request, 'assignments/assignment_detail.html', context)


def _visible_task_item(assignment, task):
    """Элемент листка с этой задачей, видимый ученику, или 404.

    Скрытые через assignment.hidden_items задачи нельзя ни сохранять,
    ни снабжать фото — иначе обходится фильтр страницы задания.
    """
    hidden = assignment.hidden_items.values('pk')
    item = (assignment.worksheet.items
            .filter(task=task, deleted_at__isnull=True)
            .exclude(pk__in=hidden)
            .first())
    if item is None:
        raise Http404
    return item


def _get_or_create_submission(assignment, task_id):
    task = get_object_or_404(Task, pk=task_id)
    _visible_task_item(assignment, task)
    submission, _ = Submission.objects.get_or_create(
        assignment=assignment, task=task)
    return submission


_ANSWER_FIELD_SUFFIXES = {
    Task.ANSWER_NUMBER: (('answer_number', 'number'),),
    Task.ANSWER_INTERVAL: (('interval_low', 'low'), ('interval_high', 'high')),
    Task.ANSWER_TEXT: (('answer_text', 'text'),),
}


def _answer_fields(answer_type, post, prefix):
    """Поля ответа по типу задачи из POST с данным префиксом.

    Возвращаются только поля, реально присланные формой: тогда POST без
    полей ответов (например, форма загрузки фото) не затирает
    сохранённое пустыми строками.
    """
    suffixes = _ANSWER_FIELD_SUFFIXES.get(
        answer_type, _ANSWER_FIELD_SUFFIXES[Task.ANSWER_TEXT])
    return {
        field: post[f'{prefix}_{suffix}'].strip()
        for field, suffix in suffixes
        if f'{prefix}_{suffix}' in post
    }


def _persist_answers(assignment, post):
    """Записывает присланные поля ответов по всем видимым задачам.

    Единая точка для сохранения черновика, отправки на проверку и действий
    с фото: любой POST со страницы задания сначала сохраняет введённое,
    иначе ответы теряются при уходе со страницы. У задач с подпунктами —
    отдельный ответ на каждый подпункт (SubmissionPart), у остальных —
    ответ на задачу целиком. Возвращает число задач, у которых что-то
    записано.
    """
    hidden = set(assignment.hidden_items.values_list('pk', flat=True))
    existing = {s.task_id: s for s in assignment.submissions.all()}
    touched = 0
    for item in assignment.worksheet.ordered_items():
        if item.task_id is None or item.pk in hidden:
            continue
        task = item.task
        prefix = f'task{task.pk}'
        subitems = item.selected_subitems()
        if subitems:
            part_fields = {
                s: _answer_fields(task.answer_type, post, f'{prefix}_sub{s.pk}')
                for s in subitems
            }
            part_fields = {s: f for s, f in part_fields.items() if f}
            if not part_fields:
                continue
            has_values = any(
                any(f.values()) for f in part_fields.values())
            if not (has_values or task.pk in existing):
                continue
            submission = existing.get(task.pk)
            if submission is None:
                submission, _ = Submission.objects.get_or_create(
                    assignment=assignment, task=task)
                existing[task.pk] = submission
            for subitem, fields in part_fields.items():
                part, _ = SubmissionPart.objects.get_or_create(
                    submission=submission, subitem=subitem)
                for name, value in fields.items():
                    setattr(part, name, value)
                part.save()
            touched += 1
            continue
        fields = _answer_fields(task.answer_type, post, prefix)
        if not fields:
            continue
        if any(fields.values()) or task.pk in existing:
            submission = existing.get(task.pk)
            if submission is None:
                submission, _ = Submission.objects.get_or_create(
                    assignment=assignment, task=task)
                existing[task.pk] = submission
            for name, value in fields.items():
                setattr(submission, name, value)
            submission.save()
            touched += 1
    return touched


def _is_xhr(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _editable_or_deny(request, assignment):
    """Проверка «работу ещё можно менять» с JSON-ответом для автосохранения."""
    if assignment.is_editable_by_student:
        return None
    if _is_xhr(request):
        return JsonResponse(
            {'ok': False,
             'message': 'Работа уже отправлена — изменения не сохранены'},
            status=403)
    raise PermissionDenied('Работа уже отправлена на проверку.')


@student_required
@require_POST
def save_answers(request, pk):
    """Сохраняет все текстовые/числовые ответы одной формой.

    Для fetch-автосохранения (X-Requested-With) отвечает JSON, как
    конструктор листка; обычная отправка формы — redirect с сообщением.
    """
    assignment = _student_assignment(request, pk)
    denied = _editable_or_deny(request, assignment)
    if denied:
        return denied
    _persist_answers(assignment, request.POST)
    if _is_xhr(request):
        return JsonResponse({'ok': True, 'message': 'Сохранено ✓'})
    messages.success(request, 'Ответы сохранены (черновик).')
    return redirect('assignment_detail', pk=pk)


@student_required
@require_POST
def upload_photo(request, pk, task_id):
    assignment = _student_assignment(request, pk)
    if not assignment.is_editable_by_student:
        raise PermissionDenied('Работа уже отправлена на проверку.')
    # Несохранённый текст из формы ответов не должен пропасть из-за фото
    _persist_answers(assignment, request.POST)
    submission = _get_or_create_submission(assignment, task_id)

    from django.conf import settings
    files = request.FILES.getlist('photos')
    existing = submission.photos.count()
    max_count = settings.SUBMISSION_PHOTO_MAX_COUNT
    max_bytes = settings.SUBMISSION_PHOTO_MAX_SIZE_MB * 1024 * 1024
    added = 0
    for f in files:
        if existing + added >= max_count:
            messages.warning(
                request, f'Не больше {max_count} фото на задачу.')
            break
        if f.size > max_bytes:
            messages.warning(
                request,
                f'Файл {f.name} больше {settings.SUBMISSION_PHOTO_MAX_SIZE_MB} МБ — пропущен.')
            continue
        try:
            SubmissionPhoto.objects.create(submission=submission, image=f)
            added += 1
        except Exception:
            messages.warning(
                request,
                f'Файл {f.name} не похож на изображение (jpeg/png/webp) — пропущен.')
    if added:
        messages.success(request, f'Загружено фото: {added}.')
    return redirect('assignment_detail', pk=pk)


@student_required
@require_POST
def delete_photo(request, pk, photo_id):
    assignment = _student_assignment(request, pk)
    if not assignment.is_editable_by_student:
        raise PermissionDenied('Работа уже отправлена на проверку.')
    _persist_answers(assignment, request.POST)
    photo = get_object_or_404(
        SubmissionPhoto, pk=photo_id, submission__assignment=assignment)
    photo.image.delete(save=False)
    photo.delete()
    messages.success(request, 'Фото удалено.')
    return redirect('assignment_detail', pk=pk)


@student_required
@require_POST
def submit_assignment(request, pk):
    assignment = _student_assignment(request, pk)
    if not assignment.is_editable_by_student:
        raise PermissionDenied('Работа уже отправлена на проверку.')
    # Кнопка «Отправить» шлёт ту же форму, что и «Сохранить черновик»:
    # сначала записываем введённое, иначе учитель увидит пустую работу
    _persist_answers(assignment, request.POST)
    # Строки-ответы для видимых задач: скрытые не создаём
    hidden = set(assignment.hidden_items.values_list('pk', flat=True))
    for item in assignment.worksheet.ordered_items():
        if item.task_id is None or item.pk in hidden:
            continue
        Submission.objects.get_or_create(
            assignment=assignment, task=item.task)
    assignment.status = Assignment.STATUS_SUBMITTED
    assignment.submitted_at = timezone.now()
    assignment.save()
    messages.success(request, 'Работа отправлена на проверку.')
    return redirect('assignment_detail', pk=pk)


# --- Проверка (учитель) ---

def _teacher_assignment(request, pk):
    return get_object_or_404(
        Assignment.objects.select_related('worksheet', 'student'),
        pk=pk, worksheet__owner=request.user)


@teacher_required
def review_assignment(request, pk):
    assignment = _teacher_assignment(request, pk)
    rows = _assignment_rows(assignment, with_review=True)
    context = {
        'assignment': assignment,
        'rows': rows,
        'grade_choices': Review.GRADE_CHOICES,
        'is_points': assignment.grade_scale == Assignment.SCALE_POINTS,
    }
    context.update(_progress(rows))
    return render(request, 'assignments/review.html', context)


@teacher_required
@require_POST
def save_review(request, pk):
    assignment = _teacher_assignment(request, pk)
    action = request.POST.get('action', 'save')

    hidden_item_ids = set(assignment.hidden_items.values_list('pk', flat=True))
    visible_task_ids = set(
        assignment.worksheet.items.filter(task__isnull=False)
        .exclude(pk__in=hidden_item_ids)
        .values_list('task_id', flat=True))
    for submission in assignment.submissions.all():
        # Пропускаем только если у задачи нет ни одного видимого элемента
        if submission.task_id not in visible_task_ids:
            continue
        prefix = f'sub{submission.pk}'
        # Полей нет в POST — задачу скрыли или убрали из формы: отзыв не трогаем
        if (f'{prefix}_grade' not in request.POST
                and f'{prefix}_points' not in request.POST
                and f'{prefix}_comment' not in request.POST):
            continue
        grade_word = request.POST.get(f'{prefix}_grade', '')
        grade_points_raw = request.POST.get(f'{prefix}_points', '').strip()
        comment = request.POST.get(f'{prefix}_comment', '').strip()

        grade_points = None
        if grade_points_raw:
            try:
                grade_points = float(grade_points_raw.replace(',', '.'))
            except ValueError:
                messages.warning(
                    request,
                    f'Баллы «{grade_points_raw}» не распознаны — пропущено.')
        if grade_word not in dict(Review.GRADE_CHOICES):
            grade_word = ''

        if grade_word or grade_points is not None or comment:
            Review.objects.update_or_create(
                submission=submission,
                defaults={
                    'grade_word': grade_word,
                    'grade_points': grade_points,
                    'comment': comment,
                    'reviewer': request.user,
                })
        else:
            Review.objects.filter(submission=submission).delete()

    if action == 'complete':
        assignment.status = Assignment.STATUS_REVIEWED
        assignment.reviewed_at = timezone.now()
        assignment.save()
        messages.success(request, 'Проверка завершена, ученик увидит результаты.')
        return redirect('dashboard')
    if action == 'return':
        assignment.status = Assignment.STATUS_RETURNED
        assignment.save()
        messages.success(request, 'Работа возвращена ученику на доработку.')
        return redirect('dashboard')
    messages.success(request, 'Проверка сохранена (черновик).')
    return redirect('review_assignment', pk=pk)


# --- Раздача фото решений (приватные файлы) ---

def photo_file(request, photo_id):
    """Фото решения видят только сам ученик и его учитель (владелец листка)."""
    if not request.user.is_authenticated:
        raise PermissionDenied
    photo = get_object_or_404(
        SubmissionPhoto.objects.select_related(
            'submission__assignment__worksheet'),
        pk=photo_id)
    assignment = photo.submission.assignment
    allowed = (request.user.pk == assignment.student_id
               or request.user.pk == assignment.worksheet.owner_id
               or request.user.is_superuser)
    if not allowed:
        raise PermissionDenied
    return FileResponse(photo.image.open('rb'), content_type='image/jpeg')

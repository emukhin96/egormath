from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Case, Count, DateTimeField, IntegerField, Q, When
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import student_required, teacher_required
from problems.models import Task
from worksheets.models import Worksheet

from .checks import reference_text
from .forms import AssignmentCreateForm
from .models import (Assignment, Review, Submission, SubmissionPart,
                     SubmissionPhoto, locked_check_visibility, wrap_math)


# --- Назначение листка ученикам (действие учителя со страницы листка) ---

def _check_visibility_or_default(post):
    value = post.get('check_visibility', Assignment.CHECK_TEACHER)
    if value not in dict(Assignment.CHECK_CHOICES):
        return Assignment.CHECK_TEACHER
    return value


def _create_assignments(*, worksheet, teacher, students, check_visibility,
                        allow_photos, due_at):
    """Создать назначения без дублей; используется обеими точками выдачи."""
    created = 0
    for student in students:
        _, was_created = Assignment.objects.get_or_create(
            worksheet=worksheet, student=student,
            defaults={
                'assigned_by': teacher,
                'check_visibility': check_visibility,
                'allow_photos': allow_photos,
                'due_at': due_at,
            })
        created += was_created
    return created


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
    check_visibility = (locked_check_visibility(worksheet)
                        or _check_visibility_or_default(request.POST))
    allow_photos = 'allow_photos' in request.POST
    due_at = request.POST.get('due_at') or None

    my_students = request.user.students.filter(
        role='student', user_id__in=student_ids)
    created = _create_assignments(
        worksheet=worksheet,
        teacher=request.user,
        students=(profile.user for profile in my_students),
        check_visibility=check_visibility,
        allow_photos=allow_photos,
        due_at=due_at,
    )
    if created:
        messages.success(request, f'Назначено ученикам: {created}.')
    else:
        messages.info(request, 'Новых назначений нет (уже были назначены).')
    return redirect('worksheet_detail', pk=worksheet.pk)


# --- Все назначения учителя ---

@teacher_required
def assignment_list(request):
    """Единая очередь выданных работ с рабочими фильтрами."""
    now = timezone.now()
    assignments = (Assignment.objects
                   .filter(worksheet__owner=request.user)
                   .select_related('worksheet', 'student'))

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    student_id = request.GET.get('student', '').strip()
    worksheet_id = request.GET.get('worksheet', '').strip()
    due = request.GET.get('due', '').strip()

    if q:
        assignments = assignments.filter(
            Q(worksheet__title__icontains=q)
            | Q(student__first_name__icontains=q)
            | Q(student__last_name__icontains=q)
            | Q(student__username__icontains=q))
    if status in dict(Assignment.STATUS_CHOICES):
        assignments = assignments.filter(status=status)
    if student_id.isdigit():
        assignments = assignments.filter(student_id=student_id)
    if worksheet_id.isdigit():
        assignments = assignments.filter(worksheet_id=worksheet_id)
    if due == 'overdue':
        assignments = assignments.filter(
            status__in=(Assignment.STATUS_ASSIGNED,
                        Assignment.STATUS_RETURNED),
            due_at__lt=now)
    elif due == 'today':
        assignments = assignments.filter(due_at__date=timezone.localdate())
    elif due == 'week':
        assignments = assignments.filter(
            due_at__gte=now, due_at__lte=now + timedelta(days=7))
    elif due == 'none':
        assignments = assignments.filter(due_at__isnull=True)

    # Сначала ручная очередь учителя, затем работы, требующие действий ученика.
    assignments = assignments.annotate(
        queue_order=Case(
            When(status=Assignment.STATUS_SUBMITTED, then=0),
            When(status=Assignment.STATUS_RETURNED, then=1),
            When(status=Assignment.STATUS_ASSIGNED, then=2),
            default=3, output_field=IntegerField()),
        due_order=Case(
            When(due_at__isnull=True, then=1),
            default=0, output_field=IntegerField()),
        # У отправленных работ порядок совпадает с экраном проверки: раньше
        # прислано — раньше в очереди. Для остальных решает ближайший срок.
        submitted_order=Case(
            When(status=Assignment.STATUS_SUBMITTED, then='submitted_at'),
            default=None, output_field=DateTimeField()),
    ).order_by(
        'queue_order', 'submitted_order', 'due_order', 'due_at', '-assigned_at')

    all_assignments = Assignment.objects.filter(worksheet__owner=request.user)
    stats = all_assignments.aggregate(
        total=Count('pk'),
        submitted=Count('pk', filter=Q(status=Assignment.STATUS_SUBMITTED)),
        returned=Count('pk', filter=Q(status=Assignment.STATUS_RETURNED)),
        assigned=Count('pk', filter=Q(status=Assignment.STATUS_ASSIGNED)),
        reviewed=Count('pk', filter=Q(status=Assignment.STATUS_REVIEWED)),
        overdue=Count('pk', filter=Q(
            status__in=(Assignment.STATUS_ASSIGNED,
                        Assignment.STATUS_RETURNED), due_at__lt=now)),
    )
    page = Paginator(assignments, 30).get_page(request.GET.get('page'))
    students = (request.user.students
                .filter(role='student')
                .select_related('user')
                .order_by('user__last_name', 'user__first_name'))
    worksheets = Worksheet.objects.filter(
        owner=request.user).order_by('-updated_at')
    return render(request, 'assignments/assignment_list.html', {
        'page': page,
        'assignments': page.object_list,
        'stats': stats,
        'students': students,
        'worksheets': worksheets,
        'status_choices': Assignment.STATUS_CHOICES,
        'due_choices': [
            ('overdue', 'Просроченные'),
            ('today', 'Срок сегодня'),
            ('week', 'Срок в ближайшие 7 дней'),
            ('none', 'Без срока'),
        ],
        'filters': {
            'q': q, 'status': status, 'student': student_id,
            'worksheet': worksheet_id, 'due': due,
        },
    })


@teacher_required
def assignment_create(request):
    """Выдать один листок нескольким адресатам из отдельного мастера."""
    initial = {'allow_photos': True}
    worksheet_id = request.GET.get('worksheet', '')
    if worksheet_id.isdigit():
        initial['worksheet'] = Worksheet.objects.filter(
            owner=request.user, pk=worksheet_id).first()
    form = AssignmentCreateForm(
        request.POST or None, teacher=request.user, initial=initial)
    if request.method == 'POST' and form.is_valid():
        created = _create_assignments(
            worksheet=form.cleaned_data['worksheet'],
            teacher=request.user,
            students=form.cleaned_data['recipients'],
            check_visibility=form.cleaned_data['check_visibility'],
            allow_photos=form.cleaned_data['allow_photos'],
            due_at=form.cleaned_data['due_at'],
        )
        selected = form.cleaned_data['recipients'].count()
        skipped = selected - created
        if created:
            messages.success(request, f'Создано назначений: {created}.')
        if skipped:
            messages.info(
                request, f'Уже были выданы и пропущены: {skipped}.')
        return redirect('assignment_list')
    return render(request, 'assignments/assignment_create.html', {
        'form': form,
    })


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
        task = item.task
        # Краткий ответ — только по рабочей маске; иначе ученику доступно
        # лишь фото решения. Маска подпункта — своя у каждого подпункта
        short_answer = task.short_answer_available(subitems)
        subrows = []
        for s in subitems:
            prefix = f'task{item.task_id}_sub{s.pk}'
            part = parts.get(s.pk)
            spec = s.mask_spec if short_answer and s.has_mask else None
            subrows.append({
                'subitem': s, 'part': part, 'prefix': prefix, 'spec': spec,
                'fragments': _mask_fragments(spec, part, prefix, with_review),
                'mask_reference': reference_text(spec) if spec else '',
            })
        prefix = f'task{item.task_id}'
        spec = task.mask_spec if short_answer and not subitems else None
        # «Отвечено» — есть текст на задаче/любом подпункте или фото;
        # только по prefetch-данным, без дополнительных запросов
        answered = bool(submission) and bool(
            submission.display_answer
            or any(sr['part'] and sr['part'].display_answer for sr in subrows)
            or submission.photos.all())
        review = getattr(submission, 'review', None) if submission else None
        # Все выбранные подпункты (или задача целиком) сошлись с эталоном —
        # учителю подсказка «выполнено» по умолчанию. Частичный ответ
        # (верно только один из нескольких подпунктов) флажок не ставит.
        if subrows:
            auto_ok = all(
                sr['part'] is not None
                and sr['part'].display_answer
                and sr['part'].auto_check == Submission.CHECK_OK
                for sr in subrows)
        else:
            auto_ok = bool(
                submission and submission.display_answer
                and submission.auto_check == Submission.CHECK_OK)
        rows.append({
            'item': item,
            'task': task,
            'number': number,
            'prefix': prefix,
            'submission': submission,
            'review': review,
            'answered': answered,
            'auto_ok': auto_ok,
            'short_answer': short_answer,
            'spec': spec,
            'fragments': _mask_fragments(spec, submission, prefix, with_review),
            'mask_reference': reference_text(spec) if spec else '',
            'has_comment': bool(review and review.comment),
            'subrows': subrows,
        })
    return rows


def _mask_fragments(spec, obj, prefix, for_teacher):
    """Слоты маски для шаблона: с ответом ученика, если он есть, иначе пустые."""
    if spec is None:
        return None
    if obj is not None:
        return obj.mask_fragments(prefix, for_teacher=for_teacher)
    from .checks import render_fragments
    return render_fragments(spec, prefix, seed=prefix)


def _progress(rows):
    """Счётчики для сайдбара и подтверждения отправки."""
    task_rows = [r for r in rows if r['task'] is not None]
    done = sum(1 for r in task_rows if r['review'] and r['review'].done)
    total = len(task_rows)
    return {
        'task_rows': task_rows,
        'task_count': total,
        'answered_count': sum(1 for r in task_rows if r['answered']),
        'unanswered_numbers': [
            r['number'] for r in task_rows if not r['answered']],
        'result': {'done': done, 'total': total,
                   'percent': round(100 * done / total) if total else 0},
    }


@student_required
def assignment_detail(request, pk):
    assignment = _student_assignment(request, pk)
    rows = _assignment_rows(assignment)
    show_checks = assignment.student_sees_checks
    if show_checks:
        _refresh_stale_checks(rows)
    editable = assignment.is_editable_by_student
    context = {
        'assignment': assignment,
        'rows': rows,
        'editable': editable,
        'show_checks': show_checks,
        # Кнопка «Проверить» — только когда ученик и так вправе видеть
        # результат до сдачи; в остальных режимах её нет вовсе
        'can_check': show_checks and editable,
        'can_upload': editable and assignment.allow_photos,
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
    Task.ANSWER_FORMULA: (('answer_text', 'text'),),
}


def _answer_fields(answer_type, post, prefix):
    """Поля ответа по типу задачи из POST с данным префиксом.

    Возвращаются только поля, реально присланные формой: тогда POST без
    полей ответов (например, форма загрузки фото) не затирает
    сохранённое пустыми строками. Формула из <math-field> приходит голым
    LaTeX и хранится как ``$…$`` (конвенция answer_latex).
    """
    suffixes = _ANSWER_FIELD_SUFFIXES.get(
        answer_type, _ANSWER_FIELD_SUFFIXES[Task.ANSWER_TEXT])
    fields = {
        field: post[f'{prefix}_{suffix}'].strip()
        for field, suffix in suffixes
        if f'{prefix}_{suffix}' in post
    }
    if answer_type == Task.ANSWER_FORMULA and 'answer_text' in fields:
        fields['answer_text'] = wrap_math(fields['answer_text'])
    return fields


def _answer_payload(owner, answer_type, post, prefix):
    """Что сохранить для задачи/подпункта ``owner``: слоты маски
    (``answer_json``) при рабочей маске, иначе старые свободные поля.
    Пустой словарь — форма этих полей не присылала."""
    spec = owner.mask_spec
    if spec is not None and spec.is_valid:
        from .checks import collect_values
        values = collect_values(post, prefix, spec)
        return ({'answer_json': values}, spec) if values else ({}, spec)
    return _answer_fields(answer_type, post, prefix), None


def _persist_answers(assignment, post):
    """Записывает присланные поля ответов по всем видимым задачам.

    Единая точка для сохранения черновика, отправки на проверку и действий
    с фото: любой POST со страницы задания сначала сохраняет введённое,
    иначе ответы теряются при уходе со страницы. У задач с подпунктами —
    отдельный ответ на каждый подпункт (SubmissionPart), у остальных —
    ответ на задачу целиком. Сразу же сверяет записанное с эталоном
    (auto_check — учителю), а раскрытый ученику результат (check_revealed)
    сбрасывает при смене ответа: новый ответ — новая кнопка «Проверить».
    """
    hidden = set(assignment.hidden_items.values_list('pk', flat=True))
    existing = {s.task_id: s for s in assignment.submissions.all()}

    def _apply(obj, fields, reference, spec):
        before = obj.display_answer
        for name, value in fields.items():
            if name == 'answer_json':
                merged = dict(obj.answer_json or {})
                merged.update(value)
                value = merged
            setattr(obj, name, value)
        obj.run_check(reference, spec=spec)
        if obj.display_answer != before:
            obj.check_revealed = False
        obj.save()

    def _has_value(fields):
        return any(
            any(v.values()) if isinstance(v, dict) else v
            for v in fields.values())

    for item in assignment.worksheet.ordered_items():
        if item.task_id is None or item.pk in hidden:
            continue
        task = item.task
        prefix = f'task{task.pk}'
        subitems = item.selected_subitems()
        if subitems:
            part_fields = {
                s: _answer_payload(s, task.answer_type, post, f'{prefix}_sub{s.pk}')
                for s in subitems
            }
            part_fields = {s: fs for s, fs in part_fields.items() if fs[0]}
            if not part_fields:
                continue
            has_values = any(_has_value(f) for f, _ in part_fields.values())
            if not (has_values or task.pk in existing):
                continue
            submission = existing.get(task.pk)
            if submission is None:
                submission, _ = Submission.objects.get_or_create(
                    assignment=assignment, task=task)
                existing[task.pk] = submission
            for subitem, (fields, spec) in part_fields.items():
                part, _ = SubmissionPart.objects.get_or_create(
                    submission=submission, subitem=subitem)
                _apply(part, fields, subitem.effective_answer_latex, spec)
            continue
        fields, spec = _answer_payload(task, task.answer_type, post, prefix)
        if not fields:
            continue
        if _has_value(fields) or task.pk in existing:
            submission = existing.get(task.pk)
            if submission is None:
                submission, _ = Submission.objects.get_or_create(
                    assignment=assignment, task=task)
                existing[task.pk] = submission
            _apply(submission, fields, task.effective_answer_latex, spec)


def _refresh_stale_checks(rows, for_teacher=False):
    """На экране проверки: пересчёт сверки, если эталон правили после неё."""
    for row in rows:
        # У рубрик и текстовых вставок нет ни задачи, ни ответа
        task = row.get('task')
        submission = row.get('submission')
        if task is None or submission is None:
            continue
        if row['subrows']:
            for sr in row['subrows']:
                part = sr['part']
                if part and part.display_answer and part.check_is_stale(task):
                    part.run_check(sr['subitem'].effective_answer_latex,
                                   spec=sr['subitem'].mask_spec)
                    part.save(update_fields=['auto_check', 'check_json', 'checked_at'])
                    sr['fragments'] = _mask_fragments(
                        sr['spec'], part, sr['prefix'], for_teacher)
        elif submission.display_answer and submission.check_is_stale(task):
            submission.run_check(task.effective_answer_latex, spec=task.mask_spec)
            submission.save(update_fields=['auto_check', 'check_json', 'checked_at'])
            row['fragments'] = _mask_fragments(
                row['spec'], submission, row['prefix'], for_teacher)


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
        # Результат сверки в ответ автосохранения не попадает ни в одном
        # режиме: ученик узнаёт его только кнопкой «Проверить»
        return JsonResponse({'ok': True, 'message': 'Сохранено ✓'})
    messages.success(request, 'Ответы сохранены (черновик).')
    return redirect('assignment_detail', pk=pk)


@student_required
@require_POST
def check_task(request, pk, task_id):
    """Кнопка «Проверить» у задачи: раскрыть ученику результат сверки.

    Сначала сохраняет всю форму (кнопка шлёт её целиком), затем помечает
    ответ задачи (или все её подпункты) как раскрытые и считает нажатие.
    Доступно только в режимах, где ученик вправе видеть результат до
    сдачи; для fetch — JSON «префикс → результат», иначе redirect к задаче.
    """
    assignment = _student_assignment(request, pk)
    denied = _editable_or_deny(request, assignment)
    if denied:
        return denied
    if not assignment.student_sees_checks:
        raise PermissionDenied('Результат сверки в этом задании не показывается.')
    _persist_answers(assignment, request.POST)
    task = get_object_or_404(Task, pk=task_id)
    item = _visible_task_item(assignment, task)
    subitems = item.selected_subitems()
    if not task.short_answer_available(subitems):
        # Кнопка на странице отключена; прямой запрос — без раскрытия и попытки
        message = 'У этой задачи нет маски ответа — решение проверит учитель'
        if _is_xhr(request):
            return JsonResponse({'ok': False, 'message': message, 'checks': {}},
                                status=400)
        messages.info(request, message)
        return redirect(f"{reverse('assignment_detail', args=[pk])}"
                        f"#task-{_visible_task_number(assignment, item)}")
    submission, _ = Submission.objects.get_or_create(
        assignment=assignment, task=task)

    def _reveal(obj, prefix):
        """Раскрыть результат: итог по полю и по каждому слоту маски."""
        obj.check_revealed = True
        obj.save(update_fields=['check_revealed'])
        checks[prefix] = obj.auto_check
        for slot, status in (obj.check_json or {}).items():
            checks[f'{prefix}_{slot}'] = status

    checks = {}
    if subitems:
        parts = {p.subitem_id: p for p in submission.parts.all()}
        for subitem in subitems:
            part = parts.get(subitem.pk)
            if part is None or not part.display_answer:
                continue
            _reveal(part, f'task{task.pk}_sub{subitem.pk}')
    elif submission.display_answer:
        _reveal(submission, f'task{task.pk}')
    if checks:
        submission.check_attempts += 1
        submission.save(update_fields=['check_attempts'])
        message = 'Проверено'
    else:
        message = 'Сначала введите ответ'

    if _is_xhr(request):
        return JsonResponse({'ok': True, 'message': message, 'checks': checks})
    messages.info(request, message)
    number = _visible_task_number(assignment, item)
    return redirect(f"{reverse('assignment_detail', args=[pk])}#task-{number}")


def _visible_task_number(assignment, item):
    """Номер задачи на странице ученика (без скрытых элементов)."""
    hidden = set(assignment.hidden_items.values_list('pk', flat=True))
    number = 0
    for other in assignment.worksheet.ordered_items():
        if other.task_id is None or other.pk in hidden:
            continue
        number += 1
        if other.pk == item.pk:
            return number
    return number


@student_required
@require_POST
def upload_photo(request, pk, task_id):
    assignment = _student_assignment(request, pk)
    if not assignment.is_editable_by_student:
        raise PermissionDenied('Работа уже отправлена на проверку.')
    if not assignment.allow_photos:
        raise PermissionDenied('Учитель не принимает фото решений в этом задании.')
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


def _pending_review_queue(teacher):
    return (Assignment.objects
            .filter(worksheet__owner=teacher,
                    status=Assignment.STATUS_SUBMITTED)
            .select_related('worksheet', 'student')
            .order_by('submitted_at', 'pk'))


def _review_queue_state(teacher, assignment):
    """Размер очереди, позиция текущей работы и следующая после неё."""
    pending = list(_pending_review_queue(teacher))
    position = None
    next_pending = None
    for index, item in enumerate(pending):
        if item.pk == assignment.pk:
            position = index + 1
            if index + 1 < len(pending):
                next_pending = pending[index + 1]
            break
    if position is None and pending:
        next_pending = pending[0]
    return len(pending), position, next_pending


@teacher_required
def review_assignment(request, pk):
    assignment = _teacher_assignment(request, pk)
    rows = _assignment_rows(assignment, with_review=True)
    _refresh_stale_checks(rows, for_teacher=True)
    queue_total, queue_position, next_pending = _review_queue_state(
        request.user, assignment)
    context = {
        'assignment': assignment,
        'rows': rows,
        'queue_total': queue_total,
        'queue_position': queue_position,
        'next_pending': next_pending,
    }
    context.update(_progress(rows))
    return render(request, 'assignments/review.html', context)


@teacher_required
@require_POST
def save_review(request, pk):
    assignment = _teacher_assignment(request, pk)
    action = request.POST.get('action', 'save')
    _, _, next_pending = _review_queue_state(request.user, assignment)

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
        # Полей нет в POST — задачу скрыли или убрали из формы: отзыв не
        # трогаем. Чекбокс в POST не приходит, когда снят, поэтому признак
        # присутствия строки — поле комментария
        if f'{prefix}_comment' not in request.POST:
            continue
        done = f'{prefix}_done' in request.POST
        comment = request.POST.get(f'{prefix}_comment', '').strip()
        # Строка есть в форме — сохраняем явное done=False, даже без
        # комментария. Иначе снятие автофлажка удаляет Review, и при
        # следующем открытии auto_ok снова включит «Выполнено».
        Review.objects.update_or_create(
            submission=submission,
            defaults={
                'done': done,
                'comment': comment,
                'reviewer': request.user,
            })

    if action in ('complete', 'complete_next'):
        assignment.status = Assignment.STATUS_REVIEWED
        assignment.reviewed_at = timezone.now()
        assignment.save()
        messages.success(request, 'Проверка завершена, ученик увидит результаты.')
        if action == 'complete_next' and next_pending:
            return redirect(
                'review_assignment', pk=next_pending.pk)
        return redirect('assignment_list')
    if action in ('return', 'return_next'):
        assignment.status = Assignment.STATUS_RETURNED
        assignment.save()
        messages.success(request, 'Работа возвращена ученику на доработку.')
        if action == 'return_next' and next_pending:
            return redirect(
                'review_assignment', pk=next_pending.pk)
        return redirect('assignment_list')
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

from assignments.checks import HELP as MASK_HELP
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, models, transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from django.utils.dateparse import parse_date

from accounts.decorators import get_role, teacher_required
from accounts.models import Profile, StudentGroup
from assignments.models import Assignment, locked_check_visibility
from problems.models import Task, Topic, topic_tree
from problems.rubricator import (GRADE_LEVEL_TO_CODE, apply_worksheet_taxonomy,
                                 dumps_state, filter_by_taxonomy,
                                 filter_state_from_params, parse_grade_choice,
                                 set_grade_bands, taxonomy_page_context,
                                 taxonomy_state_from_post,
                                 worksheet_taxonomy_state)
from problems.views import filter_tasks

from .corpus import corpus_key_from_comment
from .forms import WorksheetForm
from .import_tex import (TexImportError, create_worksheet,
                         match_existing_tasks, parse_tex)
from .beamer import worksheet_to_beamer
from .latex import worksheet_to_tex
from .models import (Collection, PdfCompileLock, ShareLink, Worksheet,
                     WorksheetItem, WorksheetPdf)
from .services import (LatexCompileError, collect_assets, collect_beamer_assets,
                       compile_latex, get_worksheet_pdf)


def _own_worksheet(request, pk):
    return get_object_or_404(Worksheet.visible_to(request.user), pk=pk)


def _builder_response(request, pk, ok=True, message=''):
    """Ответ view конструктора: JSON для fetch-автосохранения, иначе redirect."""
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': ok, 'message': message},
                            status=200 if ok else 400)
    if message:
        (messages.success if ok else messages.error)(request, message)
    return redirect('worksheet_detail', pk=pk)


WORKSHEET_ORDERINGS = {
    '-updated_at', 'updated_at', '-created_at', 'created_at',
    'title', '-title',
}


@teacher_required
def worksheet_list(request):
    """Каталог листков: фильтры по классу/теме/датам и сортировка."""
    params = request.GET
    worksheets = (Worksheet.visible_to(request.user).filter(
                      collection__isnull=True)
                  .select_related('owner')
                  .prefetch_related('topics', 'grade_bands')
                  .annotate(items_total=models.Count('items', distinct=True)))

    owner_id = params.get('owner', '').strip()
    if request.user.is_superuser and owner_id.isdigit():
        worksheets = worksheets.filter(owner_id=owner_id)
    elif not request.user.is_superuser:
        owner_id = ''

    worksheets = filter_by_taxonomy(
        worksheets, params,
        topics_lookups=('topics', 'items__task__topics'))
    current_topic = None
    topic_ids = params.getlist('topic')
    if len(topic_ids) == 1:
        current_topic = Topic.objects.filter(pk=topic_ids[0]).first()

    for param, lookup in (('created_from', 'created_at__date__gte'),
                          ('created_to', 'created_at__date__lte'),
                          ('updated_from', 'updated_at__date__gte'),
                          ('updated_to', 'updated_at__date__lte')):
        date = parse_date(params.get(param, ''))
        if date:
            worksheets = worksheets.filter(**{lookup: date})

    order = params.get('order', '-updated_at')
    if order not in WORKSHEET_ORDERINGS:
        order = '-updated_at'
    worksheets = worksheets.order_by(order)

    ctx = taxonomy_page_context(filter_state_from_params(params))
    ctx.update({
        'worksheets': worksheets,
        'params': params,
        'order': order,
        'grade_choices': Task.GRADE_CHOICES,
        'topics': Topic.objects.filter(parent=None),
        'current_topic': current_topic,
        'owner_filter': owner_id,
        'owners': (get_user_model().objects.filter(
            worksheets__collection__isnull=True).distinct()
            .order_by('last_name', 'first_name', 'username')
            if request.user.is_superuser else []),
    })
    for w in worksheets:
        w.taxonomy_json = dumps_state(worksheet_taxonomy_state(w))
        w.corpus_key = corpus_key_from_comment(w.comment)
    return render(request, 'worksheets/worksheet_list.html', ctx)


def _import_overrides(post, parsed):
    """Назначения задачам из предпросмотра импорта: класс/тема/звёзды/ответ.

    У задач с подпунктами ответы/решения собираются по подпунктам
    (answer_N_M / solution_N_M); skip_N помечает строку «удалена
    из импорта».
    """
    overrides = {}
    # Только реально существующие темы: поддельный или устаревший id
    # иначе уронит task.topics.add() уже после создания части объектов
    valid_topics = set(Topic.objects.values_list('pk', flat=True))
    for i, (kind, data) in enumerate(parsed['elements']):
        if kind != 'task':
            continue
        extra = {}
        if post.get(f'skip_{i}'):
            overrides[i] = {'skip': True}
            continue
        grade, grade_ok = parse_grade_choice(post.get(f'grade_{i}', ''))
        if grade_ok and grade is not None:
            extra['grade_level'] = grade
        topic = post.get(f'topic_{i}', '').strip()
        if topic.isdigit() and int(topic) in valid_topics:
            extra['topic_id'] = int(topic)
        stars = post.get(f'stars_{i}', '').strip()
        if stars.isdigit():
            extra['stars'] = max(0, min(3, int(stars)))
        if f'answer_{i}' in post:
            extra['answer'] = post[f'answer_{i}'].strip()
        if f'solution_{i}' in post:
            extra['solution'] = post[f'solution_{i}'].strip()
        sub_answers = {}
        sub_solutions = {}
        for j in range(len(data['subitems'])):
            if f'answer_{i}_{j}' in post:
                sub_answers[j] = post[f'answer_{i}_{j}'].strip()
            if f'solution_{i}_{j}' in post:
                sub_solutions[j] = post[f'solution_{i}_{j}'].strip()
        if sub_answers:
            extra['subitem_answers'] = sub_answers
        if sub_solutions:
            extra['subitem_solutions'] = sub_solutions
        if extra:
            overrides[i] = extra
    return overrides


@teacher_required
def worksheet_import(request):
    """Импорт .tex-листка (пакет egor): вставка/файл → предпросмотр → создание."""
    context = {
        'tex': '', 'preview': None,
        'grade_choices': Task.GRADE_CHOICES,
        'topics': topic_tree(),
        'gemini_ready': bool(settings.GEMINI_API_KEY),
    }
    context.update(taxonomy_page_context())
    if request.method == 'POST':
        tex = request.POST.get('tex', '')
        upload = request.FILES.get('file')
        if upload:
            try:
                tex = upload.read().decode('utf-8')
            except UnicodeDecodeError:
                messages.error(request, 'Файл не в кодировке UTF-8.')
                return render(request, 'worksheets/import.html', context)
        context['tex'] = tex
        try:
            parsed = parse_tex(tex)
        except TexImportError as exc:
            messages.error(request, f'Ошибка разбора: {exc}')
            return render(request, 'worksheets/import.html', context)

        if request.POST.get('action') == 'create':
            # Атомарно: при любой ошибке не остаётся полусозданный листок
            with transaction.atomic():
                worksheet, missing_images = create_worksheet(
                    parsed, owner=request.user,
                    overrides=_import_overrides(request.POST, parsed))
            messages.success(
                request,
                f'Листок «{worksheet.title}» импортирован '
                f'({worksheet.items.count()} элементов).')
            for row in missing_images:
                messages.warning(request, format_html(
                    'Задаче <a href="{}">#{}</a> нужны картинки: {} — '
                    'догрузите файлы на странице задачи (в том же порядке).',
                    reverse('task_detail', args=[row['task'].pk]),
                    row['task'].pk, ', '.join(row['files'])))
            return redirect('worksheet_detail', pk=worksheet.pk)

        matches = match_existing_tasks(parsed)
        existing = (Task.objects.prefetch_related('subitems')
                    .in_bulk([m for m in matches if m]))
        rows = []
        for (kind, data), match in zip(parsed['elements'], matches):
            row = {'kind': kind, 'data': data, 'existing_id': match}
            if kind == 'task':
                # Поля ответа/решения предзаполняются: для найденных
                # в базе — текущими значениями задачи, для новых — из .tex
                source = existing[match] if match else None
                row['answer_value'] = (
                    source.answer_latex if source else data['answer'])
                row['solution_value'] = (
                    source.solution_latex if source else data['solution'])
                # У задач с подпунктами — поля на каждый подпункт
                db_subs = list(source.subitems.all()) if source else []
                row['sub_rows'] = [
                    {'text': chunk,
                     'answer': (db_subs[j].answer_latex
                                if j < len(db_subs) else ''),
                     'solution': (db_subs[j].solution_latex
                                  if j < len(db_subs) else '')}
                    for j, chunk in enumerate(data['subitems'])
                ]
            rows.append(row)
        context['preview'] = {
            'header': parsed['header'],
            'rows': rows,
            'new_tasks': sum(1 for r in rows
                             if r['kind'] == 'task' and not r['existing_id']),
        }
        # Исходные тексты задач для кнопок нейрогенерации (json_script):
        # из KaTeX-рендера LaTeX обратно не достать
        context['solve_payloads'] = {
            str(i): {'text': data['text'], 'subitems': data['subitems']}
            for i, (kind, data) in enumerate(parsed['elements'])
            if kind == 'task'
        }
    return render(request, 'worksheets/import.html', context)


@teacher_required
@require_POST
def worksheet_import_solve(request):
    """Тот же эндпоинт, что /problems/solve/: черновик для предпросмотра."""
    from problems.views import task_neuro_solve
    return task_neuro_solve(request)


@teacher_required
def worksheet_create(request):
    if request.method == 'POST':
        form = WorksheetForm(request.POST)
        if form.is_valid():
            worksheet = form.save(commit=False)
            worksheet.owner = request.user
            worksheet.save()
            apply_worksheet_taxonomy(worksheet, request.POST)
            messages.success(request, 'Листок создан. Добавьте в него задачи.')
            return redirect('worksheet_detail', pk=worksheet.pk)
    else:
        form = WorksheetForm()
    tax_state = (taxonomy_state_from_post(request.POST)
                 if request.method == 'POST' else None)
    ctx = taxonomy_page_context(tax_state)
    ctx.update({'form': form})
    return render(request, 'worksheets/worksheet_form.html', ctx)


@teacher_required
def worksheet_edit(request, pk):
    worksheet = _own_worksheet(request, pk)
    if request.method == 'POST':
        form = WorksheetForm(request.POST, instance=worksheet)
        if form.is_valid():
            form.save()
            apply_worksheet_taxonomy(worksheet, request.POST)
            messages.success(request, 'Листок сохранён.')
            return redirect('worksheet_detail', pk=worksheet.pk)
    else:
        form = WorksheetForm(instance=worksheet)
    tax_state = (taxonomy_state_from_post(request.POST)
                 if request.method == 'POST'
                 else worksheet_taxonomy_state(worksheet))
    ctx = taxonomy_page_context(tax_state)
    ctx.update({'form': form, 'worksheet': worksheet})
    return render(request, 'worksheets/worksheet_form.html', ctx)


@teacher_required
def worksheet_detail(request, pk):
    """Конструктор листка: задачи, поиск по базе, назначение, ссылки."""
    worksheet = _own_worksheet(request, pk)
    items = list(worksheet.ordered_items())
    # И активные, и в корзине — чтобы удалённая задача не всплыла
    # в поиске конструктора и не добавилась второй раз
    task_ids = list(worksheet.items.exclude(task_id=None)
                    .values_list('task_id', flat=True))
    deleted_items = list(worksheet.items.filter(deleted_at__isnull=False)
                         .select_related('task'))

    # Кто скрывает какие элементы: {item_id: {pk ссылок/назначений}}
    share_links = list(worksheet.share_links.order_by('-created_at')
                       .prefetch_related('hidden_items'))
    assignments = list(worksheet.assignments.select_related('student')
                       .prefetch_related(
                           'hidden_items', 'submissions__check_history'))
    link_hidden = {}
    for link in share_links:
        for hidden_item in link.hidden_items.all():
            link_hidden.setdefault(hidden_item.pk, set()).add(link.pk)
    assignment_hidden = {}
    for assignment in assignments:
        for hidden_item in assignment.hidden_items.all():
            assignment_hidden.setdefault(
                hidden_item.pk, set()).add(assignment.pk)

    task_numbers = {}
    number = 0
    for item in items:
        if item.task_id:
            number += 1
            task_numbers.setdefault(item.task_id, []).append(number)
    for assignment in assignments:
        assignment.self_check_total = 0
        assignment.self_check_tasks = []
        for submission in assignment.submissions.all():
            if (not submission.check_attempts
                    or submission.task_id not in task_numbers):
                continue
            history = list(submission.check_history.all())
            assignment.self_check_total += submission.check_attempts
            assignment.self_check_tasks.append({
                'numbers': ', '.join(
                    str(value) for value in task_numbers.get(
                        submission.task_id, [])),
                'attempts': submission.check_attempts,
                'latest': history[-1] if history else None,
            })

    # Строки конструктора: сквозная нумерация только для задач
    rows = []
    number = 0
    for item in items:
        if item.task_id:
            number += 1
        rows.append({
            'item': item,
            'number': number if item.task_id else None,
            'selected_ids': ({s.pk for s in item.subitems.all()}
                             if item.task_id and not item.all_subitems
                             else None),
            'hidden_links': link_hidden.get(item.pk, set()),
            'hidden_assignments': assignment_hidden.get(item.pk, set()),
        })

    from .block_presentation import decorate_block_rows
    decorate_block_rows(rows)

    # Поиск задач для добавления (правая часть страницы)
    search_active = any(request.GET.get(k) for k in ('q', 'topic', 'grade', 'tag'))
    found_tasks = []
    if search_active:
        found_tasks = filter_tasks(request.GET).exclude(pk__in=task_ids)[:15]

    student_profiles = (Profile.students_for(request.user)
                        .select_related('user')
                        .order_by('user__last_name'))
    assigned_ids = set(
        worksheet.assignments.values_list('student_id', flat=True))
    groups = StudentGroup.visible_to(request.user).prefetch_related('students')
    # Листок уже выдан — режим сверки зафиксирован первым назначением
    locked_check = locked_check_visibility(worksheet) if assignments else None

    collection = Collection.objects.filter(worksheet=worksheet).first()
    return render(request, 'worksheets/worksheet_detail.html', {
        'worksheet': worksheet,
        'mask_help': MASK_HELP,
        'collection': collection,
        'items': items,
        'rows': rows,
        'found_tasks': found_tasks,
        'search_active': search_active,
        'params': request.GET,
        'student_profiles': student_profiles,
        'assigned_ids': assigned_ids,
        'check_choices': Assignment.CHECK_CHOICES,
        'locked_check': locked_check,
        'groups': groups,
        'stars_choices': Task.STARS_CHOICES,
        'grade_choices': Task.GRADE_CHOICES,
        'share_links': share_links,
        'assignments': assignments,
        'deleted_items': deleted_items,
    })


@teacher_required
def collection_list(request):
    """Каталог опубликованных подборок и черновиков текущего редактора."""
    visible = (models.Q() if request.user.is_superuser
               else models.Q(is_published=True)
               | models.Q(worksheet__owner=request.user))
    collections = (Collection.objects
                   .filter(visible)
                   .select_related('worksheet', 'source', 'parent')
                   .prefetch_related('children')
                   .annotate(items_total=models.Count(
                       'worksheet__items',
                       filter=models.Q(
                           worksheet__items__deleted_at__isnull=True)))
                   .order_by('source', 'order', 'pk'))
    return render(request, 'worksheets/collection_list.html', {
        'collections': collections,
    })


def _visible_collection(request, pk):
    collection = get_object_or_404(
        Collection.objects.select_related('worksheet', 'source', 'parent'),
        pk=pk)
    if (not collection.is_published
            and collection.worksheet.owner_id != request.user.pk
            and not request.user.is_superuser):
        raise PermissionDenied
    return collection


@teacher_required
def collection_detail(request, pk):
    """Страница подборки: ответы в рамке после задачи, скрыты тумблером."""
    collection = _visible_collection(request, pk)
    items = list(collection.worksheet.ordered_items())
    rows = []
    number = 0
    for item in items:
        if item.task_id:
            number += 1
        rows.append({
            'item': item,
            'number': number if item.task_id else None,
            'subitems': item.selected_subitems() if item.task_id else [],
        })
    from .block_presentation import decorate_block_rows
    decorate_block_rows(rows)
    return render(request, 'worksheets/collection_detail.html', {
        'collection': collection,
        'worksheet': collection.worksheet,
        'rows': rows,
        'can_use': bool(items),
        'can_edit': (collection.worksheet.owner_id == request.user.pk
                     or request.user.is_superuser),
    })


@teacher_required
@require_POST
def collection_use(request, pk):
    collection = _visible_collection(request, pk)
    if not collection.worksheet.items.filter(
            deleted_at__isnull=True).exists():
        messages.error(request, 'Организационная группа не содержит элементов.')
        return redirect('collection_detail', pk=collection.pk)
    worksheet = collection.worksheet.duplicate(owner=request.user)
    worksheet.title = collection.worksheet.title
    worksheet.save(update_fields=['title', 'updated_at'])
    messages.success(
        request, f'Подборка «{worksheet.title}» скопирована в мои листки.')
    return redirect('worksheet_detail', pk=worksheet.pk)


@teacher_required
def collection_edit(request, pk):
    collection = _visible_collection(request, pk)
    if (collection.worksheet.owner_id != request.user.pk
            and not request.user.is_superuser):
        raise PermissionDenied
    return redirect('worksheet_detail', pk=collection.worksheet_id)


@teacher_required
@require_POST
def worksheet_rename(request, pk):
    """Переименование листка прямо на странице конструктора."""
    worksheet = _own_worksheet(request, pk)
    title = request.POST.get('title', '').strip()
    if not title:
        return _builder_response(
            request, pk, ok=False, message='Название не может быть пустым.')
    worksheet.title = title
    worksheet.save(update_fields=['title', 'updated_at'])
    return _builder_response(request, pk)


@teacher_required
@require_POST
def worksheet_copy(request, pk):
    """Дубликат листка; поля из диалога дублирования переопределяют копию."""
    worksheet = _own_worksheet(request, pk)
    copy = worksheet.duplicate()
    title = request.POST.get('title', '').strip()
    if title:
        copy.title = title
    if 'grade_label' in request.POST:
        copy.grade_label = request.POST['grade_label'].strip()[:100]
    if 'pdf_basename' in request.POST:
        copy.pdf_basename = request.POST['pdf_basename'].strip()[:80]
    if 'grade' in request.POST:
        grade, ok = parse_grade_choice(request.POST['grade'])
        if ok:
            copy.grade = grade
    copy.save()
    copy.topics.set(worksheet.topics.all())
    copy.grade_bands.set(worksheet.grade_bands.all())
    messages.success(
        request, f'Создана копия «{copy.title}» — можно редактировать.')
    return redirect('worksheet_detail', pk=copy.pk)


@teacher_required
@require_POST
def worksheet_delete(request, pk):
    """Удаление листка из списка (вместе с назначениями и ссылками)."""
    worksheet = _own_worksheet(request, pk)
    title = worksheet.title
    worksheet.delete()
    messages.success(request, f'Листок «{title}» удалён.')
    return redirect('worksheet_list')


@teacher_required
@require_POST
def worksheet_bulk_delete(request):
    """Старый маршрут bulk-delete/: удаление по ids, без поля delete."""
    ids = request.POST.getlist('ids')
    worksheets = Worksheet.visible_to(request.user).filter(pk__in=ids)
    count = worksheets.count()
    worksheets.delete()
    messages.success(request, f'Удалено листков: {count}.')
    return redirect('worksheet_list')


@teacher_required
@require_POST
def worksheet_bulk_update(request):
    """Массовые действия над выбранными листками: назначение или удаление."""
    if request.POST.get('delete'):
        return worksheet_bulk_delete(request)
    ids = request.POST.getlist('ids')
    worksheets = Worksheet.visible_to(request.user).filter(pk__in=ids)
    fields = {}
    grade, grade_ok = parse_grade_choice(request.POST.get('grade', ''))
    if request.POST.get('grade', '').strip() and not grade_ok:
        messages.error(request, 'Недопустимый класс.')
        return redirect('worksheet_list')
    if grade is not None:
        fields['grade'] = grade
    topic = None
    topic_id = request.POST.get('topic_id', '').strip()
    if topic_id:
        topic = Topic.objects.filter(pk=topic_id).first()
    if not fields and topic is None:
        messages.error(request, 'Выберите, что назначить: класс или тему.')
        return redirect('worksheet_list')
    now = timezone.now()
    if fields:
        fields['updated_at'] = now
        worksheets.update(**fields)
        if 'grade' in fields:
            code = GRADE_LEVEL_TO_CODE.get(fields['grade'])
            for worksheet in worksheets:
                set_grade_bands(
                    worksheet, [code] if code else [], sync_legacy=False)
    if topic is not None:
        for worksheet in worksheets:
            worksheet.topics.add(topic)
        if 'updated_at' not in fields:
            worksheets.update(updated_at=now)
    messages.success(request, f'Обновлено листков: {worksheets.count()}.')
    return redirect('worksheet_list')


@teacher_required
@require_POST
def worksheet_quick_update(request, pk):
    """Горячее редактирование из списка листков: класс и темы.

    Меняет только присланные поля. Темы приходят из popup-диалога:
    маркер topics_submitted отличает «снять все темы» от «тем не присылали».
    """
    worksheet = _own_worksheet(request, pk)
    if 'grade' in request.POST:
        value, ok = parse_grade_choice(request.POST['grade'])
        if request.POST['grade'].strip() and not ok:
            return _builder_response(
                request, pk, ok=False, message='Недопустимый класс')
        worksheet.grade = value
        worksheet.save(update_fields=['grade', 'updated_at'])
        code = GRADE_LEVEL_TO_CODE.get(worksheet.grade)
        set_grade_bands(worksheet, [code] if code else [], sync_legacy=False)
    if 'grade_label' in request.POST:
        worksheet.grade_label = request.POST['grade_label'].strip()[:100]
        worksheet.save(update_fields=['grade_label', 'updated_at'])
    if (request.POST.get('topics_submitted') or 'topics' in request.POST
            or request.POST.get('grades_submitted')
            or 'grade_bands' in request.POST):
        apply_worksheet_taxonomy(worksheet, request.POST)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    messages.success(request, f'Листок «{worksheet.title}» обновлён.')
    return redirect('worksheet_list')


def append_task(worksheet, task):
    """Добавляет отдельную задачу либо все вопросы общего блока."""
    from problems.task_blocks import block_members
    if not task.block_id:
        return _append_single_task(worksheet, task)
    try:
        members = block_members(task)
    except ValueError as exc:
        return 'exists', str(exc)
    with transaction.atomic():
        Worksheet.objects.select_for_update().get(pk=worksheet.pk)
        ids = [t.pk for t in members]
        active = worksheet.items.filter(task_id__in=ids, deleted_at=None)
        if active.count() == len(ids):
            return 'exists', 'Блок уже есть в листке.'
        last = worksheet.items.aggregate(m=models.Max('order'))['m'] or 0
        existing = {i.task_id: i for i in worksheet.items.filter(task_id__in=ids)}
        for pos, member in enumerate(members, 1):
            item = existing.get(member.pk)
            if item is None:
                item = WorksheetItem(worksheet=worksheet, task=member)
            item.deleted_at = None
            item.order = last + pos * 10
            item.save()
    return 'added', f'Блок из {len(members)} задач добавлен в листок.'


def _append_single_task(worksheet, task):
    """Добавляет задачу в конец листка; возвращает (исход, сообщение).

    Исход: 'exists' — уже есть, 'restored' — возвращён мягко удалённый
    элемент, 'added' — создан новый. Повторное добавление задачи из корзины —
    это восстановление, а не второй элемент: иначе «Отменить» дало бы дубль.
    Общая точка для конструктора, создания задачи и корзины.
    """
    with transaction.atomic():
        Worksheet.objects.select_for_update().get(pk=worksheet.pk)
        if worksheet.items.filter(task=task, deleted_at__isnull=True).exists():
            return 'exists', f'Задача #{task.pk} уже есть в листке.'
        trashed = worksheet.items.filter(
            task=task, deleted_at__isnull=False).first()
        if trashed:
            worksheet.items.filter(deleted_at__isnull=False).exclude(
                pk=trashed.pk).delete()
            trashed.deleted_at = None
            trashed.save(update_fields=['deleted_at'])
            return 'restored', f'Задача #{task.pk} возвращена в листок.'
        last = worksheet.items.aggregate(m=models.Max('order'))['m'] or 0
        WorksheetItem.objects.create(
            worksheet=worksheet, task=task, order=last + 10)
    return 'added', f'Задача #{task.pk} добавлена в «{worksheet.title}».'


def soft_remove_item(worksheet, item):
    """Мягкое удаление элемента с одноуровневым «Отменить»: прежний
    «мусор» листка вычищается насовсем."""
    with transaction.atomic():
        Worksheet.objects.select_for_update().get(pk=worksheet.pk)
        worksheet.items.filter(deleted_at__isnull=False).delete()
        if item.task_id and item.task.block_id:
            worksheet.items.filter(task__block_id=item.task.block_id).update(
                deleted_at=timezone.now())
        else:
            item.deleted_at = timezone.now()
            item.save(update_fields=['deleted_at'])


def add_task_to_worksheet(request, worksheet_id, task):
    """Добавляет задачу в конец листка (используется и из создания задачи)."""
    worksheet = get_object_or_404(
        Worksheet.visible_to(request.user), pk=worksheet_id)
    outcome, message = append_task(worksheet, task)
    (messages.info if outcome == 'exists' else messages.success)(
        request, message)
    return redirect('worksheet_detail', pk=worksheet.pk)


@teacher_required
@require_POST
def worksheet_add_task(request, pk):
    task = get_object_or_404(Task, pk=request.POST.get('task_id'))
    return add_task_to_worksheet(request, pk, task)


@teacher_required
@require_POST
def worksheet_remove_item(request, pk, item_id):
    """Мягкое удаление: элемент прячется, плашка «Отменить» может вернуть.

    Отмена одноуровневая — прежний «мусор» листка при новом удалении
    вычищается насовсем.
    """
    worksheet = _own_worksheet(request, pk)
    item = get_object_or_404(
        WorksheetItem, pk=item_id, worksheet=worksheet,
        deleted_at__isnull=True)
    soft_remove_item(worksheet, item)
    if item.task_id:
        msg = 'Задача удалена из листка.'
    elif item.is_rubric:
        msg = 'Рубрика удалена из листка.'
    else:
        msg = 'Текст удалён из листка.'
    return _builder_response(request, pk, message=msg)


@teacher_required
@require_POST
def worksheet_restore_item(request, pk):
    """Возвращает последний мягко удалённый элемент («Отменить»)."""
    worksheet = _own_worksheet(request, pk)
    with transaction.atomic():
        Worksheet.objects.select_for_update().get(pk=worksheet.pk)
        restored = 0
        kind = None
        for item in worksheet.items.filter(deleted_at__isnull=False):
            if (item.task_id and worksheet.items.filter(
                    task_id=item.task_id, deleted_at__isnull=True).exists()):
                item.delete()
                continue
            item.deleted_at = None
            item.save(update_fields=['deleted_at'])
            restored += 1
            if item.task_id:
                kind = 'task'
            elif item.is_rubric:
                kind = 'rubric'
            else:
                kind = 'text'
    if restored:
        msg = {
            'task': 'Задача возвращена в листок.',
            'rubric': 'Рубрика возвращена в листок.',
            'text': 'Текст возвращён в листок.',
        }.get(kind, 'Элемент возвращён в листок.')
        return _builder_response(request, pk, message=msg)
    return redirect('worksheet_detail', pk=pk)


@teacher_required
@require_POST
def worksheet_move_item(request, pk, item_id, direction):
    worksheet = _own_worksheet(request, pk)
    items = list(worksheet.ordered_items())
    from .blocks import item_units
    units = item_units(items)
    unit_idx = next((i for i, unit in enumerate(units)
                     if any(it.pk == item_id for it in unit)), None)
    if unit_idx is None:
        raise Http404
    other_unit = unit_idx - 1 if direction == 'up' else unit_idx + 1
    if 0 <= other_unit < len(units):
        units[unit_idx], units[other_unit] = units[other_unit], units[unit_idx]
        ordered = [it for unit in units for it in unit]
        for pos, it in enumerate(ordered, 1):
            it.order = pos * 10
        WorksheetItem.objects.bulk_update(ordered, ['order'])
    return redirect('worksheet_detail', pk=pk)


@teacher_required
@require_POST
def worksheet_set_rubric(request, pk, item_id):
    """Правка элемента-рубрики (название и пояснение)."""
    worksheet = _own_worksheet(request, pk)
    item = get_object_or_404(
        WorksheetItem, pk=item_id, worksheet=worksheet, task__isnull=True)
    rubric = request.POST.get('rubric', '').strip()
    if not rubric:
        return _builder_response(
            request, pk, ok=False,
            message='Название рубрики пустое — не сохранено '
                    '(удалите рубрику кнопкой ×).')
    item.rubric = rubric
    item.rubric_note = request.POST.get('rubric_note', '').strip()
    item.save()
    return _builder_response(request, pk)


@teacher_required
@require_POST
def worksheet_reorder(request, pk):
    """Порядок элементов после перетаскивания: POST order=id1,id2,..."""
    worksheet = _own_worksheet(request, pk)
    raw = request.POST.get('order', '')
    id_list = [int(x) for x in raw.split(',') if x.strip().isdigit()]
    items = {i.pk: i for i in worksheet.ordered_items()}
    from .blocks import valid_block_order
    if any(i.task_id and i.task.block_id for i in items.values()):
        if (len(id_list) != len(items) or set(id_list) != set(items)
                or not valid_block_order([items[i] for i in id_list])):
            return JsonResponse({'ok': False, 'message':
                'Вопросы общего блока перемещаются вместе в исходном порядке.'}, status=400)
    changed = []
    for pos, item_id in enumerate(id_list):
        item = items.get(item_id)
        if item is not None:
            item.order = (pos + 1) * 10
            changed.append(item)
    WorksheetItem.objects.bulk_update(changed, ['order'])
    return JsonResponse({'ok': True, 'updated': len(changed)})


@teacher_required
@require_POST
def worksheet_add_element(request, pk):
    """Добавляет элемент «текст» или «рубрика» в конец листка."""
    worksheet = _own_worksheet(request, pk)
    kind = request.POST.get('kind', 'text')
    last = worksheet.items.aggregate(m=models.Max('order'))['m'] or 0
    if kind == 'rubric':
        rubric = request.POST.get('rubric', '').strip()
        if not rubric:
            messages.error(request, 'Название рубрики пустое — не добавлена.')
            return redirect('worksheet_detail', pk=pk)
        WorksheetItem.objects.create(
            worksheet=worksheet, rubric=rubric,
            rubric_note=request.POST.get('rubric_note', '').strip(),
            order=last + 10)
        messages.success(
            request, 'Рубрика добавлена в конец — перетащите её на место.')
    else:
        text = request.POST.get('text_latex', '').strip()
        if not text:
            messages.error(request, 'Текст пустой — элемент не добавлен.')
            return redirect('worksheet_detail', pk=pk)
        WorksheetItem.objects.create(
            worksheet=worksheet, text_latex=text, order=last + 10)
        messages.success(request, 'Текст добавлен в листок.')
    return redirect('worksheet_detail', pk=pk)


@teacher_required
@require_POST
def worksheet_edit_text(request, pk, item_id):
    worksheet = _own_worksheet(request, pk)
    item = get_object_or_404(
        WorksheetItem, pk=item_id, worksheet=worksheet,
        task__isnull=True, rubric='')
    text = request.POST.get('text_latex', '').strip()
    if not text:
        return _builder_response(
            request, pk, ok=False,
            message='Текст пустой — не сохранено (удалите элемент кнопкой ×).')
    item.text_latex = text
    updated = ['text_latex']
    style = request.POST.get('text_style', '')
    if style in dict(WorksheetItem.TEXT_STYLE_CHOICES):
        item.text_style = style
        updated.append('text_style')
    item.save(update_fields=updated)
    return _builder_response(request, pk, message='Текст сохранён.')


@teacher_required
@require_POST
def worksheet_item_visibility(request, pk, item_id):
    """Скрытие задачи по публичным ссылкам и назначениям учеников."""
    worksheet = _own_worksheet(request, pk)
    item = get_object_or_404(
        WorksheetItem, pk=item_id, worksheet=worksheet, task__isnull=False)
    members = (list(worksheet.items.filter(task__block_id=item.task.block_id))
               if item.task.block_id else [item])
    hide_links = {int(x) for x in request.POST.getlist('hide_links')
                  if x.isdigit()}
    for link in worksheet.share_links.all():
        if link.pk in hide_links:
            link.hidden_items.add(*members)
        else:
            link.hidden_items.remove(*members)
    hide_assignments = {int(x) for x in request.POST.getlist(
        'hide_assignments') if x.isdigit()}
    for assignment in worksheet.assignments.all():
        if assignment.pk in hide_assignments:
            assignment.hidden_items.add(*members)
        else:
            assignment.hidden_items.remove(*members)
    return _builder_response(request, pk, message='Видимость сохранена.')


@teacher_required
@require_POST
def worksheet_item_settings(request, pk, item_id):
    """Звёзды/колонки и выбор подпунктов для задачи в листке."""
    worksheet = _own_worksheet(request, pk)
    item = get_object_or_404(
        WorksheetItem, pk=item_id, worksheet=worksheet, task__isnull=False)

    def parse_override(name):
        raw = request.POST.get(name, '').strip()
        if raw == '':
            return None
        try:
            return max(0, int(raw))
        except ValueError:
            return None

    item.stars_override = parse_override('stars')
    item.columns_override = parse_override('columns')

    all_ids = list(item.task.subitems.values_list('pk', flat=True))
    if all_ids:
        checked = {int(x) for x in request.POST.getlist('subitems')
                   if x.isdigit()}
        checked &= set(all_ids)
        if checked == set(all_ids):
            item.all_subitems = True
            item.subitems.clear()
        else:
            item.all_subitems = False
            item.subitems.set(checked)
    item.save()
    return _builder_response(
        request, pk, message='Настройки задачи в листке сохранены.')


def _worksheet_pdf_response(worksheet, variant, exclude_ids=None):
    """PDF листка, в том числе со скрытыми элементами — через кэш WorksheetPdf."""
    pdf = get_worksheet_pdf(worksheet, variant, exclude_ids=exclude_ids)
    return FileResponse(
        pdf.file.open('rb'), content_type='application/pdf',
        filename=worksheet.pdf_filename(variant))


def worksheet_pdf(request, pk):
    """PDF листка. Учитель-владелец — любой вариант, назначенный ученик — без ответов."""
    if not request.user.is_authenticated:
        raise PermissionDenied
    worksheet = get_object_or_404(Worksheet, pk=pk)
    variant = request.GET.get('variant', WorksheetPdf.VARIANT_STUDENT)
    if variant not in dict(WorksheetPdf.VARIANT_CHOICES):
        raise Http404

    role = get_role(request.user)
    is_owner = (worksheet.owner_id == request.user.pk
                or request.user.is_superuser)
    is_assigned_student = (
        role == Profile.ROLE_STUDENT
        and worksheet.assignments.filter(student=request.user).exists())
    if not (is_owner or (is_assigned_student
                         and variant == WorksheetPdf.VARIANT_STUDENT)):
        raise PermissionDenied

    # Ученик получает PDF без задач, скрытых в его назначении
    exclude_ids = None
    if not is_owner:
        assignment = worksheet.assignments.filter(
            student=request.user).first()
        exclude_ids = set(
            assignment.hidden_items.values_list('pk', flat=True))

    try:
        return _worksheet_pdf_response(worksheet, variant,
                                       exclude_ids=exclude_ids)
    except LatexCompileError as exc:
        if not is_owner:
            # Ученику — без лога и .tex: он ничего с ними не сделает,
            # а «404» выглядел бы как пропавший листок
            return render(request, 'worksheets/latex_error.html', {
                'worksheet': worksheet,
                'for_student': True,
            }, status=502)
        return render(request, 'worksheets/latex_error.html', {
            'worksheet': worksheet,
            'error': exc,
            'tex': worksheet_to_tex(worksheet, variant),
        }, status=502)


# Профили font= пакета egor; в редакторе показываются только включённые
# в settings.PDF_EDITOR_FONTS (school/palatino требуют подготовки сервера)
PDF_EDITOR_FONT_LABELS = (
    ('cm', 'Computer Modern'),
    ('school', 'Schoolbook'),
    ('palatino', 'Palatino'),
)


@teacher_required
def worksheet_pdf_editor(request, pk):
    """Split-редактор PDF: слева исходный tex (можно править), справа PDF."""
    worksheet = _own_worksheet(request, pk)
    variant = request.GET.get('variant', WorksheetPdf.VARIANT_STUDENT)
    if variant not in dict(WorksheetPdf.VARIANT_CHOICES):
        raise Http404
    font_choices = [(v, label) for v, label in PDF_EDITOR_FONT_LABELS
                    if v in settings.PDF_EDITOR_FONTS]
    return render(request, 'worksheets/pdf_editor.html', {
        'worksheet': worksheet,
        'variant': variant,
        'variant_label': dict(WorksheetPdf.VARIANT_CHOICES)[variant],
        'variant_choices': WorksheetPdf.VARIANT_CHOICES,
        'tex': worksheet_to_tex(worksheet, variant),
        'pdf_filename': worksheet.pdf_filename(variant),
        'font_choices': font_choices,
    })


# Ограничения черновой компиляции: разумный максимум исходника и одна
# сборка на пользователя одновременно (каждая занимает воркер и квоту
# LaTeX API на десятки секунд)
PDF_EDITOR_TEX_LIMIT = 200_000
PDF_EDITOR_LOCK_TIMEOUT = timedelta(seconds=180)


def _acquire_compile_lock(user):
    """Берёт межпроцессный lock сборки PDF; False — сборка уже идёт.

    Lock в БД (см. PdfCompileLock): работает и при нескольких
    WSGI-процессах, где LocMemCache бесполезен.
    """
    PdfCompileLock.objects.filter(
        user=user,
        created_at__lt=timezone.now() - PDF_EDITOR_LOCK_TIMEOUT).delete()
    try:
        with transaction.atomic():
            PdfCompileLock.objects.create(user=user)
        return True
    except IntegrityError:
        return False


def _editor_compile(request, worksheet, tex, doc_id, filename, collect):
    """Черновая сборка: проверка tex → lock → assets → API."""
    if not tex.strip():
        return JsonResponse(
            {'ok': False, 'message': 'Пустой документ', 'log': ''},
            status=400)
    if len(tex) > PDF_EDITOR_TEX_LIMIT:
        return JsonResponse(
            {'ok': False,
             'message': f'Документ слишком большой '
                        f'(лимит {PDF_EDITOR_TEX_LIMIT} символов)',
             'log': ''},
            status=400)
    if not _acquire_compile_lock(request.user):
        return JsonResponse(
            {'ok': False,
             'message': 'Предыдущая сборка ещё идёт — дождитесь её '
                        'завершения', 'log': ''},
            status=429)
    try:
        try:
            assets = collect()
        except LatexCompileError as exc:
            return JsonResponse(
                {'ok': False, 'message': str(exc), 'log': exc.log}, status=400)
        pdf_bytes = compile_latex(tex, doc_id=doc_id, assets=assets)
    except LatexCompileError as exc:
        return JsonResponse(
            {'ok': False, 'message': str(exc), 'log': exc.log}, status=502)
    finally:
        PdfCompileLock.objects.filter(user=request.user).delete()
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


@teacher_required
@require_POST
def worksheet_pdf_compile(request, pk):
    """Компиляция tex из редактора (в т.ч. с ручными правками учителя).

    Возвращает PDF-байты либо JSON с логом ошибки компиляции. Кэш PDF
    листка не трогает — это «черновая» сборка именно присланного кода.
    """
    worksheet = _own_worksheet(request, pk)
    return _editor_compile(
        request, worksheet, request.POST.get('tex', ''),
        doc_id=f'ws{worksheet.pk}-editor',
        filename=worksheet.pdf_filename(),
        collect=lambda: collect_assets(worksheet))


@teacher_required
def worksheet_beamer_editor(request, pk):
    """Split-редактор презентации: слева Beamer-tex, справа предпросмотр."""
    worksheet = _own_worksheet(request, pk)
    return render(request, 'worksheets/beamer_editor.html', {
        'worksheet': worksheet,
        'tex': worksheet_to_beamer(worksheet),
        'pdf_filename': worksheet.beamer_filename(),
    })


@teacher_required
@require_POST
def worksheet_beamer_compile(request, pk):
    """Черновая сборка презентации; кэш WorksheetPdf не трогает."""
    worksheet = _own_worksheet(request, pk)
    tex = request.POST.get('tex', '')
    return _editor_compile(
        request, worksheet, tex,
        doc_id=f'ws{worksheet.pk}-beamer',
        filename=worksheet.beamer_filename(),
        collect=lambda: collect_beamer_assets(worksheet, tex=tex))


@teacher_required
def worksheet_tex(request, pk):
    """Показ .tex-исходника (для отладки ошибок компиляции)."""
    worksheet = _own_worksheet(request, pk)
    variant = request.GET.get('variant', WorksheetPdf.VARIANT_STUDENT)
    if variant not in dict(WorksheetPdf.VARIANT_CHOICES):
        raise Http404
    tex = worksheet_to_tex(worksheet, variant)
    return render(request, 'worksheets/tex_source.html', {
        'worksheet': worksheet, 'tex': tex, 'variant': variant,
    })


@teacher_required
@require_POST
def share_create(request, pk):
    worksheet = _own_worksheet(request, pk)
    ShareLink.objects.create(worksheet=worksheet)
    messages.success(request, 'Публичная ссылка создана.')
    return redirect('worksheet_detail', pk=pk)


@teacher_required
@require_POST
def share_toggle(request, pk, link_id):
    worksheet = _own_worksheet(request, pk)
    link = get_object_or_404(ShareLink, pk=link_id, worksheet=worksheet)
    link.is_active = not link.is_active
    link.save()
    return redirect('worksheet_detail', pk=pk)


# --- Публичные страницы (без входа) ---

def _shared_link(token):
    link = (ShareLink.objects.filter(token=token, is_active=True)
            .select_related('worksheet').first())
    if link is None:
        raise Http404
    return link


def public_worksheet(request, token):
    link = _shared_link(token)
    worksheet = link.worksheet
    hidden = set(link.hidden_items.values_list('pk', flat=True))
    rows = []
    number = 0
    for item in worksheet.ordered_items():
        if item.pk in hidden:
            continue
        if item.task_id:
            number += 1
        rows.append({
            'item': item,
            'number': number if item.task_id else None,
            'subitems': item.selected_subitems(),
        })
    from .block_presentation import decorate_block_rows
    decorate_block_rows(rows)
    # Подзаголовок — только непустые части, без «висячих» разделителей
    subtitle_line = ' · '.join(
        part.strip() for part in (worksheet.grade_label, worksheet.subtitle,
                                  worksheet.display_author)
        if part and part.strip())
    return render(request, 'worksheets/public.html', {
        'worksheet': worksheet,
        'rows': rows,
        'token': token,
        'subtitle_line': subtitle_line,
        # Публичная страница — только просмотр: без контекстной панели
        'minimal_page': True,
    })


def public_worksheet_pdf(request, token):
    link = _shared_link(token)
    hidden = set(link.hidden_items.values_list('pk', flat=True))
    try:
        return _worksheet_pdf_response(
            link.worksheet, WorksheetPdf.VARIANT_STUDENT,
            exclude_ids=hidden)
    except LatexCompileError:
        raise Http404

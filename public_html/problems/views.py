import hashlib
import json
import re

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Min, Q
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import teacher_required
from assignments.checks import HELP as MASK_HELP

from .forms import (TaskForm, TaskImageFormSet, TaskSourceFormSet,
                    TaskSubitemFormSet, TextbookBundleUploadForm,
                    TextbookDraftReviewForm, TextbookImageArchiveForm)
from .models import (Source, Tag, Task, TaskImage, TaskSource, TaskSubitem,
                     TextbookImportAsset, TextbookImportBatch,
                     TextbookTaskDraft, Topic, topic_tree)
from .rubricator import (GRADE_LEVEL_TO_CODE, apply_task_taxonomy,
                         dumps_state, filter_by_taxonomy,
                         filter_state_from_params, parse_grade_choice,
                         set_grade_bands, set_task_topics,
                         taxonomy_page_context, taxonomy_state_from_post,
                         task_taxonomy_state)


def filter_tasks(params):
    """Каталог задач по GET-параметрам: q, topic, grade, tag.

    «Локальные» копии задач (варианты для конкретного листка)
    в каталоге не показываются.
    """
    tasks = (Task.objects.filter(variant_of__isnull=True)
             .prefetch_related('topics', 'topic_links', 'grade_bands',
                               'facet_values', 'exam_items', 'tags',
                               'source_refs__source', 'subitems', 'images')
             .select_related('created_by').order_by('-created_at', '-pk'))
    q = params.get('q', '').strip()
    if re.fullmatch(r'#?\d+', q):
        # «#123» или «123» — задача по id
        tasks = tasks.filter(pk=int(q.lstrip('#')))
    elif q:
        tasks = tasks.filter(
            Q(text_plain__icontains=q) | Q(text_latex__icontains=q))
    tasks = filter_by_taxonomy(tasks, params, topics_lookups=('topics',))
    tag = params.get('tag')
    if tag:
        tasks = tasks.filter(tags__name=tag)
    # Источник (задачник) — ссылки из панели каталога
    source = (params.get('source') or '').strip()
    if source.isdigit():
        tasks = tasks.filter(source_refs__source_id=int(source)).distinct()
    return tasks


def _rubricator_blocks(topics_flat, active_topic=None):
    """Разделы рубрикатора (корневые темы) с числом задач в поддереве.

    Поддеревья берутся из плоского списка topic_tree() (один запрос),
    счётчик — по одному запросу на раздел; разделов несколько. У раздела,
    в котором лежит выбранная тема, раскрываются подтемы первого уровня
    (тоже со счётчиками), чтобы панель вела дальше по дереву.
    """
    blocks = []
    subtree_ids = []
    children = []
    for topic in topics_flat:
        if topic.depth == 0:
            subtree_ids = [topic.pk]
            children = []
            topic.subtree_ids = subtree_ids
            topic.children_topics = children
            topic.children_visible = []
            blocks.append(topic)
        else:
            subtree_ids.append(topic.pk)
            if topic.depth == 1:
                topic.subtree_ids = [topic.pk]
                children.append(topic)
            elif children:
                children[-1].subtree_ids.append(topic.pk)
    # Та же база, что у каталога (filter_tasks): локальные копии задач не считаем.
    catalog = Task.objects.filter(variant_of__isnull=True)
    for block in blocks:
        block.task_total = catalog.filter(topics__in=block.subtree_ids).distinct().count()
        block.is_current = active_topic == block.pk
        if active_topic in block.subtree_ids:
            for child in block.children_topics:
                child.task_total = catalog.filter(topics__in=child.subtree_ids).distinct().count()
                child.is_current = active_topic in child.subtree_ids
            block.children_visible = block.children_topics
    return blocks


def _catalog_facets(params):
    """Классы и источники для панели каталога — с числом задач и текущим выбором."""
    catalog = Task.objects.filter(variant_of__isnull=True)
    # Условие то же, что у фильтра ?grade=N (filter_by_taxonomy): полоса
    # классов ИЛИ старое поле grade_level — иначе счётчик расходится с выдачей.
    levels_of = {level: [10, 11] if level == 10 else [level]
                 for level in GRADE_LEVEL_TO_CODE if level != 11}
    counts = catalog.aggregate(**{
        f'g{level}': Count('id', distinct=True, filter=(
            Q(grade_bands__code=GRADE_LEVEL_TO_CODE[level]) | Q(grade_level__in=levels)))
        for level, levels in levels_of.items()})
    labels = dict(Task.GRADE_CHOICES)
    current_grade, _ = parse_grade_choice(params.get('grade'))
    grades = []
    for level in sorted(levels_of):
        count = counts[f'g{level}']
        if count:
            grades.append({'value': level, 'label': labels.get(level, str(level)),
                           'count': count, 'is_current': current_grade == level})
    current_source = (params.get('source') or '').strip()
    sources = [
        {'pk': row['source_id'], 'title': row['source__title'], 'count': row['n'],
         'is_current': current_source == str(row['source_id'])}
        for row in (TaskSource.objects.filter(task__variant_of__isnull=True)
                    .values('source_id', 'source__title')
                    .annotate(n=Count('task_id', distinct=True))
                    .order_by('-n', 'source__title')[:12])]
    return grades, sources


@teacher_required
def task_list(request):
    tasks = filter_tasks(request.GET)
    paginator = Paginator(tasks, 25)
    page = paginator.get_page(request.GET.get('page'))
    topics_flat = topic_tree()
    active_topic = request.GET.get('topic', '')
    active_topic = int(active_topic) if active_topic.isdigit() else None
    grade_facets, source_facets = _catalog_facets(request.GET)
    ctx = taxonomy_page_context(filter_state_from_params(request.GET))
    ctx.update({
        'page': page,
        'topics': _rubricator_blocks(topics_flat, active_topic),
        'grade_facets': grade_facets,
        'source_facets': source_facets,
        'topics_flat': topics_flat,
        'sources': Source.objects.all(),
        'params': request.GET,
        'grade_choices': Task.GRADE_CHOICES,
        'mask_help': MASK_HELP,
    })
    from assignments.checks import KINDS, PRESETS
    from assignments.task_usage import attach_usage, audience_context
    ctx['mask_kinds'] = {**KINDS, **{k: k for k in PRESETS}}
    for task in page:
        task.taxonomy_json = dumps_state(task_taxonomy_state(task))
    ctx.update(audience_context(request, attach_usage(request, page.object_list)))
    return render(request, 'problems/task_list.html', ctx)


def _delete_unused_task(task):
    """Общее правило удаления из карточки и массовой панели."""
    from django.db.models.deletion import ProtectedError
    try:
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task.pk)
            if (task.worksheet_items.filter(deleted_at__isnull=True).exists()
                    or task.submissions.exists()):
                return False
            task.delete()
        return True
    except ProtectedError:
        return False


@teacher_required
@require_POST
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if _delete_unused_task(task):
        messages.success(request, f'Задача #{pk} удалена.')
        return redirect('task_list')
    messages.error(request, 'Задача не удалена: она используется в листке или содержит ответы учеников.')
    return redirect('task_detail', pk=pk)


@teacher_required
@require_POST
def task_bulk_update(request):
    """Массовые действия над выбранными задачами: назначение или удаление."""
    ids = request.POST.getlist('ids')
    tasks = Task.objects.filter(variant_of__isnull=True, pk__in=ids)
    if request.POST.get('delete'):
        deleted = 0
        blocked = 0
        for task in list(tasks):
            if _delete_unused_task(task):
                deleted += 1
            else:
                blocked += 1
        if deleted:
            messages.success(request, f'Удалено задач: {deleted}.')
        if blocked:
            messages.error(
                request,
                f'Не удалено (есть в листке или есть ответы учеников): '
                f'{blocked}.')
        if not deleted and not blocked:
            messages.error(request, 'Не выбрано ни одной задачи.')
        return redirect(_safe_next(request))
    fields = {}
    grade, grade_ok = parse_grade_choice(request.POST.get('grade_level', ''))
    if request.POST.get('grade_level', '').strip() and not grade_ok:
        messages.error(request, 'Недопустимый класс.')
        return redirect(_safe_next(request))
    if grade is not None:
        fields['grade_level'] = grade
    stars = request.POST.get('stars', '').strip()
    if stars:
        if stars not in {'0', '1', '2', '3'}:
            messages.error(request, 'Недопустимое число звёзд.')
            return redirect(_safe_next(request))
        fields['stars'] = int(stars)
    topic = None
    topic_id = request.POST.get('topic_id', '').strip()
    if topic_id:
        topic = Topic.objects.filter(pk=topic_id).first()
    if not fields and topic is None:
        messages.error(request, 'Выберите, что назначить: класс, тему '
                                'или звёзды.')
        return redirect(_safe_next(request))
    if fields:
        tasks.update(**fields)
        if 'grade_level' in fields:
            code = GRADE_LEVEL_TO_CODE.get(fields['grade_level'])
            for task in tasks:
                set_grade_bands(task, [code] if code else [], sync_legacy=False)
    if topic is not None:
        for task in tasks:
            if not task.topic_links.exists():
                set_task_topics(task, [topic.pk], topic.pk)
            else:
                task.topics.add(topic)
    messages.success(request, f'Обновлено задач: {tasks.count()}.')
    return redirect(_safe_next(request))


def _safe_next(request):
    """Возврат к списку задач с сохранением фильтров (next из формы)."""
    next_url = request.POST.get('next', '')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts=None):
        return next_url
    return reverse('task_list')


@teacher_required
def task_quick_update(request, pk):
    """Горячее редактирование задачи (список и карточка): присланные поля.

    Отвечает JSON для fetch-автосохранения. Источник — первый TaskSource
    задачи (создаётся/обновляется/удаляется). Темы и теги приходят целиком
    с маркерами topics_submitted / tags_submitted (пустой список = снять все).
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'message': 'Только POST'}, status=405)
    task = get_object_or_404(Task, pk=pk)
    # Сохраняем только присланные поля (update_fields): формы на карточке
    # автосохраняются параллельно, и полный task.save() затирал бы поля,
    # изменённые соседним запросом, устаревшими значениями
    updated = []
    sync_bands = False
    band_code = None
    if 'grade_level' in request.POST:
        value, ok = parse_grade_choice(request.POST['grade_level'])
        if request.POST['grade_level'].strip() and not ok:
            return JsonResponse(
                {'ok': False, 'message': 'Недопустимый класс'}, status=400)
        task.grade_level = value
        updated.append('grade_level')
        sync_bands = True
        band_code = GRADE_LEVEL_TO_CODE.get(value)
    if 'stars' in request.POST:
        value = request.POST['stars'].strip()
        if value not in {str(s) for s, _ in Task.STARS_CHOICES}:
            return JsonResponse(
                {'ok': False, 'message': 'Недопустимые звёзды'}, status=400)
        task.stars = int(value)
        updated.append('stars')
    if 'text_latex' in request.POST:
        value = request.POST['text_latex'].strip()
        if not value:
            return JsonResponse(
                {'ok': False, 'message': 'Условие не может быть пустым'},
                status=400)
        task.text_latex = value
        updated.append('text_latex')
    tag_names = None
    if request.POST.get('tags_submitted'):
        tag_names = [n.strip()
                     for n in request.POST.get('tags', '').split(',')
                     if n.strip()]
        max_len = Tag._meta.get_field('name').max_length
        too_long = [n for n in tag_names if len(n) > max_len]
        if too_long:
            return JsonResponse(
                {'ok': False,
                 'message': f'Тег длиннее {max_len} символов: '
                            f'{too_long[0][:40]}…'},
                status=400)
    if 'answer_latex' in request.POST:
        task.answer_latex = request.POST['answer_latex'].strip()
        updated.append('answer_latex')
    if 'solution_latex' in request.POST:
        task.solution_latex = request.POST['solution_latex'].strip()
        updated.append('solution_latex')
    if updated:
        task.save(update_fields=updated)
    if sync_bands:
        set_grade_bands(
            task, [band_code] if band_code else [], sync_legacy=False)
    if (request.POST.get('topics_submitted') or 'topics' in request.POST
            or 'primary_topic' in request.POST
            or request.POST.get('grades_submitted')
            or 'grade_bands' in request.POST
            or request.POST.get('facets_submitted')
            or request.POST.get('exams_submitted')
            or 'difficulty' in request.POST):
        apply_task_taxonomy(task, request.POST)
    if tag_names is not None:
        tags = [Tag.objects.get_or_create(name=name)[0] for name in tag_names]
        # Тег с запятой в имени через это поле не выразить — не теряем его
        tags += [t for t in task.tags.all() if ',' in t.name]
        task.tags.set(tags)
    if 'source' in request.POST:
        ref = task.source_refs.order_by('pk').first()
        source_id = request.POST['source'].strip()
        number = request.POST.get('number', '').strip()
        try:
            if not source_id:
                if ref is not None:
                    ref.delete()
            else:
                source = Source.objects.filter(pk=source_id).first()
                if source is None:
                    return JsonResponse(
                        {'ok': False, 'message': 'Источник не найден'},
                        status=400)
                if ref is None:
                    task.source_refs.create(source=source, number=number)
                else:
                    ref.source = source
                    ref.number = number
                    ref.save()
        except IntegrityError:
            return JsonResponse(
                {'ok': False, 'message': 'Такой источник у задачи уже есть'},
                status=400)
    # Обычная отправка формы (например, диалог тем) — назад на карточку
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        messages.success(request, 'Задача обновлена.')
        return redirect('task_detail', pk=task.pk)
    return JsonResponse({'ok': True})


@teacher_required
@require_POST
def task_subitem_update(request, pk, spk):
    """Горячее редактирование подпункта на карточке задачи (или удаление)."""
    subitem = get_object_or_404(TaskSubitem, pk=spk, task_id=pk)
    if request.POST.get('delete'):
        subitem.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': True})
        return redirect('task_detail', pk=pk)
    updated = []
    if 'text_latex' in request.POST:
        value = request.POST['text_latex'].strip()
        if not value:
            return JsonResponse(
                {'ok': False, 'message': 'Текст подпункта пуст'}, status=400)
        subitem.text_latex = value
        updated.append('text_latex')
    if 'answer_latex' in request.POST:
        subitem.answer_latex = request.POST['answer_latex'].strip()
        updated.append('answer_latex')
    if 'solution_latex' in request.POST:
        subitem.solution_latex = request.POST['solution_latex'].strip()
        updated.append('solution_latex')
    if updated:
        subitem.save(update_fields=updated)
    return JsonResponse({'ok': True})


@teacher_required
@require_POST
def task_subitem_add(request, pk):
    """Добавление подпункта прямо с карточки задачи."""
    task = get_object_or_404(Task, pk=pk)
    text = request.POST.get('text_latex', '').strip()
    if text:
        last = task.subitems.order_by('-order').first()
        TaskSubitem.objects.create(
            task=task, order=(last.order + 10) if last else 10,
            text_latex=text,
            answer_latex=request.POST.get('answer_latex', '').strip(),
            solution_latex=request.POST.get('solution_latex', '').strip())
        messages.success(request, 'Подпункт добавлен.')
    return redirect('task_detail', pk=pk)


@xframe_options_sameorigin
def task_image_file(request, pk):
    """Файл картинки задачи. Картинки не приватные: задачи видны ученикам
    в заданиях и любому — по публичной ссылке листка.

    sameorigin: PDF-иллюстрации встраиваются в страницы через <object>,
    а XFrameOptionsMiddleware по умолчанию ставит DENY.
    """
    image = get_object_or_404(TaskImage, pk=pk)
    if not image.image.storage.exists(image.image.name):
        raise Http404
    # filename задаёт корректный Content-Type (в т.ч. application/pdf)
    return FileResponse(image.image.open('rb'), filename=image.filename)


@teacher_required
def task_detail(request, pk):
    if request.method == 'POST':
        task = get_object_or_404(Task, pk=pk)
        return _task_form(request, task=task)
    from .editor import context
    task = get_object_or_404(Task.objects.prefetch_related(
        'subitems', 'images', 'topics', 'tags', 'source_refs__source'), pk=pk)
    return render(request, 'problems/task_detail.html', context(request, task))


@teacher_required
@require_POST
@transaction.atomic
def task_duplicate(request, pk):
    """Самостоятельная копия в базе или локальная — следующей строкой листка."""
    from .editor import worksheet_context
    from worksheets.models import Worksheet
    task = get_object_or_404(Task, pk=pk)
    item = worksheet_context(request, task)
    if item and item.deleted_at:
        raise Http404
    if item:
        # Сериализуем вставки в один листок, включая строки с равным order.
        Worksheet.objects.select_for_update().get(pk=item.worksheet_id)
    standalone = request.POST.get('standalone') == '1'
    copy, mapping = task.make_variant(request.user, with_mapping=True,
                                     standalone=standalone or item is None)
    if item and mapping.get('block_tasks'):
        rows = list(item.worksheet.ordered_items())
        originals = [row for row in rows if row.task_id in mapping['block_tasks']]
        clones = []
        opened_clone = None
        for original in originals:
            clone = item.worksheet.items.create(
                task_id=mapping['block_tasks'][original.task_id], order=original.order,
                stars_override=original.stars_override, columns_override=original.columns_override,
                all_subitems=original.all_subitems)
            clone.subitems.set([mapping['subitems'][pk]
                               for pk in original.subitems.values_list('pk', flat=True)])
            clones.append(clone)
            if original.pk == item.pk:
                opened_clone = clone
        insertion = max(rows.index(row) for row in originals) + 1
        ordered = rows[:insertion] + clones + rows[insertion:]
        for pos, row in enumerate(ordered, 1):
            row.order = pos * 10
            row.save(update_fields=['order'])
        if standalone:
            messages.success(
                request, 'Копия общего блока создана в базе и добавлена в листок.')
            return redirect(
                f'{reverse("task_detail", args=[copy.pk])}'
                f'?worksheet={item.worksheet_id}&item={opened_clone.pk}')
        messages.success(request, 'Локальная копия общего блока добавлена после исходного блока.')
        return redirect('worksheet_detail', pk=item.worksheet_id)
    if item:
        rows = list(item.worksheet.items.order_by('order', 'pk'))
        for position, row in enumerate(rows, 1):
            row.order = position * 10
            row.save(update_fields=['order'])
            if row.pk == item.pk:
                insertion = row.order + 5
        clone = item.worksheet.items.create(task=copy, order=insertion,
            stars_override=item.stars_override, columns_override=item.columns_override,
            all_subitems=item.all_subitems)
        clone.subitems.set([mapping['subitems'][pk]
                           for pk in item.subitems.values_list('pk', flat=True)])
        if standalone:
            messages.success(
                request, f'Копия #{copy.pk} создана в базе и добавлена в листок.')
            return redirect(
                f'{reverse("task_detail", args=[copy.pk])}'
                f'?worksheet={item.worksheet_id}&item={clone.pk}')
        messages.success(request, f'Копия #{copy.pk} добавлена после задачи #{task.pk}.')
        return redirect('worksheet_detail', pk=item.worksheet_id)
    messages.success(request, f'Создана независимая копия #{copy.pk} задачи #{task.pk}.')
    return redirect('task_detail', pk=copy.pk)


@teacher_required
def task_create(request):
    return _task_form(request, task=None)


@teacher_required
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if request.method == 'POST':
        return _task_form(request, task=task)
    url = reverse('task_detail', args=[pk])
    if request.GET:
        url += '?' + request.GET.urlencode()
    return redirect(url)


@teacher_required
@require_POST
def task_mask_preview(request):
    """Превью маски «как увидит ученик» и самопроверка для формы задачи.

    POST: ``mask`` — текст маски; поля ``preview_s1``… — пробные значения
    (если есть, возвращается результат проверки тем же кодом, что у ученика).
    """
    from django.template.loader import render_to_string

    from assignments.checks import (check_mask, collect_values, parse_mask,
                                    render_fragments)
    prefix = request.POST.get('prefix', 'preview')
    if not re.fullmatch(r'preview(?:_[0-9]+)?', prefix):
        return JsonResponse({'ok': False, 'message': 'Некорректный префикс'}, status=400)
    spec = parse_mask(request.POST.get('mask', ''), validate_references=True)
    payload = {'ok': spec.is_valid, 'errors': spec.errors,
               'slots': len(spec.slots)}
    if not spec.slots:
        payload['html'] = ''
        return JsonResponse(payload)
    from assignments.checks.formulas import FormulaUnavailable
    values = collect_values(request.POST, prefix, spec)
    checks = {}
    if values:
        try:
            overall, checks = check_mask(spec, values)
        except FormulaUnavailable:
            payload['unavailable'] = True
            payload['message'] = 'Проверка временно недоступна — попробуйте ещё раз через минуту'
        else:
            payload['overall'] = overall
        payload['checks'] = {f'{prefix}_{k}': v for k, v in checks.items()}
    payload['html'] = render_to_string('assignments/_mask.html', {
        'fragments': render_fragments(spec, prefix, values, checks, seed=prefix),
        'editable': True,
        'show_checks': True,
    })
    return JsonResponse(payload)


@teacher_required
@require_POST
def task_mask_draft(request):
    """Заготовка маски из текстового «Ответа» (только очевидные случаи)."""
    from assignments.checks import draft_mask
    mask = draft_mask(request.POST.get('answer', ''), request.POST.get('condition', ''),
                      exam_codes=request.POST.getlist('exam_codes'),
                      source_number=request.POST.get('source_number', ''),
                      subitem_label=request.POST.get('subitem_label', ''))
    return JsonResponse({
        'ok': bool(mask), 'mask': mask,
        'message': '' if mask else
        ('Ответ не добавлен — выберите другой источник или заполните ответ'
         if not request.POST.get('answer', '').strip() else
         'Не удалось определить тип — выберите тип поля и проверьте эталон')})


def _worksheet_context(request):
    """Контекст конструктора: ?worksheet=…[&item=…] (только свои листки)."""
    from worksheets.models import Worksheet, WorksheetItem
    worksheet_id = request.GET.get('worksheet')
    if not worksheet_id:
        return None, None
    worksheet = Worksheet.objects.filter(
        pk=worksheet_id, owner=request.user).first()
    if worksheet is None:
        return None, None
    item = None
    item_id = request.GET.get('item')
    if item_id:
        item = WorksheetItem.objects.filter(
            pk=item_id, worksheet=worksheet).first()
    return worksheet, item


def _save_local_variant(user, original, form, source_fs, subitem_fs, post, image_fs=None):
    """Создаёт скрытую копию задачи с данными из провалидированных форм.

    Оригинал в базе не меняется; копия помечена variant_of и не видна
    в каталоге.
    """
    variant = Task.objects.get(pk=original.pk)
    variant.pk = None
    variant.variant_of = original.variant_of or original
    variant.created_by = user
    for name, value in form.cleaned_data.items():
        setattr(variant, name, value)
    variant.save()
    variant.tags.set(original.tags.all())
    apply_task_taxonomy(variant, post)
    variant._subitem_mapping = {}
    for data in subitem_fs.cleaned_data:
        if not data or data.get('DELETE') or not data.get('text_latex'):
            continue
        new_subitem = TaskSubitem.objects.create(
            task=variant, order=data.get('order') or 0,
            text_latex=data['text_latex'],
            answer_latex=data.get('answer_latex') or '',
            solution_latex=data.get('solution_latex') or '',
            answer_mask=data.get('answer_mask') or '',
            author_answer_latex=data.get('author_answer_latex') or '',
            author_solution_latex=data.get('author_solution_latex') or '')
        if data.get('id'):
            variant._subitem_mapping[data['id'].pk] = new_subitem.pk
    for data in source_fs.cleaned_data:
        if not data or data.get('DELETE') or not data.get('source'):
            continue
        TaskSource.objects.create(
            task=variant, source=data['source'],
            number=data.get('number') or '')
    # Сохранённые файлы переиспользуются, новые загрузки берутся из формы.
    if image_fs is not None:
        for data in image_fs.cleaned_data:
            if data and not data.get('DELETE') and data.get('image'):
                variant.images.create(image=data['image'], order=data.get('order') or 0)
    else:
        for img in original.images.all():
            variant.images.create(image=img.image.name, order=img.order)
    return variant


BULK_LINE_RE = re.compile(r'^(?P<num>.+?)[.)]\s+(?P<ans>.+)$')


def _parse_answer_lines(text):
    """Строки «номер. ответ» (или «номер) ответ») → [(номер, ответ|None)]."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = BULK_LINE_RE.match(line)
        if m:
            number = m.group('num').strip().lstrip('№').strip()
            rows.append((number, m.group('ans').strip()))
        else:
            rows.append((line, None))
    return rows


@teacher_required
def bulk_answers(request):
    """Массовое добавление ответов к задачам по номерам в источнике."""
    context = {
        'sources': Source.objects.all(),
        'text': '',
        'source_id': None,
        'rows': None,
    }
    if request.method != 'POST':
        return render(request, 'problems/bulk_answers.html', context)

    source = Source.objects.filter(pk=request.POST.get('source', 0) or 0).first()
    text = request.POST.get('answers', '')
    context['text'] = text
    context['source_id'] = source.pk if source else None
    if source is None:
        messages.error(request, 'Выберите источник.')
        return render(request, 'problems/bulk_answers.html', context)

    refs = {ref.number: ref.task
            for ref in TaskSource.objects.filter(source=source)
                                         .select_related('task')}
    rows = []
    for number, answer in _parse_answer_lines(text):
        task = refs.get(number)
        if answer is None:
            status = 'unparsed'
        elif task is None:
            status = 'notfound'
        elif not task.answer_latex.strip():
            status = 'new'
        elif task.answer_latex.strip() == answer:
            status = 'same'
        else:
            status = 'conflict'
        rows.append({'number': number, 'answer': answer,
                     'task': task, 'status': status})

    if request.POST.get('action') == 'apply':
        overwrite = {int(x) for x in request.POST.getlist('overwrite')
                     if x.isdigit()}
        applied = 0
        for row in rows:
            task = row['task']
            if row['status'] == 'new' or (
                    row['status'] == 'conflict' and task.pk in overwrite):
                task.answer_latex = row['answer']
                task.save()
                row['status'] = 'applied'
                applied += 1
        skipped = sum(1 for r in rows if r['status'] in
                      ('conflict', 'notfound', 'unparsed'))
        messages.success(
            request,
            f'Ответы записаны: {applied}. Пропущено (конфликты, '
            f'ненайденные, нераспознанные): {skipped}.')

    context['rows'] = rows
    return render(request, 'problems/bulk_answers.html', context)


def _next_number(number):
    """«5.17а» → «5.18а»: увеличивает последнее число в номере источника."""
    m = re.search(r'(\d+)(\D*)$', number)
    if not m:
        return number
    return number[:m.start(1)] + str(int(m.group(1)) + 1) + m.group(2)


def _quick_entry_initials(request):
    """Инициализация формы из ?from=<pk> («Сохранить и добавить следующую»):
    темы/теги/класс/звёзды/источник предыдущей задачи, номер +1."""
    prev = Task.objects.filter(pk=request.GET.get('from', 0) or 0).first()
    if prev is None:
        return None, None
    form_initial = {
        'grade_level': prev.grade_level,
        'stars': prev.stars,
        'difficulty': prev.difficulty,
        'columns': prev.columns,
    }
    source_initial = [
        {'source': ref.source_id, 'number': _next_number(ref.number)}
        for ref in prev.source_refs.all()
    ]
    return form_initial, source_initial


def _task_form(request, task):
    worksheet, item = _worksheet_context(request)
    if request.method == 'POST':
        # Старые клиенты не присылают авторские поля — не обнуляем их.
        data = request.POST.copy()
        if task:
            if 'answer_policy_submitted' not in data:
                data['full_answer_only'] = task.full_answer_only
            for name in ('author_answer_latex', 'author_solution_latex'):
                if name not in data:
                    data[name] = getattr(task, name)
            try:
                total = min(max(int(data.get('subitems-TOTAL_FORMS', 0)), 0), 2000)
            except ValueError:
                total = 0
            for i in range(total):
                sub = task.subitems.filter(pk=data.get(f'subitems-{i}-id') or None).first()
                if sub:
                    for name in ('author_answer_latex', 'author_solution_latex'):
                        data.setdefault(f'subitems-{i}-{name}', getattr(sub, name))
        form = TaskForm(data, instance=task)
        source_fs = TaskSourceFormSet(
            request.POST, instance=task or form.instance)
        subitem_fs = TaskSubitemFormSet(
            data, instance=task or form.instance)
        image_fs = TaskImageFormSet(
            request.POST, request.FILES, instance=task or form.instance)
        save_local = ('save_local' in request.POST and task is not None
                      and item is not None and item.task_id == task.pk
                      and task.variant_of_id is None)
        if (form.is_valid() and source_fs.is_valid()
                and subitem_fs.is_valid() and image_fs.is_valid()):
            # Дедупликация: не создавать вторую задачу с теми же условием
            # и подпунктами
            if task is None and 'force_create' not in request.POST:
                from worksheets.import_tex import find_existing_task
                new_subitems = [
                    row.get('text_latex', '')
                    for row in subitem_fs.cleaned_data
                    if row and not row.get('DELETE')]
                duplicate_pk = find_existing_task(
                    form.cleaned_data['text_latex'], new_subitems)
                if duplicate_pk is not None:
                    warning = (
                        f'Задача с таким условием уже есть в базе — '
                        f'#{duplicate_pk}. Проверьте её или нажмите '
                        f'«Всё равно создать».')
                    # Файловые поля браузер не пересылает при повторной
                    # отправке формы — предупреждаем, что их надо выбрать
                    # заново
                    if request.FILES:
                        warning += (' Выбранные файлы картинок при этом '
                                    'нужно указать заново.')
                    messages.warning(request, warning)
                    ctx = taxonomy_page_context(
                        taxonomy_state_from_post(request.POST))
                    ctx.update({
                        'form': form,
                        'formset': source_fs,
                        'subitem_formset': subitem_fs,
                        'image_formset': image_fs,
                        'task': task,
                        'worksheet': worksheet,
                        'item': item,
                        'can_save_local': False,
                        'duplicate_pk': duplicate_pk,
                        'mask_help': MASK_HELP,
                    })
                    return render(request, 'problems/task_form.html', ctx)
            if save_local:
                variant = _save_local_variant(
                    request.user, task, form, source_fs, subitem_fs,
                    request.POST, image_fs=image_fs)
                selected = list(item.subitems.values_list('pk', flat=True))
                item.task = variant
                item.save()
                item.subitems.set([variant._subitem_mapping[pk] for pk in selected
                                   if pk in variant._subitem_mapping])
                messages.success(
                    request,
                    f'Создана локальная копия #{variant.pk} — изменения '
                    f'действуют только в «{worksheet.title}». '
                    f'Задача #{task.pk} в базе не изменилась.')
                return redirect('worksheet_detail', pk=worksheet.pk)
            obj = form.save(commit=False)
            if task is None:
                obj.created_by = request.user
            obj.save()
            form.save_m2m()
            apply_task_taxonomy(obj, request.POST)
            source_fs.instance = obj
            subitem_fs.instance = obj
            image_fs.instance = obj
            source_fs.save()
            subitem_fs.save()
            image_fs.save()
            messages.success(request, 'Задача сохранена.')
            save_and_next = 'save_and_next' in request.POST
            # Из конструктора листка: добавить задачу и вернуться в него
            if worksheet is not None and task is None:
                from worksheets.views import add_task_to_worksheet
                response = add_task_to_worksheet(request, worksheet.pk, obj)
                if not save_and_next:
                    return response
            if save_and_next:
                url = f"{reverse('task_create')}?from={obj.pk}"
                if worksheet is not None:
                    url += f'&worksheet={worksheet.pk}'
                return redirect(url)
            if worksheet is not None:
                return redirect('worksheet_detail', pk=worksheet.pk)
            return redirect('task_detail', pk=obj.pk)
    else:
        form_initial, source_initial = (None, None)
        if task is None:
            form_initial, source_initial = _quick_entry_initials(request)
        form = TaskForm(instance=task, initial=form_initial)
        source_fs = TaskSourceFormSet(instance=task, initial=source_initial)
        subitem_fs = TaskSubitemFormSet(instance=task)
        image_fs = TaskImageFormSet(instance=task)
    if request.method == 'POST':
        tax_state = taxonomy_state_from_post(request.POST)
    elif task is not None:
        tax_state = task_taxonomy_state(task)
    elif request.GET.get('from'):
        prev = Task.objects.filter(pk=request.GET.get('from') or 0).first()
        tax_state = task_taxonomy_state(prev) if prev else None
    else:
        tax_state = None
    ctx = taxonomy_page_context(tax_state)
    ctx.update({
        'form': form,
        'formset': source_fs,
        'subitem_formset': subitem_fs,
        'image_formset': image_fs,
        'task': task,
        'worksheet': worksheet,
        'item': item,
        'mask_help': MASK_HELP,
        'can_save_local': (task is not None and item is not None
                           and item.task_id == task.pk
                           and task.variant_of_id is None),
    })
    return render(request, 'problems/task_form.html', ctx)


def _neuro_flag(payload, key):
    """JSON-булево: нет ключа / null → False; иначе только true/false."""
    if key not in payload or payload[key] is None:
        return False
    value = payload[key]
    if not isinstance(value, bool):
        raise ValueError(key)
    return value


@teacher_required
@require_POST
def task_neuro_solve(request):
    """Нейрогенерация черновика ответа/решения.

    JSON {text, subitems} и/или {task_id, apply, overwrite, answers_only}.
    Без apply ничего не пишет в базу — черновик уходит в поля формы.
    С apply=true записывает в задачу (конструктор листка).
    """
    from .neuro import (MAX_TASK_CHARS, NeuroError, NeuroQuotaError,
                        acquire_quota, apply_result, release_quota,
                        solve_task)
    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Некорректный запрос.'}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({'error': 'Некорректный запрос.'}, status=400)

    task = None
    task_id = payload.get('task_id')
    if task_id not in (None, ''):
        # data-task-id в DOM — строка; bool не принимаем (это subclass int).
        if isinstance(task_id, bool) or not isinstance(task_id, (int, str)):
            return JsonResponse({'error': 'Некорректный запрос.'}, status=400)
        if isinstance(task_id, str) and not task_id.isdigit():
            return JsonResponse({'error': 'Некорректный запрос.'}, status=400)
        pk = int(task_id)
        if pk < 1:
            return JsonResponse({'error': 'Некорректный запрос.'}, status=400)
        task = get_object_or_404(Task, pk=pk)

    # Поля формы, если ключ передан; база — только запасной вариант.
    # Пустой массив subitems тоже считается переданным (не подменяем).
    if 'text' in payload:
        text = payload['text']
        if not isinstance(text, str):
            return JsonResponse({'error': 'Некорректный запрос.'}, status=400)
    elif task is not None:
        text = task.text_latex or ''
    else:
        text = ''

    if 'subitems' in payload:
        raw_subs = payload['subitems']
        if (not isinstance(raw_subs, list)
                or any(not isinstance(s, str) for s in raw_subs)):
            return JsonResponse({'error': 'Некорректный запрос.'}, status=400)
        subitems = raw_subs
    elif task is not None:
        subitems = [s.text_latex for s in task.subitems.order_by('order', 'pk')]
    else:
        subitems = []
    if len(text) + sum(len(s) for s in subitems) > MAX_TASK_CHARS:
        return JsonResponse(
            {'error': 'Задача слишком длинная для нейрогенерации.'},
            status=400)
    try:
        apply = _neuro_flag(payload, 'apply')
        overwrite = _neuro_flag(payload, 'overwrite')
        answers_only = _neuro_flag(payload, 'answers_only')
    except ValueError:
        return JsonResponse({'error': 'Некорректный запрос.'}, status=400)
    acquired_at = None
    try:
        acquired_at = acquire_quota(request.user)
        result = solve_task(text, subitems)
        # Пишем, пока квота ещё занята: иначе второй запрос успеет
        # записаться раньше, и первый с overwrite затрёт его устаревшим.
        if task is not None and apply:
            apply_result(
                task, result,
                overwrite=overwrite,
                answers_only=answers_only,
            )
    except NeuroQuotaError as exc:
        return JsonResponse({'error': str(exc)}, status=429)
    except NeuroError as exc:
        return JsonResponse({'error': str(exc)}, status=502)
    finally:
        if acquired_at is not None:
            release_quota(request.user, acquired_at)
    return JsonResponse(result)


def _own_import_batch(request, pk):
    batch = get_object_or_404(TextbookImportBatch, pk=pk)
    if batch.created_by_id != request.user.pk and not request.user.is_superuser:
        raise PermissionDenied
    return batch


def _textbook_collection_groups(batch):
    """Даёт агрегаты по главам и по будущим листовым подборкам."""
    rows = (batch.drafts.exclude(status=TextbookTaskDraft.STATUS_SKIPPED)
            .order_by()
            .values('collection_key', 'source_path')
            .annotate(count=Count('pk'), title=Max('collection_title'),
                      first_position=Min('position'), first_pk=Min('pk')))
    grouped = {}
    for row in rows:
        path = tuple(
            str(part).strip() for part in row['source_path']
            if str(part).strip())
        if not path:
            path = ((row['title'] or '').strip() or batch.title,)
        identity = ((row['collection_key'] or '').strip(), path)
        group = grouped.setdefault(identity, {
            'collection_key': identity[0],
            'path': list(path),
            'title': (row['title'] or '').strip() or path[-1],
            'selectors': [],
            'count': 0,
            'is_leaf': True,
            'level_label': 'Подраздел',
            'book_order': (row['first_position'], row['first_pk']),
        })
        group['selectors'].append((
            row['collection_key'], row['source_path']))
        group['count'] += row['count']
        group['book_order'] = min(group['book_order'],
                                (row['first_position'], row['first_pk']))
    leaf_groups = list(grouped.values())
    for leaf in leaf_groups:
        for depth in range(1, len(leaf['path'])):
            prefix = tuple(leaf['path'][:depth])
            identity = ('__prefix__', prefix)
            group = grouped.setdefault(identity, {
                'collection_key': '',
                'path': list(prefix),
                'title': prefix[-1],
                'selectors': [],
                'count': 0,
                'is_leaf': False,
                'level_label': ('Глава целиком'
                                if depth == 1 else 'Раздел целиком'),
                'book_order': leaf['book_order'],
            })
            group['selectors'].extend(leaf['selectors'])
            group['count'] += leaf['count']
            group['book_order'] = min(group['book_order'], leaf['book_order'])
    for identity, group in grouped.items():
        raw = json.dumps(identity, ensure_ascii=False, separators=(',', ':'))
        group['token'] = hashlib.sha256(
            raw.encode('utf-8')).hexdigest()[:20]
        if not group['is_leaf'] and len(group['path']) == 1:
            group['optgroup'] = 'Главы целиком'
        elif not group['is_leaf']:
            group['optgroup'] = 'Разделы целиком'
        else:
            group['optgroup'] = (
                group['path'][0] if len(group['path']) > 1
                else 'Подразделы')
    # Порядок книги: по первой задаче раздела. Строковый путь ставил
    # «Глава 10» сразу за «Главой 1».
    return sorted(grouped.values(), key=lambda group: (
        group['book_order'], len(group['path']), group['is_leaf'],
        tuple(group['path']), group['collection_key']))


def _group_for_path(groups, path):
    """Находит группу предпросмотра по пути: сначала главу/раздел, потом лист."""
    path = tuple(path)
    prefix = [group for group in groups
              if tuple(group['path']) == path and not group['is_leaf']]
    if prefix:
        return prefix[0]
    exact = [group for group in groups if tuple(group['path']) == path]
    return exact[0] if exact else None


def _section_filter_href(request, token):
    """Тот же GET, что раньше отправляла форма «Показать подборку»."""
    if not token:
        return ''
    query = _textbook_detail_query(
        request, section=token, page=None, collection_page=None)
    return f'?{query}#collection-preview'


def _all_sections_href(request):
    """Сбрасывает раздел, сохраняет вкладку статуса."""
    query = _textbook_detail_query(
        request, section=None, page=None, collection_page=None)
    # Всегда оставляем «?», иначе «#якорь» не сбрасывает ?section=…
    return f'?{query}#collection-preview'


def _annotate_section_nav_row(row, request, selected_token,
                              work_group, title_group):
    work_token = work_group['token'] if work_group else ''
    title_token = title_group['token'] if title_group else ''
    row['work_href'] = _section_filter_href(request, work_token)
    row['title_href'] = _section_filter_href(request, title_token)
    row['work_current'] = bool(work_token and work_token == selected_token)
    row['title_current'] = bool(title_token and title_token == selected_token)
    return row


def _link_ziv_variant_summary(summary, collection_groups, request,
                              selected_token):
    for row in summary:
        work_group = _group_for_path(collection_groups, [row['work']])
        title_path = [row['work'], row['title']] if row.get('title') else [
            row['work']]
        title_group = _group_for_path(collection_groups, title_path)
        if title_group is None:
            title_group = next(
                (group for group in collection_groups
                 if len(group['path']) >= 2
                 and group['path'][0] == row['work']
                 and group['path'][1] == row['title']
                 and not group['is_leaf']),
                None)
        _annotate_section_nav_row(
            row, request, selected_token, work_group, title_group)
    return summary


# Уровни сложности внутри параграфа («Первый уровень» у Шабунина) — не
# темы: в сводке они идут ссылками внутри строки своего параграфа.
_LEVEL_TITLE_RE = re.compile(
    r'(?i)^(?:перв|втор|трет|четв[её]рт|пят)\w*\s+уровень(?:\s+сложности)?$')


def _section_nav_rows(collection_groups, request, selected_token):
    """Ссылки на главы и листовые подборки, если нет сводки Зива."""
    rows = []
    by_topic = {}
    for leaf in collection_groups:
        if not leaf['is_leaf']:
            continue
        path = leaf['path']
        if len(path) >= 3 and _LEVEL_TITLE_RE.match(path[-1]):
            parent = path[:-1]
            row = by_topic.get(tuple(parent))
            if row is None:
                row = {
                    'work': parent[0],
                    'title': ' › '.join(parent[1:]),
                    'count': 0,
                    'levels': [],
                }
                _annotate_section_nav_row(
                    row, request, selected_token,
                    _group_for_path(collection_groups, [parent[0]]),
                    _group_for_path(collection_groups, parent))
                by_topic[tuple(parent)] = row
                rows.append(row)
            row['count'] += leaf['count']
            row['levels'].append({
                'title': path[-1],
                'count': leaf['count'],
                'href': _section_filter_href(request, leaf['token']),
                'current': leaf['token'] == selected_token,
            })
            continue
        work = leaf['path'][0]
        title = leaf['path'][-1] if len(leaf['path']) > 1 else leaf['title']
        # Только варианты требуют уточнения работы; названия глав и
        # параграфов остальных книг сохраняют прежний компактный вид.
        if re.fullmatch(r'(?:Вариант\s+\d+|Подготовительный вариант)', title, re.I):
            title = ' › '.join(leaf['path'][1:]) or title
        row = {
            'work': work,
            'title': title,
            'count': leaf['count'],
        }
        _annotate_section_nav_row(
            row, request, selected_token,
            _group_for_path(collection_groups, [work]),
            leaf)
        rows.append(row)
    return rows


def _textbook_detail_query(request=None, **overrides):
    params = request.GET.copy() if request is not None else {}
    if not hasattr(params, 'urlencode'):
        from django.http import QueryDict
        params = QueryDict('', mutable=True)
    else:
        params = params.copy()
    for key, value in overrides.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


def _textbook_detail_url(batch, request=None, **overrides):
    query = _textbook_detail_query(request, **overrides)
    url = reverse('textbook_import_detail', args=[batch.pk])
    return f'{url}?{query}' if query else url


ANSWERS_FILTER_NONE = 'none'


def _draft_lacks_answer(author_answer, answer, subitems) -> bool:
    if str(author_answer or answer or '').strip():
        return False
    return not any(
        str((item or {}).get('author_answer_latex')
            or (item or {}).get('answer_latex') or '').strip()
        for item in (subitems or []))


def _filter_drafts_without_answers(qs):
    """Черновики без ответа у родителя и у всех подпунктов."""
    empty_pks = [
        pk for pk, author_answer, answer, items in qs.values_list(
            'pk', 'author_answer_latex', 'answer_latex', 'subitems')
        if _draft_lacks_answer(author_answer, answer, items)
    ]
    return qs.filter(pk__in=empty_pks)


def _textbook_group_drafts(batch, group):
    selector = Q()
    for collection_key, source_path in group['selectors']:
        selector |= Q(
            collection_key=collection_key, source_path=source_path)
    return batch.drafts.filter(selector)


def _filter_import_drafts(drafts, *, status='', answers=''):
    """Общие фильтры таблицы и массового выбора по всем страницам."""
    if status in dict(TextbookTaskDraft.STATUS_CHOICES):
        drafts = drafts.filter(status=status)
    if answers == ANSWERS_FILTER_NONE:
        drafts = _filter_drafts_without_answers(drafts)
    return drafts


def _draft_taxonomy_json(draft):
    from .textbook_topics import draft_topic_ids
    ids = draft_topic_ids(draft)
    return dumps_state({
        'topics': ids,
        'primary': draft.topic_id,
        'grades': [], 'facets': [], 'exams': [], 'difficulty': None,
    })


def _attach_draft_taxonomy(drafts):
    for draft in drafts:
        draft.taxonomy_json = _draft_taxonomy_json(draft)


def _group_topic_counts(drafts):
    from collections import Counter
    from .textbook_topics import draft_topic_ids
    counter = Counter()
    for draft in drafts:
        ids = draft_topic_ids(draft)
        if not ids:
            counter[None] += 1
        else:
            for pk in ids:
                counter[pk] += 1
    topics = {
        topic.pk: topic
        for topic in Topic.objects.filter(
            pk__in=[pk for pk in counter if pk])
    }
    rows = []
    for pk, count in counter.most_common():
        if pk is None:
            rows.append({'label': 'Тема не выбрана', 'count': count})
            continue
        topic = topics.get(pk)
        rows.append({
            'label': str(topic) if topic else f'Тема #{pk}',
            'count': count,
        })
    return rows


def _subitem_label_key(value):
    value = str(value or '').strip().lower()
    aliases = {
        'а': 'a', 'a': 'a',
        'б': 'b', 'b': 'b', '6': 'b',
        'в': 'c', 'c': 'c',
        'г': 'd', 'd': 'd',
        'д': 'e', 'e': 'e',
    }
    return aliases.get(value, value)


def _review_subitem_post_count(post):
    count = 0
    while any(
            f'{prefix}{count}' in post
            for prefix in (
                'subitem_text_', 'subitem_label_',
                'subitem_answer_', 'subitem_solution_',
                'subitem_author_answer_', 'subitem_answer_mask_',
                'subitem_author_solution_')):
        count += 1
    return count


def _subitems_from_review_editors(post):
    """Собирает подпункты из отдельных полей сверки; JSON не нужен."""
    from .textbook_import import normalize_subitems
    items = []
    for index in range(_review_subitem_post_count(post)):
        items.append({
            'label': post.get(f'subitem_label_{index}', '') or str(index + 1),
            'text_latex': post.get(f'subitem_text_{index}', ''),
            'author_answer_latex': post.get(
                f'subitem_author_answer_{index}', ''),
            'answer_mask': post.get(f'subitem_answer_mask_{index}', ''),
            'author_solution_latex': post.get(
                f'subitem_author_solution_{index}', ''),
        })
        for field in ('answer_latex', 'solution_latex'):
            key = f"subitem_{field.removesuffix('_latex')}_{index}"
            if key in post:
                items[-1][field] = post[key]
    return normalize_subitems(items)


def _merge_review_subitems(from_editors, from_json):
    """JSON задаёт состав и порядок; редакторы перекрывают пункт с той же меткой.

    Иначе удаление или перестановка в служебном JSON молча игнорировались бы
    полями подпунктов, которые страница всё равно присылает целиком.
    """
    by_label = {}
    for item in from_editors:
        key = _subitem_label_key(item.get('label'))
        if key not in by_label:
            by_label[key] = item
    merged = []
    used = set()
    for item in from_json:
        key = _subitem_label_key(item.get('label'))
        if key in by_label and key not in used:
            merged.append({**item, **by_label[key]})
            used.add(key)
        else:
            merged.append(item)
    return merged


def _overlay_review_author_fields(subitems, original, post):
    """Поля материалов привязываются к метке, а не к позиции JSON."""
    from .textbook_import import normalize_answer_mask

    by_label = {}
    for index, item in enumerate(original):
        values = {}
        for field in ('author_answer_latex', 'author_solution_latex',
                      'answer_latex', 'solution_latex', 'answer_mask'):
            prefix = field.removesuffix('_latex')
            key = f'subitem_{prefix}_{index}'
            if key in post:
                value = post[key].strip()
                values[field] = (normalize_answer_mask(value)
                                 if field == 'answer_mask' else value)
        if values:
            by_label[_subitem_label_key(item.get('label'))] = values
    used = set()
    for subitem in subitems:
        key = _subitem_label_key(subitem.get('label'))
        if key in by_label and key not in used:
            subitem.update(by_label[key])
            used.add(key)
    return subitems


@teacher_required
def textbook_import_list(request):
    batches = TextbookImportBatch.objects.all()
    if not request.user.is_superuser:
        batches = batches.filter(created_by=request.user)
    # Без diagnostics: MySQL сортирует (-created_at) и группирует строки
    # целиком, большой JSON переполняет буфер сортировки.
    batches = (batches.select_related('source', 'created_by')
               .defer('diagnostics')
               .annotate(total=Count('drafts')))
    return render(request, 'problems/textbook_import_list.html', {
        'batches': batches,
    })


@teacher_required
def textbook_import_help(request):
    """Инструкция редактора по сверке и загрузке задачника."""
    return render(request, 'problems/textbook_import_help.html')


@teacher_required
def textbook_import_upload(request):
    from .textbook_import import (TextbookImportError,
                                  attach_image_archive,
                                  create_batch_from_bundle,
                                  parse_tex_uploads, read_bundle)
    if request.method == 'POST':
        form = TextbookBundleUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                input_kind = form.cleaned_data['input_kind']
                if input_kind == TextbookBundleUploadForm.INPUT_JSON:
                    payload = read_bundle(form.cleaned_data['bundle'])
                else:
                    payload = parse_tex_uploads(
                        form.cleaned_data['tasks_tex'],
                        profile=form.cleaned_data['resolved_profile'],
                        solutions_upload=form.cleaned_data.get(
                            'solutions_tex'))
                with transaction.atomic():
                    batch = create_batch_from_bundle(
                        payload, user=request.user,
                        title=form.cleaned_data['title'],
                        source_title=form.cleaned_data['source_title'],
                        source_author=form.cleaned_data['source_author'],
                        source_year=form.cleaned_data['source_year'])
                    images_zip = form.cleaned_data.get('images_zip')
                    if images_zip:
                        stored = attach_image_archive(batch, images_zip)
                        messages.success(
                            request,
                            f'Сопоставлено рисунков: {stored}.')
            except TextbookImportError as exc:
                error_field = ('bundle' if form.cleaned_data.get('input_kind')
                               == TextbookBundleUploadForm.INPUT_JSON
                               else 'tasks_tex')
                form.add_error(error_field, str(exc))
            else:
                messages.success(
                    request,
                    f'Партия создана: {batch.drafts.count()} задач.')
                return redirect('textbook_import_detail', pk=batch.pk)
    else:
        form = TextbookBundleUploadForm()
    return render(request, 'problems/textbook_import_upload.html', {
        'form': form,
    })


@teacher_required
def textbook_import_detail(request, pk):
    batch = _own_import_batch(request, pk)
    from .textbook_import import missing_imported_collection_draft_ids
    missing_collection_ids = missing_imported_collection_draft_ids(batch)
    status = request.GET.get('status', '')
    collection_groups = _textbook_collection_groups(batch)
    groups_by_token = {group['token']: group for group in collection_groups}
    selected_token = request.GET.get('section', '')
    selected_group = groups_by_token.get(selected_token)
    drafts = batch.drafts.select_related('topic', 'imported_task')
    if selected_group:
        drafts = _textbook_group_drafts(batch, selected_group).select_related(
            'topic', 'imported_task')
    drafts = _filter_import_drafts(drafts, status=status)
    answers_filter = request.GET.get('answers', '')
    missing_answer_count = _filter_drafts_without_answers(drafts).count()
    drafts = _filter_import_drafts(drafts, answers=answers_filter)
    filtered_selectable_count = drafts.exclude(
        status=TextbookTaskDraft.STATUS_IMPORTED).count()
    paginator = Paginator(drafts, 50)
    page = paginator.get_page(request.GET.get('page'))
    # Meta.ordering по external_id иначе попадает в GROUP BY: для каждого
    # статуса получаем много строк с единицей, а dict оставляет последнюю.
    counts = dict(batch.drafts.order_by().values_list('status')
                  .annotate(n=Count('pk')))
    status_tabs = [
        {
            'value': value,
            'label': label,
            'count': counts.get(value, 0),
            'href': '?' + _textbook_detail_query(
                request, status=value, page=None),
            'current': status == value,
        }
        for value, label in TextbookTaskDraft.STATUS_CHOICES
    ]
    selected_topic = None
    selected_topics = []
    suggested_topic = None
    if selected_group:
        from .textbook_topics import (candidate_reason_label,
                                      draft_topic_ids,
                                      suggested_topic_for_drafts)
        group_drafts = _textbook_group_drafts(batch, selected_group)
        selected_group['topic_counts'] = _group_topic_counts(
            group_drafts.only('topic_id', 'topic_ids', 'batch_id'))
        suggested_topic = suggested_topic_for_drafts(
            group_drafts.select_related('topic'))
        assigned_sets = [
            tuple(draft_topic_ids(draft))
            for draft in group_drafts.only('topic_id', 'topic_ids',
                                           'batch_id')
        ]
        if assigned_sets and len(set(assigned_sets)) == 1 and assigned_sets[0]:
            selected_topics = list(assigned_sets[0])
            selected_topic = selected_topics[0]
        elif suggested_topic:
            selected_topic = suggested_topic.pk
            selected_topics = [selected_topic]
        candidate_rows = (
            group_drafts.exclude(topic_candidates=[])
            .values_list('topic_candidates', flat=True)[:8])
        shown = []
        seen = set()
        for payload in candidate_rows:
            for item in payload or []:
                key = item.get('id') or item.get('code')
                if key in seen:
                    continue
                seen.add(key)
                shown.append({
                    **item,
                    'reason_label': candidate_reason_label(item.get('reason')),
                })
                if len(shown) == 5:
                    break
            if len(shown) == 5:
                break
        selected_group['topic_candidates'] = shown
        section_statuses = list(group_drafts.values_list('status', flat=True))
        selected_group['approved_count'] = sum(
            status == TextbookTaskDraft.STATUS_APPROVED
            for status in section_statuses)
        selected_group['missing_collection_count'] = len(
            missing_imported_collection_draft_ids(batch, group_drafts))
        selected_group['open_count'] = sum(
            status in {TextbookTaskDraft.STATUS_REVIEW,
                       TextbookTaskDraft.STATUS_CONFLICT}
            for status in section_statuses)
        selected_group['can_commit'] = (
            selected_group['approved_count'] > 0
            or selected_group['missing_collection_count'] > 0)
    _attach_draft_taxonomy(page.object_list)
    context = taxonomy_page_context({
        'topics': selected_topics,
        'primary': selected_topic,
        'grades': [], 'facets': [], 'exams': [], 'difficulty': None,
    })
    from .textbook_import import ziv_variant_summary
    ziv_summary = _link_ziv_variant_summary(
        ziv_variant_summary(batch), collection_groups, request,
        selected_token)
    context.update({
        'batch': batch,
        'page': page,
        'counts': counts,
        'status': status,
        'status_tabs': status_tabs,
        'answers_filter': (
            answers_filter if answers_filter == ANSWERS_FILTER_NONE else ''),
        'missing_answer_count': missing_answer_count,
        'all_drafts_href': '?' + _textbook_detail_query(
            request, status=None, answers=None, page=None),
        'missing_answers_href': '?' + _textbook_detail_query(
            request,
            answers=(None if answers_filter == ANSWERS_FILTER_NONE
                     else ANSWERS_FILTER_NONE),
            page=None),
        'collection_groups': collection_groups,
        'selected_group': selected_group,
        'selected_section': selected_token if selected_group else '',
        'filtered_selectable_count': filtered_selectable_count,
        'selected_topic': selected_topic,
        'suggested_topic': suggested_topic,
        'ziv_variant_summary': ziv_summary,
        'section_nav': (
            [] if ziv_summary else _section_nav_rows(
                collection_groups, request, selected_token)),
        'image_form': TextbookImageArchiveForm(),
        'list_query': _textbook_detail_query(
            request, section=selected_token if selected_group else None,
            page=None),
        'all_sections_href': _all_sections_href(request),
        'approved_count': counts.get(TextbookTaskDraft.STATUS_APPROVED, 0),
        'missing_collection_count': len(missing_collection_ids),
        'masks_pending_count': _masks_pending_count(batch.drafts.all()),
        'section_masks_pending_count': (
            _masks_pending_count(_textbook_group_drafts(batch, selected_group))
            if selected_group else 0),
    })
    return render(request, 'problems/textbook_import_detail.html', context)


def _masks_pending_count(drafts):
    """Строки с отложенным подбором масок (ещё не загруженные)."""
    from .textbook_import import DEFERRED_MASK_WARNING
    return sum(
        DEFERRED_MASK_WARNING in (warnings or [])
        for warnings in drafts.exclude(status__in=[
            TextbookTaskDraft.STATUS_IMPORTED,
            TextbookTaskDraft.STATUS_SKIPPED]).values_list('warnings', flat=True))


@teacher_required
@require_POST
@transaction.atomic
def textbook_import_assign_section_topic(request, pk):
    """Назначает одну тему всем черновикам будущей подборки."""
    batch = _own_import_batch(request, pk)
    batch = TextbookImportBatch.objects.select_for_update().get(pk=batch.pk)
    section_token = request.POST.get('section', '')
    group = next((item for item in _textbook_collection_groups(batch)
                  if item['token'] == section_token), None)
    if group is None:
        messages.error(request, 'Выбранный раздел задачника не найден.')
        return redirect(_textbook_detail_url(batch, section=section_token))
    if batch.status == TextbookImportBatch.STATUS_IMPORTED:
        messages.error(
            request, 'Загруженную партию нельзя изменять через предпросмотр.')
        return redirect(_textbook_detail_url(batch, section=section_token))
    from .textbook_topics import (set_draft_topics, suggested_topic_for_drafts,
                                 topics_from_post)
    topic_ids, primary_id = topics_from_post(request.POST)
    if not topic_ids:
        suggested = suggested_topic_for_drafts(
            _textbook_group_drafts(batch, group).select_related('topic'))
        if suggested:
            topic_ids, primary_id = [suggested.pk], suggested.pk
    if not topic_ids:
        messages.error(request, 'Выберите тему рубрикатора.')
        return redirect(_textbook_detail_url(batch, section=section_token))
    drafts = list(
        _textbook_group_drafts(batch, group)
        .exclude(status=TextbookTaskDraft.STATUS_IMPORTED))
    for draft in drafts:
        set_draft_topics(draft, topic_ids, primary_id)
    labels = ', '.join(
        str(topic) for topic in Topic.objects.filter(pk__in=topic_ids))
    messages.success(
        request,
        f'Темы ({labels}) назначены задачам раздела '
        f'«{group["title"]}»: {len(drafts)}.')
    return redirect(_textbook_detail_url(batch, section=section_token))


@teacher_required
@require_POST
def textbook_import_quick_topic(request, batch_pk, pk):
    """Горячее назначение темы одной строке партии — как в базе задач."""
    batch = _own_import_batch(request, batch_pk)
    draft = get_object_or_404(TextbookTaskDraft, batch=batch, pk=pk)
    if (batch.status == TextbookImportBatch.STATUS_IMPORTED
            or draft.status == TextbookTaskDraft.STATUS_IMPORTED):
        return JsonResponse(
            {'ok': False, 'message': 'Загруженную партию нельзя изменять.'},
            status=400)
    from .textbook_topics import set_draft_topics, topics_from_post
    topic_ids, primary_id = topics_from_post(request.POST)
    set_draft_topics(draft, topic_ids, primary_id)
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return redirect(_textbook_detail_url(batch, request))
    return JsonResponse({'ok': True})


@teacher_required
@require_POST
@transaction.atomic
def textbook_import_bulk(request, pk):
    """Массовые действия над выбранными черновиками партии."""
    batch = _own_import_batch(request, pk)
    batch = TextbookImportBatch.objects.select_for_update().get(pk=batch.pk)
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts=None):
        next_url = _textbook_detail_url(batch, request)
    if batch.status == TextbookImportBatch.STATUS_IMPORTED:
        messages.error(request, 'Загруженную партию нельзя изменять.')
        return redirect(next_url)
    scope = request.POST.get('selection_scope', 'page')
    if scope == 'filtered':
        filter_status = request.POST.get('filter_status', '')
        filter_answers = request.POST.get('filter_answers', '')
        section = request.POST.get('filter_section', '')
        group = next((group for group in _textbook_collection_groups(batch)
                      if group['token'] == section), None) if section else None
        if ((filter_status and filter_status not in dict(TextbookTaskDraft.STATUS_CHOICES))
                or filter_answers not in ('', ANSWERS_FILTER_NONE)
                or (section and group is None)):
            messages.error(request, 'Фильтры изменились. Обновите страницу и выберите задачи заново.')
            return redirect(next_url)
        drafts = _textbook_group_drafts(batch, group) if group else batch.drafts.all()
        drafts = _filter_import_drafts(
            drafts, status=filter_status, answers=filter_answers)
    elif scope == 'page':
        drafts = batch.drafts.filter(pk__in=request.POST.getlist('ids'))
    else:
        messages.error(request, 'Неизвестный режим выбора задач.')
        return redirect(next_url)
    drafts = drafts.exclude(status=TextbookTaskDraft.STATUS_IMPORTED)
    if not drafts.exists():
        messages.error(request, 'Не выбрано ни одной задачи.')
        return redirect(next_url)
    if request.POST.get('delete'):
        deleted = drafts.count()
        drafts.delete()
        messages.success(request, f'Удалено задач: {deleted}.')
        return redirect(next_url)
    status = request.POST.get('status')
    if request.POST.get('skip'):
        status = TextbookTaskDraft.STATUS_SKIPPED
    allowed_statuses = {
        TextbookTaskDraft.STATUS_APPROVED,
        TextbookTaskDraft.STATUS_REVIEW,
        TextbookTaskDraft.STATUS_CONFLICT,
        TextbookTaskDraft.STATUS_SKIPPED,
    }
    if status in allowed_statuses:
        now = timezone.now()
        updated = drafts.update(
            status=status,
            reviewed_by=request.user,
            reviewed_at=now,
        )
        labels = {
            TextbookTaskDraft.STATUS_APPROVED: 'Одобрено задач',
            TextbookTaskDraft.STATUS_REVIEW: 'Возвращено на проверку',
            TextbookTaskDraft.STATUS_CONFLICT: 'Отмечено конфликтными',
            TextbookTaskDraft.STATUS_SKIPPED: 'Пропущено задач',
        }
        messages.success(request, f'{labels[status]}: {updated}.')
        return redirect(next_url)
    from .textbook_topics import merge_draft_topics, topics_from_post
    topic_ids, primary_id = topics_from_post(request.POST)
    if not topic_ids:
        messages.error(request, 'Выберите тему рубрикатора.')
        return redirect(next_url)
    updated = 0
    for draft in drafts:
        merge_draft_topics(draft, topic_ids, primary_id)
        updated += 1
    labels = ', '.join(
        str(topic) for topic in Topic.objects.filter(pk__in=topic_ids))
    messages.success(
        request, f'Темы ({labels}) добавлены выбранным задачам: {updated}.')
    return redirect(next_url)


@teacher_required
def textbook_import_block(request, batch_pk, block_pk):
    """Показывает все пять черновиков с общим условием один раз."""
    from .block_text import split_common_condition
    from .textbook_import import normalize_image_stem
    batch = _own_import_batch(request, batch_pk)
    drafts = list(batch.drafts.filter(block_id=block_pk)
                  .select_related('block').order_by('block_position'))
    if not drafts:
        raise Http404
    assets = {asset.stem: asset for asset in batch.assets.all()}

    def parts(text, images):
        result, start = [], 0
        for match in re.finditer(r'\\taskpic\{(\d+)\}', text):
            result.append({'text': text[start:match.start()]})
            index = int(match.group(1)) - 1
            name = images[index] if 0 <= index < len(images) else ''
            result.append({'image': True, 'name': name,
                           'asset': assets.get(normalize_image_stem(name))})
            start = match.end()
        result.append({'text': text[start:]})
        return result

    split = None
    if [d.block_position for d in drafts] == [1, 2, 3, 4, 5]:
        split = split_common_condition([d.text_latex for d in drafts],
                                       [d.images for d in drafts])
    common = parts(split.text, drafts[0].images) if split else []
    rows = [{'draft': d, 'parts': parts(split.questions[i] if split else d.text_latex,
                                      d.images)} for i, d in enumerate(drafts)]
    return render(request, 'problems/textbook_import_block.html', {
        'batch': batch, 'task_block': drafts[0].block, 'common': common,
        'rows': rows, 'combined': split is not None})


def _neighbour_draft(batch, draft, *, following):
    """Соседняя строка в порядке книги (position, затем pk)."""
    if following:
        return (batch.drafts.filter(
            Q(position__gt=draft.position)
            | Q(position=draft.position, pk__gt=draft.pk))
            .order_by('position', 'pk').first())
    return (batch.drafts.filter(
        Q(position__lt=draft.position)
        | Q(position=draft.position, pk__lt=draft.pk))
        .order_by('-position', '-pk').first())


@teacher_required
def textbook_import_review(request, batch_pk, pk):
    from .models import ExamItem
    batch = _own_import_batch(request, batch_pk)
    draft = get_object_or_404(
        TextbookTaskDraft.objects.select_related('topic', 'imported_task'),
        batch=batch, pk=pk)
    original_subitems = [dict(item) for item in draft.subitems]
    if (request.method == 'POST'
            and draft.status == TextbookTaskDraft.STATUS_IMPORTED):
        messages.error(
            request,
            'Импортированную задачу нельзя изменять в сверке. '
            'Правки — в карточке задачи.')
        return redirect(
            'textbook_import_review', batch_pk=batch.pk, pk=draft.pk)
    if request.method == 'POST':
        form = TextbookDraftReviewForm(request.POST, instance=draft)
        if form.is_valid():
            updated = form.save(commit=False)
            from .textbook_import import TextbookImportError
            try:
                if any(f'subitem_text_{index}' in request.POST
                       for index in range(_review_subitem_post_count(request.POST))):
                    structured = _subitems_from_review_editors(request.POST)
                    updated.subitems = _merge_review_subitems(
                        structured, updated.subitems)
                else:
                    updated.subitems = _overlay_review_author_fields(
                        updated.subitems, original_subitems, request.POST)
            except TextbookImportError as exc:
                form.add_error('subitems', str(exc))
            if not form.errors:
                if updated.subitems:
                    updated.answer_mask = ''
                if (request.POST.get('topics_submitted')
                        or 'topics' in request.POST
                        or 'topic' in request.POST
                        or 'primary_topic' in request.POST):
                    from .textbook_topics import set_draft_topics, topics_from_post
                    topic_ids, primary_id = topics_from_post(request.POST)
                    set_draft_topics(
                        updated, topic_ids, primary_id, save=False)
                from .textbook_import import refresh_image_warnings
                from .textbook_parser import finalize_draft_images
                finalize_draft_images(updated)
                updated.reviewed_by = request.user
                updated.reviewed_at = timezone.now()
                updated.save()
                refresh_image_warnings(batch)
                if request.POST.get('prepare_masks'):
                    # Подбор после сохранения: маски строятся по ответам,
                    # которые учитель только что поправил в этой форме.
                    from .textbook_import import complete_draft_answer_masks
                    added = complete_draft_answer_masks(updated)
                    messages.success(
                        request, f'{updated.external_id}: сохранено, подобрано масок — {added}.'
                        if added else f'{updated.external_id}: сохранено; новых масок нет — '
                                      'добавьте вручную, если ответ можно проверить.')
                    return redirect('textbook_import_review',
                                    batch_pk=batch.pk, pk=updated.pk)
                messages.success(request, f'{updated.external_id}: сохранено.')
                next_draft = _neighbour_draft(batch, updated, following=True)
                if request.POST.get('save_next') and next_draft:
                    return redirect(
                        'textbook_import_review', batch_pk=batch.pk,
                        pk=next_draft.pk)
                return redirect(
                    'textbook_import_review', batch_pk=batch.pk, pk=updated.pk)
    else:
        form = TextbookDraftReviewForm(instance=draft)
    previous = _neighbour_draft(batch, draft, following=False)
    following = _neighbour_draft(batch, draft, following=True)
    from .textbook_parser import order_letter_subitems
    review_subitems = [dict(item) for item in draft.subitems]
    if request.method == 'POST':
        for index, subitem in enumerate(review_subitems):
            if f'subitem_label_{index}' in request.POST:
                subitem['label'] = request.POST[f'subitem_label_{index}']
            if f'subitem_text_{index}' in request.POST:
                subitem['text_latex'] = request.POST[f'subitem_text_{index}']
            answer_key = f'subitem_author_answer_{index}'
            mask_key = f'subitem_answer_mask_{index}'
            solution_key = f'subitem_author_solution_{index}'
            for field in ('answer_latex', 'solution_latex'):
                key = f"subitem_{field.removesuffix('_latex')}_{index}"
                if key in request.POST:
                    subitem[field] = request.POST[key]
            if answer_key in request.POST:
                subitem['author_answer_latex'] = request.POST[answer_key]
            if mask_key in request.POST:
                subitem['answer_mask'] = request.POST[mask_key]
            if solution_key in request.POST:
                subitem['author_solution_latex'] = request.POST[solution_key]
    else:
        review_subitems = order_letter_subitems(review_subitems)
    from .textbook_topics import draft_topic_ids, topics_from_post
    if request.method == 'POST':
        review_topic_ids, review_primary = topics_from_post(request.POST)
        if (not review_topic_ids
                and not request.POST.get('topics_submitted')
                and 'topics' not in request.POST
                and 'topic' not in request.POST):
            review_topic_ids = draft_topic_ids(draft)
            review_primary = draft.topic_id
    else:
        review_topic_ids = draft_topic_ids(draft)
        review_primary = draft.topic_id
    context = taxonomy_page_context({
        'topics': review_topic_ids,
        'primary': review_primary,
        'grades': [], 'facets': [], 'exams': [], 'difficulty': None,
    })
    from .textbook_import import normalize_image_stem
    assets = {
        asset.stem: asset
        for asset in batch.assets.all()
    }
    draft_images = []
    for name in draft.images:
        stem = normalize_image_stem(name)
        draft_images.append({
            'name': name,
            'asset': assets.get(stem),
        })
    from .textbook_topics import candidate_reason_label
    from .textbook_import import content_warnings, DEFERRED_MASK_WARNING
    context.update({
        'batch': batch,
        'draft': draft,
        'content_warnings': content_warnings(draft),
        'masks_pending': DEFERRED_MASK_WARNING in draft.warnings,
        'masks_by_exam': draft.masks_by_exam,
        'form': form,
        'review_subitems': review_subitems,
        'import_exam_items': ExamItem.objects.filter(code__in=draft.exam_item_codes),
        'known_tags': list(Tag.objects.values_list('name', flat=True)),
        'previous': previous,
        'following': following,
        'review_locked': draft.status == TextbookTaskDraft.STATUS_IMPORTED,
        'draft_images': draft_images,
        'topic_candidates': [
            {**item, 'reason_label': candidate_reason_label(item.get('reason'))}
            for item in (draft.topic_candidates or [])
        ],
    })
    return render(request, 'problems/textbook_import_review.html', context)


@teacher_required
@require_POST
def textbook_import_attach_images(request, pk):
    from .textbook_import import TextbookImportError, attach_image_archive
    batch = _own_import_batch(request, pk)
    form = TextbookImageArchiveForm(request.POST, request.FILES)
    if batch.status == TextbookImportBatch.STATUS_IMPORTED:
        messages.error(request, 'Загруженную партию нельзя дополнять рисунками.')
        return redirect(_textbook_detail_url(batch))
    if not form.is_valid():
        messages.error(request, 'Выберите ZIP с рисунками.')
        return redirect(_textbook_detail_url(batch))
    try:
        stored = attach_image_archive(batch, form.cleaned_data['images_zip'])
    except TextbookImportError as exc:
        messages.error(request, str(exc))
        return redirect(_textbook_detail_url(batch))
    messages.success(request, f'Сопоставлено рисунков: {stored}.')
    return redirect(_textbook_detail_url(batch))


@teacher_required
@xframe_options_sameorigin
def textbook_import_asset_file(request, batch_pk, pk):
    batch = _own_import_batch(request, batch_pk)
    asset = get_object_or_404(TextbookImportAsset, batch=batch, pk=pk)
    return FileResponse(asset.file.open('rb'), filename=asset.original_name)


@teacher_required
@require_POST
def textbook_import_approve_clean(request, pk):
    from .textbook_import import content_warnings
    batch = _own_import_batch(request, pk)
    drafts = list(batch.drafts.filter(
        status=TextbookTaskDraft.STATUS_REVIEW))
    approved = []
    now = timezone.now()
    for draft in drafts:
        if not content_warnings(draft) and draft.confidence == 1 and draft.topic_id:
            draft.status = TextbookTaskDraft.STATUS_APPROVED
            draft.reviewed_by = request.user
            draft.reviewed_at = now
            approved.append(draft)
    TextbookTaskDraft.objects.bulk_update(
        approved, ['status', 'reviewed_by', 'reviewed_at'])
    messages.success(request, f'Автоматически одобрено: {len(approved)}.')
    return redirect('textbook_import_detail', pk=batch.pk)


def _prepare_import_publication(request, batch, draft_ids=None,
                                approved_only=True):
    """Повторные POST завершают подбор без длинного запроса на всю книгу."""
    from .textbook_import import prepare_batch_answer_masks
    remaining = prepare_batch_answer_masks(
        batch, draft_ids=draft_ids, approved_only=approved_only)
    if remaining:
        return render(request, 'problems/textbook_import_preparing.html', {
            'batch': batch, 'remaining': remaining,
            'action_url': request.path, 'section': request.POST.get('section', ''),
            'masks_only': not approved_only,
        })


@teacher_required
@require_POST
def textbook_import_prepare_masks(request, pk):
    """Подбирает отложенные маски всей партии или раздела до одобрения."""
    batch = _own_import_batch(request, pk)
    section_token = request.POST.get('section', '')
    draft_ids = None
    if section_token:
        group = next((item for item in _textbook_collection_groups(batch)
                      if item['token'] == section_token), None)
        if group is None:
            messages.error(request, 'Выбранный раздел задачника не найден.')
            return redirect(_textbook_detail_url(batch))
        draft_ids = list(_textbook_group_drafts(batch, group)
                         .values_list('pk', flat=True))
    preparing = _prepare_import_publication(
        request, batch, draft_ids, approved_only=False)
    if preparing is not None:
        return preparing
    messages.success(request, 'Маски ответов подобраны. Проверьте их в сверке '
                              'задач или в списке с включёнными ответами.')
    return redirect(_textbook_detail_url(batch, section=section_token or None))


@teacher_required
@require_POST
def textbook_import_commit(request, pk):
    from .textbook_import import TextbookImportError, commit_batch
    batch = _own_import_batch(request, pk)
    try:
        preparing = _prepare_import_publication(request, batch)
        if preparing is not None:
            return preparing
        result = commit_batch(
            batch, user=request.user, require_complete=False)
    except TextbookImportError as exc:
        messages.error(request, str(exc))
        return redirect('textbook_import_detail', pk=batch.pk)
    messages.success(
        request,
        'Импорт завершён: создано задач — %(created)s, '
        'переиспользовано — %(reused)s, новых подборок — %(collections)s.'
        % result)
    batch.refresh_from_db()
    if batch.status == TextbookImportBatch.STATUS_IMPORTED:
        return redirect('collection_list')
    return redirect('textbook_import_detail', pk=batch.pk)


@teacher_required
@require_POST
def textbook_import_commit_section(request, pk):
    """Загружает в каталог только одобренные задачи выбранного раздела."""
    from .textbook_import import TextbookImportError, commit_batch
    batch = _own_import_batch(request, pk)
    section_token = request.POST.get('section', '')
    group = next((item for item in _textbook_collection_groups(batch)
                  if item['token'] == section_token), None)
    if group is None:
        messages.error(request, 'Выбранный раздел задачника не найден.')
        return redirect(_textbook_detail_url(batch, section=section_token))
    group_drafts = _textbook_group_drafts(batch, group)
    draft_ids = list(group_drafts.filter(status__in=[
        TextbookTaskDraft.STATUS_APPROVED,
        TextbookTaskDraft.STATUS_IMPORTED,
    ]).values_list('pk', flat=True))
    try:
        preparing = _prepare_import_publication(request, batch, draft_ids)
        if preparing is not None:
            return preparing
        result = commit_batch(
            batch, user=request.user, draft_ids=draft_ids,
            require_complete=False)
    except TextbookImportError as exc:
        messages.error(request, str(exc))
        return redirect(_textbook_detail_url(batch, section=section_token))
    if any(result.values()):
        messages.success(
            request,
            'Раздел «%(title)s» загружен: создано задач — %(created)s, '
            'переиспользовано — %(reused)s, новых подборок — %(collections)s.'
            % {'title': group['title'], **result})
    else:
        messages.success(request, f'Раздел «{group["title"]}» уже загружен. '
                                  'Изменений нет.')
    batch.refresh_from_db()
    if batch.status == TextbookImportBatch.STATUS_IMPORTED:
        return redirect('collection_list')
    return redirect(_textbook_detail_url(batch, section=section_token))


# Сколько браузер держит каталог рубрикатора без перепроверки. Числа задач
# у тем могут отставать на это время — для подсказок в фильтре не страшно.
TAXONOMY_CATALOG_MAX_AGE = 60


@login_required
@require_GET
def taxonomy_catalog_json(request):
    """Каталог рубрикатора для виджета тем (static/js/taxonomy.js).

    Раньше он целиком вставлялся в каждую страницу с выбором темы и был
    около половины её HTML. Теперь страница несёт только ссылку, а ответ
    кэшируется браузером; после истечения срока — 304 по ETag.
    """
    from livefile.etags import matches
    from .rubricator import taxonomy_catalog_json as build
    text, etag = build()
    if matches(request, etag):
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(text, content_type='application/json; charset=utf-8')
    response['ETag'] = etag
    response['Cache-Control'] = 'private, max-age=%d' % TAXONOMY_CATALOG_MAX_AGE
    return response

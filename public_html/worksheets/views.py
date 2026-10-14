from assignments.checks import HELP as MASK_HELP
import json
import re
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, models, transaction
from django.db.models import prefetch_related_objects
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_POST, require_http_methods

from django.utils.dateparse import parse_date

from accounts.decorators import get_role, teacher_required
from livefile import files as livefiles
from accounts.models import Profile, StudentGroup
from assignments.models import Assignment, locked_check_visibility
from problems.models import Task, Topic, topic_tree
from problems.rubricator import (GRADE_LEVEL_TO_CODE, apply_worksheet_taxonomy,
                                 dumps_state, filter_by_taxonomy,
                                 filter_state_from_params, parse_grade_choice,
                                 set_grade_bands, set_task_topics,
                                 taxonomy_page_context,
                                 taxonomy_state_from_post,
                                 worksheet_taxonomy_state)
from problems.views import filter_tasks

from .collection_pages import build_chunks, section_pages
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
                  .annotate(items_total=models.Count(
                      'items',
                      filter=(models.Q(items__deleted_at__isnull=True)
                              & models.Q(items__task__isnull=False)),
                      distinct=True),
                            was_assigned=models.Exists(Assignment.objects.filter(
                                worksheet_id=models.OuterRef('pk')))))

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
    from assignments.progress import (progress_assignments, progress_groups,
                                      progress_people)
    assignments = list(progress_assignments(
        worksheet.assignments.select_related('student').prefetch_related('source_groups')))
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
    point_groups = progress_groups([
        item for item in items if item.task_id], assignments)
    progress_people_rows = progress_people(point_groups, assignments)

    # Поиск задач для добавления (правая часть страницы)
    search_active = any(request.GET.get(k) for k in ('q', 'topic', 'grade', 'tag', 'who'))
    found_tasks = []
    if search_active:
        found_tasks = list(filter_tasks(request.GET).exclude(pk__in=task_ids)[:15])

    student_profiles = (Profile.students_for(request.user)
                        .select_related('user')
                        .order_by('user__last_name'))
    assigned_ids = set(
        worksheet.assignments.values_list('student_id', flat=True))
    groups = StudentGroup.visible_to(request.user).prefetch_related('students')
    # Листок уже выдан — режим сверки зафиксирован первым назначением
    locked_check = locked_check_visibility(worksheet) if assignments else None

    from .recipients import assignment_sections
    assignment_groups, individual_assignments = assignment_sections(assignments, groups)
    # Диалог видимости задачи: группа отмечена, если задача скрыта у всех её учеников
    for row in rows:
        hidden = row.get('hidden_assignments') or set()
        row['hidden_groups'] = {
            section['group'].pk for section in assignment_groups
            if section['assignments']
            and all(a.pk in hidden for a in section['assignments'])}
    collection = Collection.objects.filter(worksheet=worksheet).select_related('source').first()
    from .authored import SOURCE_TITLE as AUTHORED_SOURCE, is_section
    from assignments.task_usage import attach_usage, audience_context
    usage_ctx = audience_context(request, attach_usage(
        request, [item.task for item in items if item.task_id] + list(found_tasks)))
    return render(request, 'worksheets/worksheet_detail.html', {
        **usage_ctx,
        **taxonomy_page_context(filter_state_from_params(request.GET)),
        'is_authored': bool(collection and collection.source.title == AUTHORED_SOURCE
                            and not is_section(collection)),
        'corpus_key': corpus_key_from_comment(worksheet.comment),
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
        'assignment_groups': assignment_groups,
        'individual_assignments': individual_assignments,
        'point_groups': point_groups,
        'progress_people': progress_people_rows,
        'status_choices': Assignment.STATUS_CHOICES,
        'deleted_items': deleted_items,
    })


@teacher_required
def collection_list(request):
    """Двухуровневый каталог: сначала источник, затем его дерево разделов."""
    sources = _collection_catalog(request.user)
    source_pk = request.GET.get('source', '')
    selected_source = next(
        (row for row in sources if str(row['source'].pk) == source_pk), None)
    return render(request, 'worksheets/collection_list.html', {
        'collection_sources': sources,
        'selected_source': selected_source,
        # Мета-строка шапки: «3 источника · 120 подборок · 2400 задач»
        'collection_totals': {
            'sources': len(sources),
            'leaves': sum(row['leaf_total'] for row in sources),
            'items': sum(row['item_total'] for row in sources),
        },
    })


def _collection_title(collection):
    """Короткое название каталога с двузначным номером задания."""
    title = collection.worksheet.title.strip()
    title = re.sub(
        r'^№\s*1[–-]5\.\s*Практические\s+(?:задачи|задания)\s*:\s*',
        '№01–05. ', title, flags=re.IGNORECASE)
    title = re.sub(
        r'^№\s*1[–-]5\.\s*Практические\s+(?:задачи|задания)\s*$',
        '№01–05', title, flags=re.IGNORECASE)
    match = re.match(r'^№\s*([1-9])([.\s])', title)
    if match:
        title = f'№0{match.group(1)}{match.group(2)}{title[match.end():]}'
    return title


def _natural_key(text):
    """Числа в названии сравниваются как числа: «прототип 1.2» раньше
    «прототип 1.10», а не после «1.19», как при строковом сравнении."""
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', text) if part)


def _collection_sort_key(collection):
    title = _collection_title(collection)
    match = re.match(r'^№\s*(\d+)', title)
    return (int(match.group(1)) if match else 10_000,
            collection.order, _natural_key(title), collection.pk)


def _child_title(child, parent):
    """Название дочерней подборки без повтора родителя: «№01. Планиметрия 1 —
    прототип 1.1» внутри раздела «№01. Планиметрия 1» — просто «Прототип 1.1»."""
    title = child.catalog_title
    prefixes = {_collection_title(parent), parent.worksheet.title.strip(),
                getattr(parent, 'catalog_title', '')}
    for prefix in sorted(filter(None, prefixes), key=len, reverse=True):
        match = re.match(
            r'^' + re.escape(prefix) + r'\s*(?:[—–:-]|\.)\s*(.+)$', title)
        if match and match.group(1).strip():
            tail = match.group(1).strip()
            return tail[0].upper() + tail[1:]
    return title


def _collection_catalog(user):
    """Строит доступное дерево и отсекает ветви без единого элемента."""
    collections = list(
        Collection.objects.all()
        .select_related('worksheet', 'source', 'parent')
        .prefetch_related('worksheet__topics')
        .annotate(direct_items_total=models.Count(
            'worksheet__items',
            filter=models.Q(worksheet__items__deleted_at__isnull=True),
            distinct=True))
        .order_by('source__title', 'order', 'pk'))
    ids = {collection.pk for collection in collections}
    by_source = {}
    for collection in collections:
        collection.catalog_title = _collection_title(collection)
        collection.catalog_visible = (
            user.is_superuser or collection.is_published
            or collection.worksheet.owner_id == user.pk)
        by_source.setdefault(collection.source_id, {
            'source': collection.source, 'collections': [],
        })['collections'].append(collection)

    result = []
    for group in by_source.values():
        by_parent = {}
        for collection in group['collections']:
            parent_id = (collection.parent_id
                         if collection.parent_id in ids else None)
            by_parent.setdefault(parent_id, []).append(collection)
        for siblings in by_parent.values():
            siblings.sort(key=_collection_sort_key)

        def walk(collection, depth=0):
            children = [row for child in by_parent.get(collection.pk, [])
                        if (row := walk(child, depth + 1))]
            direct_items_total = (collection.direct_items_total
                                  if collection.catalog_visible else 0)
            direct_topics = (list(collection.worksheet.topics.all())
                             if collection.catalog_visible else [])
            topics = {topic.pk: topic for topic in direct_topics}
            for child in children:
                topics.update({topic.pk: topic for topic in child['topics']})
            item_total = (direct_items_total
                          + sum(child['item_total'] for child in children))
            if not item_total:
                return None
            return {
                'collection': collection,
                'depth': depth,
                'children': children,
                'direct_items_total': direct_items_total,
                'item_total': item_total,
                'leaf_total': ((1 if direct_items_total else 0)
                               + sum(child['leaf_total'] for child in children)),
                'topics': sorted(topics.values(),
                                 key=lambda topic: (topic.order, topic.name)),
            }

        roots = [row for root in by_parent.get(None, [])
                 if (row := walk(root))]

        def flatten(rows):
            return [item for row in rows
                    for item in [row, *flatten(row['children'])]]

        flat_rows = flatten(roots)
        if not flat_rows:
            continue
        group.update(
            roots=roots,
            rows=flat_rows,
            item_total=sum(row['item_total'] for row in roots),
            leaf_total=sum(row['leaf_total'] for row in roots),
            topics=sorted(
                {topic.pk: topic for row in roots
                 for topic in row['topics']}.values(),
                key=lambda topic: (topic.order, topic.name)),
        )
        result.append(group)
    return result


def _visible_collection(request, pk):
    collection = get_object_or_404(
        Collection.objects.select_related('worksheet', 'source', 'parent')
        .prefetch_related('worksheet__topics'),
        pk=pk)
    if (collection.is_published
            or collection.worksheet.owner_id == request.user.pk
            or request.user.is_superuser):
        return collection
    if not any(
            row['collection'].pk == collection.pk
            for source in _collection_catalog(request.user)
            for row in source['rows']):
        raise PermissionDenied
    return collection


# Не больше, чем cart.CART_ADD_MANY_LIMIT: «Всё в корзину» отправляет все
# задачи развёрнутого раздела одним запросом.
FLAT_ITEMS_LIMIT = 400


def _visible_children(request, collection):
    """Дочерние подборки, которые вправе видеть учитель, с счётчиками."""
    children = collection.children.select_related('worksheet', 'source')
    if not request.user.is_superuser:
        children = children.filter(
            models.Q(is_published=True)
            | models.Q(worksheet__owner_id=request.user.pk))
    children = list(
        children.annotate(
            items_total=models.Count(
                'worksheet__items',
                filter=models.Q(worksheet__items__deleted_at__isnull=True),
                distinct=True),
            children_total=models.Count('children', distinct=True))
        .order_by('order', 'pk'))
    for child in children:
        child.catalog_title = _collection_title(child)
        child.short_title = _child_title(child, collection)
    children.sort(key=_collection_sort_key)
    return children


def _source_number(task, source_id):
    """Номер задачи в задачнике подборки («3.15» у Мерзляка, «1.1» у ФИПИ)
    из TaskSource; None, если ссылки на этот источник нет."""
    if not source_id:
        return None
    for ref in task.source_refs.all():
        if ref.source_id == source_id and ref.number.strip():
            return ref.number.strip().lstrip('№').strip()
    return None


def _collection_rows(items, number=0, source_id=None):
    """Строки задач подборки: номер, подпункты, общее условие блока.

    ``label`` — то, что печатается перед условием: номер из задачника
    (``source_id`` — источник подборки), а если его нет — сквозной
    позиционный номер ``number``.
    """
    rows = []
    for item in items:
        if item.task_id:
            number += 1
        rows.append({
            'item': item,
            'number': number if item.task_id else None,
            'label': ((_source_number(item.task, source_id) or str(number))
                      if item.task_id else ''),
            'subitems': item.selected_subitems() if item.task_id else [],
        })
    from .block_presentation import decorate_block_rows
    decorate_block_rows(rows)
    return rows


def _flat_groups(request, children):
    """Раздел «списком»: два уровня вниз на одной странице.

    Подборки первого и второго уровня показываются с задачами; у
    подраздела второго уровня, где есть свои дети, — только ссылка.
    Возвращает None, если задач слишком много для одной страницы.
    """
    groups = []
    for child in children:
        groups.append({'collection': child, 'depth': 1,
                       'has_children': child.children_total > 0})
        if child.children_total:
            for grand in _visible_children(request, child):
                groups.append({'collection': grand, 'depth': 2,
                               'has_children': grand.children_total > 0})
    total = sum(g['collection'].items_total for g in groups)
    if not total or total > FLAT_ITEMS_LIMIT:
        return None
    by_worksheet = {}
    items = (WorksheetItem.objects
             .filter(worksheet_id__in=[g['collection'].worksheet_id for g in groups],
                     deleted_at__isnull=True)
             .select_related('task')
             .prefetch_related('task__subitems', 'task__images', 'subitems',
                               'task__source_refs')
             .order_by('worksheet_id', 'order', 'id'))
    for item in items:
        by_worksheet.setdefault(item.worksheet_id, []).append(item)
    for group in groups:
        group['rows'] = _collection_rows(
            by_worksheet.get(group['collection'].worksheet_id, []),
            source_id=group['collection'].source_id)
    return groups


def _section_nav(sections, chunks, source_id):
    """Параграфы для боковой панели: страница и диапазон номеров задач."""
    pages = section_pages(chunks)
    nav, number = [], 0
    for section in sections:
        tasks = [item for item in section.items if item.task_id]
        first = last = ''
        if tasks:
            first = _source_number(tasks[0].task, source_id) or str(number + 1)
            last = (_source_number(tasks[-1].task, source_id)
                    or str(number + len(tasks)))
        number += len(tasks)
        nav.append({'section': section, 'page': pages.get(section.index, 1),
                    'first': first, 'last': last, 'total': len(tasks)})
    return nav


@teacher_required
def collection_detail(request, pk):
    """Страница подборки: ответы в рамке после задачи, скрыты тумблером.

    Раздел по умолчанию разворачивается «списком»: подборки двух уровней
    с задачами на одной странице (?view=tree — прежняя таблица детей).
    """
    collection = _visible_collection(request, pk)
    collection.catalog_title = _collection_title(collection)
    all_items = list(collection.worksheet.ordered_items())
    prefetch_related_objects(all_items, 'task__source_refs')
    # Страница — параграф (рубрика «§ N» и её задачи), а не 25 элементов
    # подряд; без рубрик — прежние куски по 25.
    sections, chunks = build_chunks(all_items)
    page = Paginator(chunks or [None], 1).get_page(request.GET.get('page'))
    chunk = page.object_list[0] if chunks else None
    children = _visible_children(request, collection)
    # Пустой технический раздел с единственным продолжением не заставляет
    # пользователя проходить ещё один экран дерева.
    if not all_items and len(children) == 1:
        return redirect('collection_detail', pk=children[0].pk)
    # Строки по блокам страницы (параграф или его часть — со своим заголовком)
    page_blocks, number = [], chunk.first_task_number if chunk else 0
    for block in (chunk.blocks if chunk else []):
        block_rows = _collection_rows(
            block.items, number=number, source_id=collection.source_id)
        number += block.tasks_total
        page_blocks.append({'block': block, 'rows': block_rows})
    rows = [row for entry in page_blocks for row in entry['rows']]
    flat_groups = None
    if children and request.GET.get('view') != 'tree':
        flat_groups = _flat_groups(request, children)
    page_tasks = [row['item'].task for row in rows if row['item'].task_id]
    if flat_groups:
        page_tasks += [row['item'].task for group in flat_groups
                       for row in group['rows'] if row['item'].task_id]
    cart_task_ids = [task.pk for task in page_tasks if not task.variant_of_id]
    from assignments.task_usage import attach_usage, audience_context
    usage_ctx = audience_context(request, attach_usage(request, page_tasks))
    sources = _collection_catalog(request.user)
    selected_source = next(
        (row for row in sources if row['source'].pk == collection.source_id),
        None)
    current_collection_row = next(
        (row for row in (selected_source['rows'] if selected_source else [])
         if row['collection'].pk == collection.pk), None)
    from .authored import SOURCE_TITLE as AUTHORED_SOURCE, is_section
    return render(request, 'worksheets/collection_detail.html', {
        **usage_ctx,
        'is_authored': (collection.source.title == AUTHORED_SOURCE
                        and not is_section(collection)),
        'is_owner': (collection.worksheet.owner_id == request.user.pk
                     or request.user.is_superuser),
        'corpus_key': corpus_key_from_comment(collection.worksheet.comment),
        'collection': collection,
        'worksheet': collection.worksheet,
        'rows': rows,
        'page_blocks': page_blocks,
        'chunk': chunk,
        'tasks_total': sum(1 for item in all_items if item.task_id),
        'section_nav': (_section_nav(sections, chunks, collection.source_id)
                        if any(s.heading is not None for s in sections)
                        else []),
        # Номера вроде «127» или «3.15» не помещаются в колонку 2rem
        'wide_numbers': any(
            len(row['label']) > 3
            for row in rows + [r for g in (flat_groups or [])
                               for r in g['rows']]),
        # Ширина колонки номера — по самому длинному номеру страницы («26.149»):
        # шаблон задаёт --task-num-col, чтобы номер не наползал на текст.
        'number_width': max(
            [len(row['label']) for row in rows + [r for g in (flat_groups or [])
                                                  for r in g['rows']]]
            or [2]),
        'page': page,
        'children': children,
        'flat_groups': flat_groups,
        'tree_view': request.GET.get('view') == 'tree',
        'flat_too_big': bool(children) and request.GET.get('view') != 'tree'
        and flat_groups is None,
        'cart_task_ids': cart_task_ids,
        'can_use': bool(all_items),
        'can_edit': (not children
                     and (collection.worksheet.owner_id == request.user.pk
                          or request.user.is_superuser)),
        'mask_help': MASK_HELP,
        'collection_sources': sources,
        'selected_source': selected_source,
        'current_collection': collection,
        'current_collection_topics': (
            current_collection_row['topics'] if current_collection_row else []),
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
@require_POST
def worksheet_to_collections(request, pk):
    """Свой листок → подборка в «Авторских листках»."""
    from .authored import AuthoredError, move_to_collections
    worksheet = _own_worksheet(request, pk)
    try:
        collection = move_to_collections(worksheet, request.user)
    except AuthoredError as exc:
        messages.error(request, str(exc))
        return redirect('worksheet_detail', pk=worksheet.pk)
    messages.success(
        request, f'Листок «{worksheet.title}» перенесён в подборки '
                 f'(раздел «{collection.parent.worksheet.title}»). '
                 f'Пока он виден только вам.')
    return redirect('collection_detail', pk=collection.pk)


def _own_authored_collection(request, pk):
    collection = get_object_or_404(
        Collection.objects.select_related('worksheet', 'source'), pk=pk)
    if (collection.worksheet.owner_id != request.user.pk
            and not request.user.is_superuser):
        raise PermissionDenied
    return collection


@teacher_required
@require_POST
def collection_to_worksheets(request, pk):
    """Авторская подборка → обратно в «Мои листки»."""
    from .authored import AuthoredError, move_to_worksheets
    collection = _own_authored_collection(request, pk)
    try:
        worksheet = move_to_worksheets(collection)
    except AuthoredError as exc:
        messages.error(request, str(exc))
        return redirect('collection_detail', pk=pk)
    messages.success(
        request, f'Листок «{worksheet.title}» возвращён в мои листки.')
    return redirect('worksheet_detail', pk=worksheet.pk)


@teacher_required
@require_POST
def collection_publish(request, pk):
    """Переключает видимость подборки для других учителей."""
    from .authored import set_published
    collection = _own_authored_collection(request, pk)
    set_published(collection, request.POST.get('published') == '1')
    messages.success(
        request, 'Подборка видна всем учителям.' if collection.is_published
        else 'Подборка видна только вам.')
    return redirect(request.POST.get('next') or reverse(
        'collection_detail', args=[pk]))


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
    if request.POST.get('to_collections'):
        from .authored import AuthoredError, move_to_collections
        moved, skipped = 0, []
        for worksheet in worksheets:
            try:
                move_to_collections(worksheet, request.user)
                moved += 1
            except AuthoredError as exc:
                skipped.append(f'«{worksheet.title}»: {exc}')
        if moved:
            messages.success(request, f'Перенесено в подборки: {moved}.')
        for line in skipped:
            messages.error(request, line)
        return redirect('worksheet_list')
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
            livefiles.touch('worksheet', worksheet.pk)
        else:
            item.deleted_at = timezone.now()
            item.save(update_fields=['deleted_at'])


def add_task_to_worksheet(request, worksheet_id, task):
    """Добавляет задачу в конец листка (используется и из создания задачи).

    Для fetch-запросов конструктора отвечает JSON, как остальные его
    действия; повтор уже добавленной задачи — не ошибка, а подсказка.
    """
    worksheet = get_object_or_404(
        Worksheet.visible_to(request.user), pk=worksheet_id)
    outcome, message = append_task(worksheet, task)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'message': message,
                             'outcome': outcome})
    (messages.info if outcome == 'exists' else messages.success)(
        request, message)
    return redirect('worksheet_detail', pk=worksheet.pk)


@teacher_required
@require_POST
def worksheet_quick_task(request, pk):
    """Быстрая задача из конструктора: условие, ответ, решение, звёзды.

    Класс и темы берутся у листка. Дубликат по условию не создаётся —
    вместо этого предлагается добавить существующую задачу.
    """
    worksheet = _own_worksheet(request, pk)
    text = request.POST.get('text_latex', '').strip()
    if not text:
        return _builder_response(
            request, pk, ok=False, message='Введите условие задачи.')
    from .import_tex import find_existing_task
    duplicate_pk = find_existing_task(text)
    if duplicate_pk is not None:
        return _builder_response(
            request, pk, ok=False,
            message=f'Такая задача уже есть в базе — #{duplicate_pk}. '
                    f'Найдите её по «#{duplicate_pk}» и добавьте.')
    stars = request.POST.get('stars', '1')
    stars = int(stars) if stars.isdigit() and int(stars) in range(4) else 1
    with transaction.atomic():
        task = Task.objects.create(
            text_latex=text,
            answer_latex=request.POST.get('answer_latex', '').strip(),
            solution_latex=request.POST.get('solution_latex', '').strip(),
            stars=stars,
            grade_level=worksheet.grade,
            created_by=request.user)
        code = GRADE_LEVEL_TO_CODE.get(worksheet.grade)
        if code:
            set_grade_bands(task, [code], sync_legacy=False)
        topics = list(worksheet.topics.values_list('pk', flat=True))
        if topics:
            set_task_topics(task, topics, topics[0])
        outcome, message = append_task(worksheet, task)
    return _builder_response(
        request, pk, message=f'Задача #{task.pk} создана. {message}')


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
        livefiles.touch('worksheet', pk)
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
    livefiles.touch('worksheet', pk)
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
    # Группа целиком: скрыть у всех её учеников из назначений листка
    hide_groups = {int(x) for x in request.POST.getlist('hide_groups')
                   if x.isdigit()}
    if hide_groups:
        from .recipients import assignment_sections
        sections, _ = assignment_sections(
            list(worksheet.assignments.select_related('student')
                 .prefetch_related('source_groups')),
            StudentGroup.visible_to(request.user).prefetch_related('students'))
        for section in sections:
            if section['group'].pk in hide_groups:
                hide_assignments.update(a.pk for a in section['assignments'])
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
# в settings.PDF_EDITOR_FONTS (school/palatino требуют подготовки сервера;
# OTF Inter и STIX Two раскладывает на latex-api deploy/vps/deploy.sh)
PDF_EDITOR_FONT_LABELS = (
    ('cm', 'Computer Modern'),
    ('school', 'Schoolbook'),
    ('palatino', 'Palatino'),
    ('stix', 'STIX Two'),
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
    tex = worksheet_to_tex(worksheet, variant)
    if variant == WorksheetPdf.VARIANT_STUDENT and worksheet.student_pdf_options:
        from .latex import apply_pdf_options
        tex = apply_pdf_options(tex, worksheet.student_pdf_options)
    return render(request, 'worksheets/pdf_editor.html', {
        'worksheet': worksheet,
        'variant': variant,
        'variant_label': dict(WorksheetPdf.VARIANT_CHOICES)[variant],
        'variant_choices': WorksheetPdf.VARIANT_CHOICES,
        'tex': tex,
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


def _editor_compile(request, worksheet, tex, doc_id, filename, collect,
                    on_success=None):
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
    if on_success:
        on_success()
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
    variant = request.POST.get('variant', WorksheetPdf.VARIANT_STUDENT)
    if variant not in dict(WorksheetPdf.VARIANT_CHOICES):
        raise Http404
    tex = request.POST.get('tex', '')

    def remember_student_options():
        if variant != WorksheetPdf.VARIANT_STUDENT:
            return
        from .latex import pdf_options_from_tex
        worksheet.student_pdf_options = pdf_options_from_tex(tex)
        worksheet.save(update_fields=['student_pdf_options'])

    return _editor_compile(
        request, worksheet, tex,
        doc_id=f'ws{worksheet.pk}-editor',
        filename=worksheet.pdf_filename(variant),
        collect=lambda: collect_assets(worksheet),
        on_success=remember_student_options)


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
        collect=lambda: collect_beamer_assets(worksheet))


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
    link.save(update_fields=['is_active'])
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'is_active': link.is_active})
    return redirect('worksheet_detail', pk=pk)


@teacher_required
@require_POST
def share_comment(request, pk, link_id):
    """Личная заметка учителя, не выводится на публичной странице."""
    worksheet = _own_worksheet(request, pk)
    link = get_object_or_404(ShareLink, pk=link_id, worksheet=worksheet)
    comment = request.POST.get('comment', '').strip()
    if len(comment) > 500:
        return _builder_response(request, pk, ok=False,
                                 message='Комментарий должен быть не длиннее 500 символов.')
    link.comment = comment
    link.save(update_fields=['comment'])
    return _builder_response(request, pk, message='Комментарий сохранён.')


@teacher_required
@require_http_methods(['GET', 'POST'])
def worksheet_recipient_visibility(request, pk, kind, recipient_id):
    """Настройки ссылки, ученика или группы получателей листка."""
    from .recipients import assignment_sections, visibility_options
    from assignments.views import _set_assignment_status
    from assignments.forms import AssignmentSettingsForm

    worksheet = _own_worksheet(request, pk)
    members = []
    if kind == 'all':
        members = list(worksheet.assignments.select_related('student').prefetch_related('source_groups'))
        if not members:
            raise Http404
        recipient = members[0]
        label = 'Все ученики'
    elif kind == 'link':
        recipient = get_object_or_404(worksheet.share_links, pk=recipient_id)
        label = recipient.comment or f'Ссылка от {recipient.created_at:%d.%m.%Y %H:%M}'
    elif kind == 'assignment':
        recipient = get_object_or_404(worksheet.assignments.select_related('student'), pk=recipient_id)
        label = recipient.student.get_full_name() or recipient.student.username
    elif kind == 'group':
        assignments = list(worksheet.assignments.select_related('student').prefetch_related('source_groups'))
        groups = StudentGroup.visible_to(request.user).prefetch_related('students')
        sections, _ = assignment_sections(assignments, groups)
        section = next((section for section in sections if section['group'].pk == recipient_id), None)
        if section is None:
            raise Http404
        members = section['assignments']
        recipient = members[0]
        label = section['group'].name
    else:
        raise Http404
    targets = members or [recipient]
    settings_form = AssignmentSettingsForm(
        request.POST if request.method == 'POST' and 'settings_present' in request.POST else None,
        recipients=targets, whole_worksheet=kind == 'all') if kind != 'link' else None
    sections = []
    if kind == 'all':
        sections, _ = assignment_sections(members, StudentGroup.visible_to(request.user).prefetch_related('students'))
    options = visibility_options(worksheet, recipient)
    if members:
        hidden_sets = [set(a.hidden_items.values_list('pk', flat=True)) for a in members]
        for option in options:
            states = [not (set(option['item_ids']) & hidden) for hidden in hidden_sets]
            option['visible'] = all(states)
            option['mixed'] = any(states) and not all(states)
    if request.method == 'POST':
        selected = set(request.POST.getlist('visible_items'))
        preserved = set(request.POST.getlist('unchanged_items')) if members else set()
        allowed = {str(option['value']) for option in options}
        if not (selected | preserved) <= allowed or selected & preserved:
            return _builder_response(request, pk, ok=False,
                                     message='Состав листка изменился. Откройте настройки заново.')
        active_ids = {item_id for option in options if str(option['value']) not in preserved
                      for item_id in option['item_ids']}
        hidden_ids = {item_id for option in options if str(option['value']) not in (selected | preserved)
                      for item_id in option['item_ids']}
        status = request.POST.get('status') if kind == 'assignment' else None
        if status is not None and status not in dict(Assignment.STATUS_CHOICES):
            return _builder_response(request, pk, ok=False, message='Неизвестный статус работы.')
        if settings_form and settings_form.is_bound and not settings_form.is_valid():
            return _builder_response(request, pk, ok=False,
                                     message=' '.join(str(error) for errors in settings_form.errors.values() for error in errors))
        with transaction.atomic():
            if status is not None:
                recipient = Assignment.objects.select_for_update().get(pk=recipient.pk)
                if not _set_assignment_status(recipient, status):
                    return _builder_response(request, pk, ok=False,
                                             message='Проверенной можно отметить только отправленную работу.')
            if settings_form and settings_form.is_bound:
                changes = settings_form.changes()
                if changes:
                    worksheet.assignments.filter(pk__in=[a.pk for a in targets]).update(**changes)
                    for target in targets:
                        livefiles.touch_assignment(target.pk, worksheet.pk, target.student_id)
            for target in targets:
                target.hidden_items.remove(*active_ids)
                target.hidden_items.add(*hidden_ids)
        return _builder_response(request, pk, message='Настройки сохранены.')
    return render(request, 'worksheets/_recipient_visibility.html', {
        'recipient_label': label, 'options': options, 'action': request.path,
        'assignment': recipient if kind == 'assignment' else None,
        'members': members, 'worksheet': worksheet, 'settings_form': settings_form,
        'recipient_groups': sections, 'whole_worksheet': kind == 'all',
        'status_choices': Assignment.STATUS_CHOICES,
    })


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

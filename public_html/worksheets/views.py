from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from django.utils.dateparse import parse_date

from accounts.decorators import get_role, teacher_required
from accounts.models import Profile
from problems.models import Task, Topic, topic_tree
from problems.views import filter_tasks

from .forms import WorksheetForm
from .import_tex import (TexImportError, create_worksheet,
                         match_existing_tasks, parse_tex)
from .latex import worksheet_to_tex
from .models import ShareLink, Worksheet, WorksheetItem, WorksheetPdf
from .services import LatexCompileError, get_worksheet_pdf


def _own_worksheet(request, pk):
    return get_object_or_404(Worksheet, pk=pk, owner=request.user)


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
    worksheets = (Worksheet.objects.filter(owner=request.user)
                  .prefetch_related('topics')
                  .annotate(items_total=models.Count('items', distinct=True)))

    grade = params.get('grade')
    if grade and grade.isdigit():
        worksheets = worksheets.filter(grade=grade)

    current_topic = None
    if params.get('topic'):
        current_topic = Topic.objects.filter(pk=params['topic']).first()
    if current_topic:
        # Тема указана у листка ИЛИ у любой его задачи
        ids = current_topic.descendants_ids()
        worksheets = worksheets.filter(
            models.Q(topics__in=ids)
            | models.Q(items__task__topics__in=ids)).distinct()

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

    return render(request, 'worksheets/worksheet_list.html', {
        'worksheets': worksheets,
        'params': params,
        'order': order,
        'grade_choices': Task.GRADE_CHOICES,
        'topics': topic_tree(),
        'current_topic': current_topic,
    })


def _import_overrides(post, parsed):
    """Назначения задачам из предпросмотра импорта: класс/тема/звёзды/ответ."""
    overrides = {}
    valid_grades = {str(g) for g, _ in Task.GRADE_CHOICES}
    # Только реально существующие темы: поддельный или устаревший id
    # иначе уронит task.topics.add() уже после создания части объектов
    valid_topics = set(Topic.objects.values_list('pk', flat=True))
    for i, (kind, data) in enumerate(parsed['elements']):
        if kind != 'task':
            continue
        extra = {}
        grade = post.get(f'grade_{i}', '').strip()
        if grade in valid_grades:
            extra['grade_level'] = int(grade)
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
    }
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
                    reverse('task_edit', args=[row['task'].pk]),
                    row['task'].pk, ', '.join(row['files'])))
            return redirect('worksheet_detail', pk=worksheet.pk)

        matches = match_existing_tasks(parsed)
        rows = []
        for (kind, data), match in zip(parsed['elements'], matches):
            rows.append({'kind': kind, 'data': data, 'existing_id': match})
        context['preview'] = {
            'header': parsed['header'],
            'rows': rows,
            'new_tasks': sum(1 for r in rows
                             if r['kind'] == 'task' and not r['existing_id']),
        }
    return render(request, 'worksheets/import.html', context)


@teacher_required
def worksheet_create(request):
    if request.method == 'POST':
        form = WorksheetForm(request.POST)
        if form.is_valid():
            worksheet = form.save(commit=False)
            worksheet.owner = request.user
            worksheet.save()
            messages.success(request, 'Листок создан. Добавьте в него задачи.')
            return redirect('worksheet_detail', pk=worksheet.pk)
    else:
        form = WorksheetForm()
    return render(request, 'worksheets/worksheet_form.html', {'form': form})


@teacher_required
def worksheet_edit(request, pk):
    worksheet = _own_worksheet(request, pk)
    if request.method == 'POST':
        form = WorksheetForm(request.POST, instance=worksheet)
        if form.is_valid():
            form.save()
            messages.success(request, 'Листок сохранён.')
            return redirect('worksheet_detail', pk=worksheet.pk)
    else:
        form = WorksheetForm(instance=worksheet)
    return render(request, 'worksheets/worksheet_form.html', {
        'form': form, 'worksheet': worksheet,
    })


@teacher_required
def worksheet_detail(request, pk):
    """Конструктор листка: задачи, поиск по базе, назначение, ссылки."""
    worksheet = _own_worksheet(request, pk)
    items = list(worksheet.ordered_items())
    task_ids = [item.task_id for item in items if item.task_id]

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
        })

    # Поиск задач для добавления (правая часть страницы)
    search_active = any(request.GET.get(k) for k in ('q', 'topic', 'grade', 'tag'))
    found_tasks = []
    if search_active:
        found_tasks = filter_tasks(request.GET).exclude(pk__in=task_ids)[:15]

    student_profiles = (Profile.objects
                        .filter(teacher=request.user, role=Profile.ROLE_STUDENT)
                        .select_related('user')
                        .order_by('user__last_name'))
    assigned_ids = set(
        worksheet.assignments.values_list('student_id', flat=True))
    groups = request.user.owned_groups.prefetch_related('students')

    return render(request, 'worksheets/worksheet_detail.html', {
        'worksheet': worksheet,
        'items': items,
        'rows': rows,
        'found_tasks': found_tasks,
        'search_active': search_active,
        'params': request.GET,
        'student_profiles': student_profiles,
        'assigned_ids': assigned_ids,
        'groups': groups,
        'stars_choices': Task.STARS_CHOICES,
        'grade_choices': Task.GRADE_CHOICES,
        'share_links': worksheet.share_links.order_by('-created_at'),
        'assignments': worksheet.assignments.select_related('student'),
    })


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
    worksheet.save()
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
        grade = request.POST['grade'].strip()
        if grade in {str(g) for g, _ in Task.GRADE_CHOICES}:
            copy.grade = int(grade)
        elif not grade:
            copy.grade = None
    copy.save()
    copy.topics.set(worksheet.topics.all())
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
def worksheet_quick_update(request, pk):
    """Горячее редактирование из списка листков: класс и темы.

    Меняет только присланные поля. Темы приходят из popup-диалога:
    маркер topics_submitted отличает «снять все темы» от «тем не присылали».
    """
    worksheet = _own_worksheet(request, pk)
    if 'grade' in request.POST:
        value = request.POST['grade'].strip()
        if value and value not in {str(g) for g, _ in Task.GRADE_CHOICES}:
            return _builder_response(
                request, pk, ok=False, message='Недопустимый класс')
        worksheet.grade = int(value) if value else None
        worksheet.save(update_fields=['grade', 'updated_at'])
    if 'grade_label' in request.POST:
        worksheet.grade_label = request.POST['grade_label'].strip()[:100]
        worksheet.save(update_fields=['grade_label', 'updated_at'])
    if request.POST.get('topics_submitted'):
        ids = [t for t in request.POST.getlist('topics') if t.isdigit()]
        worksheet.topics.set(Topic.objects.filter(pk__in=ids))
        # M2M-операции не трогают auto_now — обновляем дату явно
        worksheet.save(update_fields=['updated_at'])
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    messages.success(request, f'Листок «{worksheet.title}» обновлён.')
    return redirect('worksheet_list')


def add_task_to_worksheet(request, worksheet_id, task):
    """Добавляет задачу в конец листка (используется и из создания задачи)."""
    worksheet = get_object_or_404(
        Worksheet, pk=worksheet_id, owner=request.user)
    last = worksheet.items.aggregate(m=models.Max('order'))['m'] or 0
    WorksheetItem.objects.create(
        worksheet=worksheet, task=task, order=last + 10)
    messages.success(request, f'Задача #{task.pk} добавлена в «{worksheet.title}».')
    return redirect('worksheet_detail', pk=worksheet.pk)


@teacher_required
@require_POST
def worksheet_add_task(request, pk):
    task = get_object_or_404(Task, pk=request.POST.get('task_id'))
    return add_task_to_worksheet(request, pk, task)


@teacher_required
@require_POST
def worksheet_remove_item(request, pk, item_id):
    worksheet = _own_worksheet(request, pk)
    item = get_object_or_404(WorksheetItem, pk=item_id, worksheet=worksheet)
    item.delete()
    messages.success(request, 'Элемент убран из листка.')
    return redirect('worksheet_detail', pk=pk)


@teacher_required
@require_POST
def worksheet_move_item(request, pk, item_id, direction):
    worksheet = _own_worksheet(request, pk)
    items = list(worksheet.ordered_items())
    idx = next((i for i, it in enumerate(items) if it.pk == item_id), None)
    if idx is None:
        raise Http404
    other = idx - 1 if direction == 'up' else idx + 1
    if 0 <= other < len(items):
        items[idx].order, items[other].order = items[other].order, items[idx].order
        # Совпадающие order (например, все 0) — перенумеруем целиком
        if items[idx].order == items[other].order:
            items[idx], items[other] = items[other], items[idx]
            for i, it in enumerate(items):
                it.order = (i + 1) * 10
            WorksheetItem.objects.bulk_update(items, ['order'])
        else:
            WorksheetItem.objects.bulk_update(
                [items[idx], items[other]], ['order'])
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
    items = {i.pk: i for i in worksheet.items.all()}
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
    item.save()
    return _builder_response(request, pk, message='Текст сохранён.')


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


def _worksheet_pdf_response(worksheet, variant):
    pdf = get_worksheet_pdf(worksheet, variant)
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
    is_owner = worksheet.owner_id == request.user.pk
    is_assigned_student = (
        role == Profile.ROLE_STUDENT
        and worksheet.assignments.filter(student=request.user).exists())
    if not (is_owner or (is_assigned_student
                         and variant == WorksheetPdf.VARIANT_STUDENT)):
        raise PermissionDenied

    try:
        return _worksheet_pdf_response(worksheet, variant)
    except LatexCompileError as exc:
        if not is_owner:
            raise Http404
        return render(request, 'worksheets/latex_error.html', {
            'worksheet': worksheet,
            'error': exc,
            'tex': worksheet_to_tex(worksheet, variant),
        }, status=502)


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

def _shared_worksheet(token):
    link = ShareLink.objects.filter(token=token, is_active=True).first()
    if link is None:
        raise Http404
    return link.worksheet


def public_worksheet(request, token):
    worksheet = _shared_worksheet(token)
    rows = []
    number = 0
    for item in worksheet.ordered_items():
        if item.task_id:
            number += 1
        rows.append({
            'item': item,
            'number': number if item.task_id else None,
            'subitems': item.selected_subitems(),
        })
    return render(request, 'worksheets/public.html', {
        'worksheet': worksheet,
        'rows': rows,
        'token': token,
        # Публичная страница — только просмотр: без контекстной панели
        'minimal_page': True,
    })


def public_worksheet_pdf(request, token):
    worksheet = _shared_worksheet(token)
    try:
        return _worksheet_pdf_response(worksheet, WorksheetPdf.VARIANT_STUDENT)
    except LatexCompileError:
        raise Http404

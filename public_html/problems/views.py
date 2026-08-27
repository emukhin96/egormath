import json
import re

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required

from .forms import (TaskForm, TaskImageFormSet, TaskSourceFormSet,
                    TaskSubitemFormSet, TextbookBundleUploadForm,
                    TextbookDraftReviewForm)
from .models import (Source, Tag, Task, TaskImage, TaskSource, TaskSubitem,
                     TextbookImportBatch, TextbookTaskDraft, Topic,
                     topic_tree)
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
                               'source_refs__source', 'subitems')
             .select_related('created_by'))
    q = params.get('q', '').strip()
    if q:
        tasks = tasks.filter(
            Q(text_plain__icontains=q) | Q(text_latex__icontains=q))
    tasks = filter_by_taxonomy(tasks, params, topics_lookups=('topics',))
    tag = params.get('tag')
    if tag:
        tasks = tasks.filter(tags__name=tag)
    return tasks


@teacher_required
def task_list(request):
    tasks = filter_tasks(request.GET)
    paginator = Paginator(tasks, 25)
    page = paginator.get_page(request.GET.get('page'))
    blocks = Topic.objects.filter(parent=None)
    ctx = taxonomy_page_context(filter_state_from_params(request.GET))
    ctx.update({
        'page': page,
        'topics': blocks,
        'topics_flat': topic_tree(),
        'sources': Source.objects.all(),
        'params': request.GET,
        'grade_choices': Task.GRADE_CHOICES,
    })
    for task in page:
        task.taxonomy_json = dumps_state(task_taxonomy_state(task))
    return render(request, 'problems/task_list.html', ctx)


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
            if task.worksheet_items.exists() or task.submissions.exists():
                blocked += 1
                continue
            task.delete()
            deleted += 1
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
    task = get_object_or_404(
        Task.objects.prefetch_related('topics', 'tags', 'source_refs__source'),
        pk=pk)
    ctx = taxonomy_page_context(task_taxonomy_state(task))
    ctx.update({
        'task': task,
        'grade_choices': Task.GRADE_CHOICES,
        'stars_choices': Task.STARS_CHOICES,
        'topics': topic_tree(),
        'tags_value': ', '.join(t.name for t in task.tags.all()),
    })
    return render(request, 'problems/task_detail.html', ctx)


@teacher_required
def task_create(request):
    return _task_form(request, task=None)


@teacher_required
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk)
    return _task_form(request, task=task)


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


def _save_local_variant(user, original, form, source_fs, subitem_fs, post):
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
    for data in subitem_fs.cleaned_data:
        if not data or data.get('DELETE') or not data.get('text_latex'):
            continue
        TaskSubitem.objects.create(
            task=variant, order=data.get('order') or 0,
            text_latex=data['text_latex'],
            answer_latex=data.get('answer_latex') or '',
            solution_latex=data.get('solution_latex') or '')
    for data in source_fs.cleaned_data:
        if not data or data.get('DELETE') or not data.get('source'):
            continue
        TaskSource.objects.create(
            task=variant, source=data['source'],
            number=data.get('number') or '')
    # Картинки: копия ссылается на те же файлы, что у оригинала
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
        'answer_type': prev.answer_type,
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
        form = TaskForm(request.POST, instance=task)
        source_fs = TaskSourceFormSet(
            request.POST, instance=task or form.instance)
        subitem_fs = TaskSubitemFormSet(
            request.POST, instance=task or form.instance)
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
                    })
                    return render(request, 'problems/task_form.html', ctx)
            if save_local:
                variant = _save_local_variant(
                    request.user, task, form, source_fs, subitem_fs,
                    request.POST)
                item.task = variant
                # Выбор подпунктов ссылался на подпункты оригинала — сброс
                item.all_subitems = True
                item.save()
                item.subitems.clear()
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


@teacher_required
def textbook_import_list(request):
    batches = TextbookImportBatch.objects.all()
    if not request.user.is_superuser:
        batches = batches.filter(created_by=request.user)
    batches = (batches.select_related('source', 'created_by')
               .annotate(total=Count('drafts')))
    return render(request, 'problems/textbook_import_list.html', {
        'batches': batches,
    })


@teacher_required
def textbook_import_upload(request):
    from .textbook_import import (TextbookImportError,
                                  create_batch_from_bundle, read_bundle)
    if request.method == 'POST':
        form = TextbookBundleUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                payload = read_bundle(form.cleaned_data['bundle'])
                batch = create_batch_from_bundle(
                    payload, user=request.user,
                    title=form.cleaned_data['title'],
                    source_title=form.cleaned_data['source_title'],
                    source_author=form.cleaned_data['source_author'],
                    source_year=form.cleaned_data['source_year'])
            except TextbookImportError as exc:
                form.add_error('bundle', str(exc))
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
    status = request.GET.get('status', '')
    drafts = batch.drafts.select_related('topic', 'imported_task')
    if status in dict(TextbookTaskDraft.STATUS_CHOICES):
        drafts = drafts.filter(status=status)
    paginator = Paginator(drafts, 50)
    page = paginator.get_page(request.GET.get('page'))
    counts = dict(batch.drafts.values_list('status').annotate(n=Count('pk')))
    status_tabs = [
        {'value': value, 'label': label, 'count': counts.get(value, 0)}
        for value, label in TextbookTaskDraft.STATUS_CHOICES
    ]
    return render(request, 'problems/textbook_import_detail.html', {
        'batch': batch,
        'page': page,
        'counts': counts,
        'status': status,
        'status_tabs': status_tabs,
    })


@teacher_required
def textbook_import_review(request, batch_pk, pk):
    batch = _own_import_batch(request, batch_pk)
    draft = get_object_or_404(
        TextbookTaskDraft.objects.select_related('topic'),
        batch=batch, pk=pk)
    if request.method == 'POST':
        form = TextbookDraftReviewForm(request.POST, instance=draft)
        if form.is_valid():
            updated = form.save(commit=False)
            source_key = form.cleaned_data.get('copy_solution_from', '').strip()
            if source_key:
                candidate = batch.drafts.filter(external_id=source_key).first()
                if candidate is None:
                    form.add_error(
                        'copy_solution_from', 'В этой партии такого ключа нет.')
                else:
                    used = (batch.drafts
                            .exclude(pk=draft.pk)
                            .filter(solution_source_external_id=source_key,
                                    status=TextbookTaskDraft.STATUS_APPROVED)
                            .first())
                    if used:
                        form.add_error(
                            'copy_solution_from',
                            f'Решение уже одобрено для {used.external_id}.')
                    else:
                        updated.author_answer_latex = \
                            candidate.author_answer_latex
                        updated.author_solution_latex = \
                            candidate.author_solution_latex
                        updated.solution_source_external_id = source_key
            if not form.errors:
                updated.reviewed_by = request.user
                updated.reviewed_at = timezone.now()
                updated.save()
                messages.success(request, f'{updated.external_id}: сохранено.')
                next_draft = (batch.drafts
                              .filter(external_id__gt=updated.external_id)
                              .order_by('external_id', 'pk').first())
                if request.POST.get('save_next') and next_draft:
                    return redirect(
                        'textbook_import_review', batch_pk=batch.pk,
                        pk=next_draft.pk)
                return redirect('textbook_import_detail', pk=batch.pk)
    else:
        solution_key = draft.solution_source_external_id
        if solution_key == draft.external_id:
            solution_key = ''
        form = TextbookDraftReviewForm(
            instance=draft,
            initial={'copy_solution_from': solution_key})
    previous = (batch.drafts.filter(external_id__lt=draft.external_id)
                .order_by('-external_id', '-pk').first())
    following = (batch.drafts.filter(external_id__gt=draft.external_id)
                 .order_by('external_id', 'pk').first())
    candidates = (batch.drafts.exclude(pk=draft.pk)
                  .exclude(author_solution_latex='')
                  .order_by('external_id')[:12])
    return render(request, 'problems/textbook_import_review.html', {
        'batch': batch,
        'draft': draft,
        'form': form,
        'previous': previous,
        'following': following,
        'candidates': candidates,
    })


@teacher_required
@require_POST
def textbook_import_approve_clean(request, pk):
    batch = _own_import_batch(request, pk)
    drafts = list(batch.drafts.filter(
        status=TextbookTaskDraft.STATUS_REVIEW))
    approved = []
    now = timezone.now()
    for draft in drafts:
        if not draft.warnings and draft.confidence == 1 and draft.topic_id:
            draft.status = TextbookTaskDraft.STATUS_APPROVED
            draft.reviewed_by = request.user
            draft.reviewed_at = now
            approved.append(draft)
    TextbookTaskDraft.objects.bulk_update(
        approved, ['status', 'reviewed_by', 'reviewed_at'])
    messages.success(request, f'Автоматически одобрено: {len(approved)}.')
    return redirect('textbook_import_detail', pk=batch.pk)


@teacher_required
@require_POST
def textbook_import_commit(request, pk):
    from .textbook_import import TextbookImportError, commit_batch
    batch = _own_import_batch(request, pk)
    try:
        result = commit_batch(batch, user=request.user)
    except TextbookImportError as exc:
        messages.error(request, str(exc))
        return redirect('textbook_import_detail', pk=batch.pk)
    messages.success(
        request,
        'Импорт завершён: создано задач — %(created)s, '
        'переиспользовано — %(reused)s, новых подборок — %(collections)s.'
        % result)
    return redirect('collection_list')

import re

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin

from accounts.decorators import teacher_required

from .forms import (TaskForm, TaskImageFormSet, TaskSourceFormSet,
                    TaskSubitemFormSet)
from .models import (Source, Tag, Task, TaskImage, TaskSource, TaskSubitem,
                     Topic)


def filter_tasks(params):
    """Каталог задач по GET-параметрам: q, topic, grade, tag.

    «Локальные» копии задач (варианты для конкретного листка)
    в каталоге не показываются.
    """
    tasks = (Task.objects.filter(variant_of__isnull=True)
             .prefetch_related('topics', 'tags', 'source_refs__source',
                               'subitems')
             .select_related('created_by'))
    q = params.get('q', '').strip()
    if q:
        tasks = tasks.filter(
            Q(text_plain__icontains=q) | Q(text_latex__icontains=q))
    topic_id = params.get('topic')
    if topic_id:
        try:
            topic = Topic.objects.get(pk=topic_id)
            tasks = tasks.filter(topics__in=topic.descendants_ids()).distinct()
        except (Topic.DoesNotExist, ValueError):
            pass
    grade = params.get('grade')
    if grade:
        tasks = tasks.filter(grade_level=grade)
    tag = params.get('tag')
    if tag:
        tasks = tasks.filter(tags__name=tag)
    return tasks


@teacher_required
def task_list(request):
    tasks = filter_tasks(request.GET)
    paginator = Paginator(tasks, 25)
    page = paginator.get_page(request.GET.get('page'))
    topics = Topic.objects.filter(parent=None).prefetch_related('children')
    current_topic = None
    if request.GET.get('topic'):
        current_topic = Topic.objects.filter(pk=request.GET['topic']).first()
    return render(request, 'problems/task_list.html', {
        'page': page,
        'topics': topics,
        'tags': Tag.objects.all(),
        'sources': Source.objects.all(),
        'current_topic': current_topic,
        'params': request.GET,
        'grade_choices': Task.GRADE_CHOICES,
    })


@teacher_required
def task_quick_update(request, pk):
    """Горячее редактирование из списка задач: класс, ответ, источник.

    Меняет только присланные поля; отвечает JSON для fetch-автосохранения.
    Источник — первый TaskSource задачи (создаётся/обновляется/удаляется).
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'message': 'Только POST'}, status=405)
    task = get_object_or_404(Task, pk=pk)
    if 'grade_level' in request.POST:
        value = request.POST['grade_level'].strip()
        if value and value not in {str(g) for g, _ in Task.GRADE_CHOICES}:
            return JsonResponse(
                {'ok': False, 'message': 'Недопустимый класс'}, status=400)
        task.grade_level = int(value) if value else None
    if 'answer_latex' in request.POST:
        task.answer_latex = request.POST['answer_latex'].strip()
    task.save()
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
    return JsonResponse({'ok': True})


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
    return render(request, 'problems/task_detail.html', {'task': task})


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


def _save_local_variant(user, original, form, source_fs, subitem_fs):
    """Создаёт скрытую копию задачи с данными из провалидированных форм.

    Оригинал в базе не меняется; копия помечена variant_of и не видна
    в каталоге.
    """
    variant = Task.objects.get(pk=original.pk)
    variant.pk = None
    variant.variant_of = original.variant_of or original
    variant.created_by = user
    for name, value in form.cleaned_data.items():
        if name in ('topics', 'tags'):
            continue
        setattr(variant, name, value)
    variant.save()
    variant.topics.set(form.cleaned_data['topics'])
    variant.tags.set(form.cleaned_data['tags'])
    for data in subitem_fs.cleaned_data:
        if not data or data.get('DELETE') or not data.get('text_latex'):
            continue
        TaskSubitem.objects.create(
            task=variant, order=data.get('order') or 0,
            text_latex=data['text_latex'],
            answer_latex=data.get('answer_latex') or '')
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
        'answer_type': prev.answer_type,
        'columns': prev.columns,
        'topics': list(prev.topics.values_list('pk', flat=True)),
        'tags': list(prev.tags.values_list('pk', flat=True)),
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
            # Дедупликация: не создавать вторую задачу с тем же условием
            if task is None and 'force_create' not in request.POST:
                from worksheets.import_tex import find_existing_task
                duplicate_pk = find_existing_task(
                    form.cleaned_data['text_latex'])
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
                    return render(request, 'problems/task_form.html', {
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
            if save_local:
                variant = _save_local_variant(
                    request.user, task, form, source_fs, subitem_fs)
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
    return render(request, 'problems/task_form.html', {
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

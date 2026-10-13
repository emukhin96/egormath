"""Быстрый клон задачи: диалог «Клон», сохранение и предпросмотр.

Клон — каталожная задача (``make_variant(standalone=True)``) без номера
задачника: строки ``TaskSource`` удаляются, связь с исходной хранится
в семействе аналогов (``Family``). Контекст вызова:

* ``worksheet`` + ``item`` — клон встаёт в листок сразу после пункта;
* ``position`` — клон становится кандидатом номера самостоятельной;
* без контекста — просто новая задача в базе.
"""
import json

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.validators import FileExtensionValidator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required

from .clone_numbers import (follow_mask, mask_follows_answer, mask_numbers,
                            split_numbers)
from .forms import clean_mask_text
from .models import Task, TaskImage
from .task_images import TASKPIC_NUM_RE, taskpic_indices

IMAGE_ACTIONS = ('keep', 'replace', 'remove')
TEXT_FIELDS = ('text_latex', 'answer_latex', 'solution_latex',
               'author_answer_latex', 'author_solution_latex')


class CloneError(Exception):
    pass


def _position_number(position):
    """Номер позиции, как на странице подбора (пояснения не нумеруются)."""
    rows = position.work.positions.filter(
        Q(text='') | Q(candidates__isnull=False)).distinct()
    for number, row in enumerate(rows, 1):
        if row.pk == position.pk:
            return number
    return None


def resolve_context(request, task):
    """``(item, position)`` из параметров запроса с проверкой прав."""
    from .editor import worksheet_context
    item = worksheet_context(request, task)
    if item is not None and item.deleted_at:
        raise Http404
    position = None
    position_id = request.GET.get('position') or request.POST.get('position')
    if position_id:
        if item is not None or not getattr(settings, 'INDEPENDENT_WORKS_ENABLED', False):
            raise Http404
        from independentworks.models import Position, Work
        position = get_object_or_404(
            Position.objects.select_related('work'), pk=position_id,
            work__in=Work.visible_to(request.user))
        # Локальная копия годится как исходная, только если уже в этом номере
        if task.variant_of_id and not position.candidates.filter(task=task).exists():
            raise Http404
    return item, position


def source_label(task):
    ref = task.source_refs.select_related('source').first()
    if ref is None:
        return ''
    return f'{ref.source}, №{ref.number}' if ref.number else str(ref.source)


def _owner_data(owner, key, title):
    answer = owner.effective_answer_latex
    mask = owner.answer_mask or ''
    follows = mask_follows_answer(mask, answer)
    return {
        'key': key,
        'title': title,
        'text': owner.text_latex,
        'segments': split_numbers(owner.text_latex),
        'answer': answer,
        'answer_source': 'author' if (owner.author_answer_latex or '').strip() else 'editor',
        'mask': mask,
        'mask_follows': follows,
        'mask_slots': json.dumps([[start, end] for start, end, _ in mask_numbers(mask)]
                                 if follows else []),
        'has_solution': bool(owner.effective_solution_latex),
    }


def owners(task):
    """Условие задачи и подпункты: текст, ответ, маска для диалога."""
    from worksheets.latex import subitem_label
    subs = list(task.subitems.all())
    rows = [_owner_data(task, 'task', 'Условие')]
    # У задачи с подпунктами общий ответ бывает редко — поле только при нём
    rows[0]['answer_block'] = not subs or bool(rows[0]['answer'] or rows[0]['mask'])
    for index, sub in enumerate(subs):
        row = _owner_data(sub, f'sub-{sub.pk}', f'Подпункт {subitem_label(index)})')
        row['answer_block'] = True
        rows.append(row)
    return rows


def images(task):
    referenced = set(taskpic_indices(task.text_latex))
    for sub in task.subitems.all():
        referenced.update(taskpic_indices(sub.text_latex))
    return [{'image': image, 'number': index + 1, 'referenced': index in referenced}
            for index, image in enumerate(task.images.all())]


def dialog_context(request, task, item, position):
    if item is not None:
        target = f'Добавится в листок «{item.worksheet.title}» после задачи #{task.pk}'
        note = 'Сохранится как новая задача в базе и встанет в листок следующей строкой.'
    elif position is not None:
        number = _position_number(position)
        target = f'Добавится вариантом в №{number} · {position.work.title}' if number else \
            f'Добавится вариантом в «{position.work.title}»'
        note = 'Сохранится как новая задача в базе, связанная с исходной как аналог.'
    else:
        target = 'Новая задача в базе'
        note = 'Сохранится как новая задача в базе, связанная с исходной как аналог.'
    rows = owners(task)
    return {
        'task': task, 'item': item, 'position': position,
        'source_label': source_label(task), 'target': target, 'note': note,
        'owners': rows, 'images': images(task),
        'has_solution': any(row['has_solution'] for row in rows),
        'blocked': bool(task.block_id),
        'preview_html': preview_html(task.text_latex, [
            sub.text_latex for sub in task.subitems.all()]),
    }


def preview_html(text, subtexts):
    return render_to_string('problems/_clone_preview.html', {
        'text': text, 'subitems': [{'text_latex': t} for t in subtexts]})


def _renumber_taskpics(copy, numbering):
    """Ссылки ``\\taskpic{N}`` после удаления рисунков: удалённые — убрать,
    остальные — новый номер по порядку."""
    def fix(match):
        new = numbering.get(int(match.group(1)))
        return '' if new is None else f'\\taskpic{{{new}}}'

    for owner in [copy, *copy.subitems.all()]:
        changed = []
        for field in TEXT_FIELDS:
            value = getattr(owner, field, None)
            if value and TASKPIC_NUM_RE.search(value):
                setattr(owner, field, TASKPIC_NUM_RE.sub(fix, value))
                changed.append(field)
        if changed:
            owner.save(update_fields=changed)


def _validated_image(upload):
    if upload is None:
        raise CloneError('Выберите файл для замены рисунка.')
    try:
        FileExtensionValidator(['png', 'jpg', 'jpeg', 'pdf'])(upload)
    except forms.ValidationError:
        raise CloneError('Рисунок — файл PNG, JPEG или PDF.')
    return upload


def read_post(request, task):
    """Разбор формы диалога до создания копии: тексты, ответы, маски, рисунки."""
    data = request.POST
    plan = {'owners': {}, 'images': {}}
    for row in owners(task):
        key = row['key']
        values = {}
        text = data.get(f'{key}-text', row['text'])
        if not text.strip():
            raise CloneError(f'{row["title"]}: текст не может быть пустым.')
        values['text'] = text
        if row['answer_block']:
            answer = data.get(f'{key}-answer', row['answer']).strip()
            mask = None
            if data.get(f'{key}-mask_follow') == '1':
                mask = follow_mask(row['mask'], row['answer'], answer)
            if mask is None:
                mask = data.get(f'{key}-mask', row['mask'])
            try:
                mask = clean_mask_text(mask)
            except forms.ValidationError as exc:
                label = 'Маска' if key == 'task' else f'Маска ({row["title"].lower()})'
                raise CloneError(f'{label}: ' + '; '.join(exc.messages))
            values.update(answer=answer, mask=mask)
        plan['owners'][key] = values
    for entry in images(task):
        image = entry['image']
        action = data.get(f'image-{image.pk}', 'keep')
        if action not in IMAGE_ACTIONS:
            raise CloneError('Неизвестное действие с рисунком.')
        upload = None
        if action == 'replace':
            upload = _validated_image(request.FILES.get(f'image-{image.pk}-file'))
        plan['images'][image.pk] = (action, upload)
    plan['keep_solution'] = data.get('keep_solution') == '1'
    return plan


def _apply_owner(original, clone, values, keep_solution):
    fields = []
    if 'text' in values:
        clone.text_latex = values['text']
        fields.append('text_latex')
    if 'answer' in values:
        if (original.author_answer_latex or '').strip():
            # Правим действующий (авторский) ответ; AI-версия устарела
            clone.author_answer_latex = values['answer']
            clone.answer_latex = ''
        else:
            clone.answer_latex = values['answer']
        clone.answer_mask = values['mask']
        fields += ['author_answer_latex', 'answer_latex', 'answer_mask']
    if not keep_solution:
        clone.solution_latex = clone.author_solution_latex = ''
        fields += ['solution_latex', 'author_solution_latex']
    if fields:
        clone.save(update_fields=fields)


def _apply_images(copy, mapping, plan):
    """Оставить / заменить / убрать; порядок остаётся согласован с \\taskpic."""
    clones = {img.pk: img for img in copy.images.all()}
    final, numbering, changed = [], {}, False
    # Нумерация \taskpic — по исходному порядку картинок
    for number, original in enumerate(TaskImage.objects.filter(
            pk__in=plan).order_by('order', 'id'), 1):
        action, upload = plan[original.pk]
        row = clones[mapping[original.pk]]
        if action == 'remove':
            row.delete()
            changed = True
            continue
        if action == 'replace':
            # Файл исходной не трогаем: строки картинок делят один файл
            new = TaskImage(task=copy, image=upload, order=row.order)
            try:
                new.save()
            except Exception:
                raise CloneError('Не удалось прочитать файл рисунка.')
            row.delete()
            row = new
            changed = True
        final.append(row)
        numbering[number] = len(final)
    if changed:
        for order, row in enumerate(final):
            if row.order != order:
                TaskImage.objects.filter(pk=row.pk).update(order=order)
        if len(final) < len(plan):
            _renumber_taskpics(copy, numbering)


def resolve_after(request, item):
    """«Сохранить и ещё клон»: следующий клон встаёт после предыдущего.
    ``after`` — строка того же листка; чужая или удалённая — 404."""
    after_id = request.POST.get('after')
    if item is None or not after_id:
        return None
    return get_object_or_404(item.worksheet.items, pk=after_id, deleted_at__isnull=True)


def create_clone(request, task, item, position, plan, after=None):
    """Создаёт клон по разобранной форме; вызывается внутри транзакции.
    Возвращает ``(copy, строка листка или None)``."""
    from independentworks.models import Family
    copy, mapping = task.make_variant(request.user, with_mapping=True, standalone=True)
    # Клон — не номер задачника: связь с исходной хранит семейство аналогов
    copy.source_refs.all().delete()
    row = None
    keep = plan['keep_solution']
    _apply_owner(task, copy, plan['owners']['task'], keep)
    clones = {sub.pk: sub for sub in copy.subitems.all()}
    for sub in task.subitems.all():
        _apply_owner(sub, clones[mapping['subitems'][sub.pk]],
                     plan['owners'][f'sub-{sub.pk}'], keep)
    if plan['images']:
        _apply_images(copy, mapping['images'], plan['images'])
    Family.link_analog(task, copy)
    if item is not None:
        from .editor import insert_after
        row = insert_after(item, copy, mapping, after)
    if position is not None:
        from independentworks import services as svc
        try:
            svc.add_candidate(position, copy)
        except svc.WorkError as error:
            raise CloneError(str(error))
    return copy, row


@teacher_required
def task_clone(request, pk):
    task = get_object_or_404(Task.objects.prefetch_related('subitems', 'images'), pk=pk)
    item, position = resolve_context(request, task)
    if request.method != 'POST':
        return render(request, 'problems/_clone_dialog.html',
                      dialog_context(request, task, item, position))
    if task.block_id:
        return JsonResponse({'ok': False, 'errors': [
            'Задача из общего блока: используйте «дублировать».']}, status=400)
    after = resolve_after(request, item)
    try:
        plan = read_post(request, task)
        with transaction.atomic():
            if item is not None:
                from worksheets.models import Worksheet
                Worksheet.objects.select_for_update().get(pk=item.worksheet_id)
            copy, row = create_clone(request, task, item, position, plan, after)
    except CloneError as error:
        return JsonResponse({'ok': False, 'errors': [str(error)]}, status=400)
    url = reverse('task_detail', args=[copy.pk])
    reload = item is not None or position is not None
    if item is not None:
        messages.success(request, f'Клон #{copy.pk} добавлен после задачи #{task.pk}.')
    elif position is not None:
        messages.success(request, f'Клон #{copy.pk} добавлен в номер.')
    return JsonResponse({'ok': True, 'task_id': copy.pk, 'url': url, 'reload': reload,
                         'item_id': row.pk if row else None,
                         'message': f'Клон #{copy.pk} сохранён'})


@teacher_required
@require_POST
def task_clone_preview(request, pk):
    """«Ученик увидит»: условие и подпункты клона в веб-разметке."""
    get_object_or_404(Task, pk=pk)
    return JsonResponse({'html': preview_html(
        request.POST.get('text', ''), request.POST.getlist('sub'))})


"""Аналоги в конструкторе листка: список у строки и быстрые действия.

Счётчик в строке ставит ``worksheet_detail`` (``attach_analog_counts``,
два запроса на листок), список подгружается по клику
(``worksheet_item_analogs``) — условия аналогов всех строк в конструктор
не грузим. «Заменить в листке» меняет задачу строки на месте: порядок,
звёзды листка, колонки и скрытие у получателей остаются; «Добавить после»
ставит аналог следующей строкой.
"""
from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from independentworks import analog_lists
from problems.models import Task
from .models import Worksheet, WorksheetItem


def _row(request, pk, item_id):
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=pk)
    item = get_object_or_404(WorksheetItem.objects.select_related('task', 'worksheet'),
                             pk=item_id, worksheet=worksheet, deleted_at__isnull=True,
                             task__isnull=False)
    return worksheet, item


def row_actions_context(item):
    """Кнопки «Заменить в листке» / «Добавить после» для строки ``item``:
    у вопросов общего блока их нет — блок переставляется только целиком."""
    if item.task.block_id:
        return {}
    worksheet = item.worksheet
    return {
        'analog_item': item,
        'analog_replace_url': reverse('worksheet_item_analog_replace', args=[worksheet.pk, item.pk]),
        'analog_after_url': reverse('worksheet_item_analog_after', args=[worksheet.pk, item.pk]),
        'analog_in_sheet': set(worksheet.items.filter(deleted_at__isnull=True)
                               .exclude(task=None).values_list('task_id', flat=True)),
        'analog_assigned': worksheet.assignments.exists(),
    }


@teacher_required
def worksheet_item_analogs(request, pk, item_id):
    """Фрагмент со списком аналогов строки (подгружает static/js/analogs.js)."""
    worksheet, item = _row(request, pk, item_id)
    analogs, total = analog_lists.analog_tasks(request.user, item.task)
    from assignments.task_usage import attach_usage
    attach_usage(request, analogs)
    ctx = {'analogs': analogs, 'analogs_total': total,
           'analogs_more': max(total - len(analogs), 0), 'task': item.task,
           'form_id': f'analogs-form-{item.pk}'}
    ctx.update(row_actions_context(item))
    return render(request, 'worksheets/_item_analogs.html', ctx)


def _chosen_analog(request, item):
    raw = request.POST.get('task', '')
    ids = analog_lists.analog_ids(request.user, [item.task]).get(item.task_id, [])
    if not raw.isdigit() or int(raw) not in ids:
        raise Http404
    return Task.objects.get(pk=int(raw))


def _back(worksheet, item):
    return redirect(reverse('worksheet_detail', args=[worksheet.pk]) + f'#ws-item-{item.pk}')


@teacher_required
@require_POST
def worksheet_item_analog_replace(request, pk, item_id):
    worksheet, item = _row(request, pk, item_id)
    if item.task.block_id:
        messages.error(request, 'Вопрос общего блока заменить нельзя.')
        return _back(worksheet, item)
    analog = _chosen_analog(request, item)
    with transaction.atomic():
        Worksheet.objects.select_for_update().get(pk=worksheet.pk)
        if worksheet.items.filter(task=analog, deleted_at__isnull=True).exists():
            messages.error(request, f'Задача #{analog.pk} уже есть в листке.')
            return _back(worksheet, item)
        # Как в «Добавить после»: мягко удалённая строка с той же задачей
        # иначе вернулась бы второй строкой по «Отменить».
        worksheet.items.filter(task=analog, deleted_at__isnull=False).delete()
        old = item.task
        # Звёзды листка остаются прежними, даже если у аналога другие.
        if item.stars_override is None and old.stars != analog.stars:
            item.stars_override = old.stars
        item.task = analog
        item.all_subitems = True
        item.save(update_fields=['task', 'stars_override', 'all_subitems'])
        item.subitems.clear()
    messages.success(request, f'Задача #{old.pk} заменена в листке на #{analog.pk}.')
    return _back(worksheet, item)


@teacher_required
@require_POST
def worksheet_item_analog_after(request, pk, item_id):
    worksheet, item = _row(request, pk, item_id)
    if item.task.block_id:
        messages.error(request, 'После вопроса общего блока аналог не добавляется.')
        return _back(worksheet, item)
    analog = _chosen_analog(request, item)
    with transaction.atomic():
        Worksheet.objects.select_for_update().get(pk=worksheet.pk)
        if worksheet.items.filter(task=analog, deleted_at__isnull=True).exists():
            messages.error(request, f'Задача #{analog.pk} уже есть в листке.')
            return _back(worksheet, item)
        # Мягко удалённая копия той же задачи иначе вернулась бы второй
        # строкой по «Отменить».
        worksheet.items.filter(task=analog, deleted_at__isnull=False).delete()
        rows = list(worksheet.items.order_by('order', 'pk'))
        insertion = None
        for position, row in enumerate(rows, 1):
            if row.order != position * 10:
                row.order = position * 10
                row.save(update_fields=['order'])
            if row.pk == item.pk:
                insertion = row.order + 5
        added = worksheet.items.create(task=analog, order=insertion,
                                       stars_override=item.stars_override)
    messages.success(request, f'Аналог #{analog.pk} добавлен после задачи #{item.task_id}.')
    return _back(worksheet, added)

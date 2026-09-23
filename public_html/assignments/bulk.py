"""Массовые действия над выданными работами из общего списка.

Строки списка — группы: обычный листок (``ordinary-<worksheet>``) или
проведение самостоятельной (``independent-<run>``). Одно действие на
запрос:

- ``apply`` — статус и/или срок: обычным назначениям — статус (по правилам
  ``_set_assignment_status``) и ``due_at``; самостоятельным — только общее
  окончание ``Run.deadline``, статус к ним не применим;
- ``delete`` — снять выдачу: удаляются назначения листка со всеми ответами
  и историей проверки; проведение самостоятельной — вместе с попытками
  (подтверждение с перечислением получателей собирает страница);
- ``cart`` — задачи выбранных работ в корзину (для сборки нового листка);
- ``independent`` — шаблон самостоятельной по листку одной выбранной выдачи.
"""
import re
from datetime import datetime

from django.contrib import messages
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from worksheets.models import Worksheet

from .models import Assignment

_KEY = re.compile(r'^(ordinary|independent)-(\d+)$')
_POINT_TASK = re.compile(r'^t(\d+)(?::|$)')


def parse_keys(values):
    """Ключи строк → (id листков, id проведений)."""
    worksheets, runs = [], []
    for value in values:
        match = _KEY.match(value or '')
        if not match:
            continue
        (worksheets if match.group(1) == 'ordinary' else runs).append(
            int(match.group(2)))
    return worksheets, runs


def _parse_due(raw):
    """datetime-local → aware datetime или None."""
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S'):
        try:
            return timezone.make_aware(datetime.strptime(raw, fmt))
        except ValueError:
            continue
    return None


def _back(request):
    query = request.POST.get('return_query', '')
    kind = request.POST.get('kind', '')
    base = reverse('independentworks:catalog') if kind == 'independent' else reverse('assignment_list')
    return redirect(f'{base}?{query}' if query else base)


def _runs_for(request, run_ids):
    from independentworks.models import Run, Work
    return list(Run.objects.filter(pk__in=run_ids, work__in=Work.visible_to(request.user))
                .select_related('work'))


@teacher_required
@require_POST
def assignment_bulk(request):
    worksheet_ids, run_ids = parse_keys(request.POST.getlist('ids'))
    if not worksheet_ids and not run_ids:
        messages.error(request, 'Не выбрано ни одной работы.')
        return _back(request)
    action = request.POST.get('action', '')
    worksheets = list(Worksheet.visible_to(request.user).filter(pk__in=worksheet_ids))
    runs = _runs_for(request, run_ids)
    if action == 'delete':
        _delete(request, worksheets, runs)
    elif action == 'apply':
        _apply(request, worksheets, runs)
    elif action == 'cart':
        _to_cart(request, worksheets, runs)
    elif action == 'independent':
        if len(worksheets) != 1 or runs:
            messages.error(request, 'Выберите ровно одну выдачу обычного листка.')
            return _back(request)
        from independentworks.views import create_from_worksheet
        return create_from_worksheet(request, worksheets[0].pk)
    else:
        messages.error(request, 'Неизвестное действие.')
    return _back(request)


def _delete(request, worksheets, runs):
    removed = 0
    with transaction.atomic():
        for worksheet in worksheets:
            count, _ = Assignment.visible_to(request.user).filter(
                worksheet=worksheet).delete()
            removed += bool(count)
    blocked = []
    for run in runs:
        try:
            _delete_run(run)
            removed += 1
        except ProtectedError:
            blocked.append(run.title)
    if removed:
        messages.success(request, f'Снято выдач: {removed}.')
    if blocked:
        messages.error(
            request, 'Не удалены (сначала снимите работу над ошибками или '
                     'пересдачу): ' + ', '.join(f'«{t}»' for t in blocked))


def _delete_run(run):
    """Удаляет проведение с попытками, снимками и файлами.

    Попытки удаляются первыми: их ответы ссылаются на пункты (PROTECT),
    а варианты защищены попытками. Работа над ошибками или пересдача
    ссылается на попытку исходного проведения — тогда ProtectedError.
    """
    from independentworks.models import Asset, Photo
    files = list(Photo.objects.filter(answer__attempt__run=run)
                 .values_list('file', flat=True))
    files += list(Asset.objects.filter(point__variant__run=run)
                  .values_list('file', flat=True))
    storage = Photo._meta.get_field('file').storage
    with transaction.atomic():
        run.attempts.all().delete()
        run.delete()
    for name in files:
        if name:
            storage.delete(name)


def _apply(request, worksheets, runs):
    from .views import _set_assignment_status
    status = request.POST.get('status', '')
    if status not in dict(Assignment.STATUS_CHOICES):
        status = ''
    due_action = request.POST.get('due_action', '')
    due_at = _parse_due(request.POST.get('due_at')) if due_action == 'set' else None
    if due_action == 'set' and due_at is None:
        messages.error(request, 'Укажите срок в формате даты и времени.')
        return
    if not status and due_action not in ('set', 'clear'):
        messages.error(request, 'Выберите, что применить: статус или срок.')
        return
    now = timezone.now()
    changed = blocked = 0
    with transaction.atomic():
        assignments = Assignment.visible_to(request.user).filter(worksheet__in=worksheets)
        for assignment in assignments:
            if status and not _set_assignment_status(assignment, status, now):
                blocked += 1
            if due_action in ('set', 'clear'):
                assignment.due_at = due_at
                assignment.save(update_fields=['due_at'])
            changed += 1
        if due_action in ('set', 'clear') and runs:
            from independentworks.models import Run
            Run.objects.filter(pk__in=[r.pk for r in runs]).update(deadline=due_at)
            changed += len(runs)
    if changed:
        messages.success(request, f'Обновлено: {changed}.')
    if blocked:
        messages.warning(
            request, f'Проверенной можно отметить только отправленную работу '
                     f'(пропущено: {blocked}).')
    if status and runs:
        messages.info(request, 'Статус самостоятельных не меняется вручную — '
                               'только срок.')


def _to_cart(request, worksheets, runs):
    from worksheets.cart import _store, cart_ids
    from worksheets.models import WorksheetItem
    ids = cart_ids(request)
    added = 0
    ordered = list(WorksheetItem.objects.filter(
        worksheet__in=worksheets, deleted_at__isnull=True, task__isnull=False)
        .order_by('worksheet_id', 'order', 'id')
        .values_list('task_id', 'task__variant_of_id'))
    wanted = [variant_of or task_id for task_id, variant_of in ordered]
    if runs:
        from independentworks.models import Point
        keys = (Point.objects.filter(variant__run__in=runs)
                .order_by('variant__run_id', 'variant__number', 'position', 'part')
                .values_list('source_key', flat=True))
        for key in keys:
            match = _POINT_TASK.match(key)
            if match:
                wanted.append(int(match.group(1)))
    for pk in wanted:
        if pk not in ids:
            ids.append(pk)
            added += 1
    _store(request, ids)
    messages.success(
        request, f'В корзину добавлено задач: {added}. Соберите из них листок '
                 f'через «Корзину» в шапке.' if added
        else 'Все задачи выбранных работ уже в корзине.')

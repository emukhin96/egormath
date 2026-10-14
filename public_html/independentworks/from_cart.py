"""Корзина задач → номера самостоятельной.

Каждая задача корзины становится новым номером в конце шаблона через
``services.add_candidate``: блок связанных задач занимает подряд идущие
номера. С ``group_similar`` задачи одной семьи аналогов
(``analogs.similar_groups``) становятся кандидатами одного номера — в
порядке первого появления в корзине. Задачи, уже использованные в
самостоятельной, пропускаются (``pool.validate_selection``). Разное число
подпунктов в одном номере — штатное предупреждение конструктора, не
ошибка.
"""
from django.db import transaction
from django.db.models import Max

from problems.task_blocks import block_members

from .analogs import similar_groups
from .models import Position, Work
from .pool import validate_selection
from .services import WorkError, add_candidate


def _already_used(work, task):
    try:
        validate_selection(Position(work=work), task, [])
    except WorkError:
        return True
    return False


@transaction.atomic
def add_tasks(work, tasks, group_similar=True):
    """Добавляет задачи в конец ``work``; возвращает (id новых номеров, пропущено)."""
    Work.objects.select_for_update().get(pk=work.pk)
    before = set(work.positions.values_list('pk', flat=True))
    groups = similar_groups(t.pk for t in tasks if not t.block_id) if group_similar else {}
    group_positions = {}
    seen_blocks = set()
    skipped = 0

    def new_position():
        order = (work.positions.aggregate(n=Max('order'))['n'] or 0) + 1
        return Position.objects.create(work=work, order=order)

    for task in tasks:
        if task.block_id:
            if task.block_id in seen_blocks:
                continue
            seen_blocks.add(task.block_id)
            try:
                members = block_members(task)
            except ValueError as error:
                raise WorkError(str(error))
            if any(_already_used(work, member) for member in members):
                skipped += len(members)
                continue
            add_candidate(new_position(), members[0])
            continue
        if _already_used(work, task):
            skipped += 1
            continue
        group = groups.get(task.pk)
        if group is not None and group in group_positions:
            add_candidate(group_positions[group], task)
            continue
        position = new_position()
        add_candidate(position, task)
        if group is not None:
            group_positions[group] = position
    created = [pk for pk in work.positions.values_list('pk', flat=True) if pk not in before]
    return created, skipped

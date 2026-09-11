"""Операции над неделимыми блоками в листке."""
from problems.task_blocks import block_members


def item_units(items):
    """Разбивает элементы на единицы перемещения; порядок внутри блока исходный."""
    units, seen = [], set()
    for item in items:
        block_id = item.task.block_id if item.task_id else None
        if not block_id:
            units.append([item])
        elif block_id not in seen:
            seen.add(block_id)
            units.append(sorted((i for i in items if i.task_id and i.task.block_id == block_id),
                                key=lambda i: i.task.block_position))
    return units


def valid_block_order(items):
    """Проверяет непрерывность и полноту каждого блока в предложенном порядке."""
    seen = set()
    index = 0
    while index < len(items):
        item = items[index]
        if not item.task_id or not item.task.block_id:
            index += 1
            continue
        block_id = item.task.block_id
        if block_id in seen:
            return False
        seen.add(block_id)
        try:
            expected = [t.pk for t in block_members(item.task)]
        except ValueError:
            return False
        if [i.task_id for i in items[index:index + len(expected)]] != expected:
            return False
        index += len(expected)
    return True

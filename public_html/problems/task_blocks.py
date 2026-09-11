"""Связи вопросов ОГЭ и проверка полноты неделимых блоков."""
import re
from django.db import transaction
from .models import TaskBlock


@transaction.atomic
def bind_oge_draft_blocks(batch):
    """Связывает вопросы 1–5 только у явно выбранного профиля Остромогильского."""
    if batch.profile != 'ostromogilsky':
        return 0
    changed = []
    blocks = {}
    for draft in batch.drafts.all():
        match = re.fullmatch(r'([1-5])\.(\d+(?:\.\d+)?)', draft.external_id)
        if not match:
            continue
        position, suffix = match.groups()
        if suffix not in blocks:
            blocks[suffix], _ = TaskBlock.objects.get_or_create(
                source=batch.source, key=f'oge-1-5:{suffix}',
                defaults={'title': f'ОГЭ №1–5 · блок {suffix}', 'size': 5})
        block = blocks[suffix]
        if draft.block_id != block.pk or draft.block_position != int(position):
            draft.block = block
            draft.block_position = int(position)
            changed.append(draft)
    if changed:
        batch.drafts.model.objects.bulk_update(changed, ['block', 'block_position'])
    return len(changed)


def block_members(task):
    """Возвращает весь блок в исходном порядке, запрещая неполный набор."""
    if not task.block_id:
        return [task]
    members = list(task.block.tasks.order_by('block_position', 'pk'))
    if [t.block_position for t in members] != list(range(1, task.block.size + 1)):
        raise ValueError('Блок задач загружен не полностью. Сначала загрузите все вопросы.')
    return members

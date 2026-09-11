"""Общее условие полного блока для веба и печатного листка."""
import hashlib
from dataclasses import dataclass

from problems.block_text import split_common_condition


@dataclass(frozen=True)
class BlockQuestion:
    text: str
    common: str
    common_indices: frozenset[int]


def block_presentations(items):
    """Выделяет общее условие только у пяти соседних вопросов по порядку.

    Копии рисунков при импорте получают разные имена, поэтому сравниваются
    байты файлов. При недоступном файле остаются полные условия вопросов.
    """
    result, hashes = {}, {}
    for start, item in enumerate(items):
        if not item.task_id or not item.task.block_id or item.task.block_position != 1:
            continue
        group = items[start:start + 5]
        if (len(group) != 5 or any(not row.task_id for row in group)
                or [row.task.block_position for row in group] != [1, 2, 3, 4, 5]
                or any(row.task.block_id != item.task.block_id for row in group)):
            continue
        keys = []
        try:
            for row in group:
                row_keys = []
                for image in row.task.images.all():
                    name = image.image.name
                    if name not in hashes:
                        digest = hashlib.sha256()
                        with image.image.open('rb') as stream:
                            for chunk in stream.chunks():
                                digest.update(chunk)
                        hashes[name] = digest.hexdigest()
                    row_keys.append(hashes[name])
                keys.append(row_keys)
        except OSError:
            continue
        split = split_common_condition([row.task.text_latex for row in group], keys)
        if split is None:
            continue
        indices = frozenset(position - 1 for position in split.image_positions)
        for index, row in enumerate(group):
            result[row.pk] = BlockQuestion(split.questions[index],
                                           split.text if index == 0 else '', indices)
    return result


def decorate_block_rows(rows):
    """Добавляет представление общего условия к строкам веб-листка."""
    import re
    from problems.task_images import images_for_group, taskpic_indices
    presentations = block_presentations([row['item'] for row in rows])
    for row in rows:
        item = row['item']
        if not item.task_id:
            continue
        presentation = presentations.get(item.pk)
        row['statement'] = presentation.text if presentation else item.task.text_latex
        row['statement_images'] = images_for_group(item.task)
        row['review_images'] = list(item.task.images.all())
        if not presentation:
            continue
        images = list(item.task.images.all())
        remaining = taskpic_indices(presentation.text)
        for subitem in item.task.subitems.all():
            remaining.update(taskpic_indices(subitem.text_latex))
        omitted = {images[index].pk for index in presentation.common_indices - remaining}
        row['statement_images'] = [image for image in row['statement_images'] if image.pk not in omitted]
        row['review_images'] = [image for image in row['review_images'] if image.pk not in omitted]
        if presentation.common:
            parts, start = [], 0
            for match in re.finditer(r'\\taskpic\{(\d+)\}', presentation.common):
                parts.append({'text': presentation.common[start:match.start()]})
                parts.append({'images': [images[int(match.group(1)) - 1]]})
                start = match.end()
            parts.append({'text': presentation.common[start:]})
            row['common_parts'] = parts
    return rows

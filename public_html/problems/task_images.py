"""Какие картинки задачи относятся к условию, а какие — к ответу/решению.

Нумерация как в PDF: ``\\taskpic{1}`` — первая картинка в ``task.images``
(порядок ``order``, затем ``id``). Картинки, на которые ссылаются только
поля ответа/решения, в ученическом варианте не показываем — та же логика,
что в ``worksheets.latex.task_to_tex``.
"""

import re

# Ссылка на картинку в тексте: \taskpic{N}, N — номер по порядку
TASKPIC_NUM_RE = re.compile(r'\\taskpic\{(\d+)\}')
MATERIAL_FIELDS = ('author_answer_latex', 'answer_latex',
                   'author_solution_latex', 'solution_latex')


def taskpic_indices(text):
    """0-индексы картинок, на которые ссылается текст."""
    return {int(match.group(1)) - 1
            for match in TASKPIC_NUM_RE.finditer(text or '')}


def material_indices(owner):
    """Все ссылки материала, включая скрытую авторским полем AI-версию."""
    result = set()
    for field in MATERIAL_FIELDS:
        result.update(taskpic_indices(getattr(owner, field, '')))
    return result


def classify_task_images(task):
    """Делит картинки задачи на условие и ответы/решения.

    Возвращает ``(statement, answers)`` — списки ``TaskImage``.
    Картинка из обоих мест остаётся в условии (без дубля).
    Картинка без ссылок — в условии, как в ученическом PDF.
    """
    images = list(task.images.all())
    statement_ids = set(taskpic_indices(task.text_latex))
    answer_ids = material_indices(task)
    for subitem in task.subitems.all():
        statement_ids.update(taskpic_indices(subitem.text_latex))
        answer_ids.update(material_indices(subitem))

    statement, answers = [], []
    for index, image in enumerate(images):
        if index in statement_ids or index not in answer_ids:
            statement.append(image)
        else:
            answers.append(image)
    return statement, answers


def owner_material_images(task, owner, kind):
    """Рисунки ответа (``kind='answer'``) или решения подпункта/задачи.

    Для карточки редактора: берутся ссылки из обеих версий (авторской и
    редакторской / AI), чтобы ни один рисунок не потерялся; рисунки
    условия и уже показанные в ответе к решению не повторяются.
    """
    fields = {'answer': ('author_answer_latex', 'answer_latex'),
              'solution': ('author_solution_latex', 'solution_latex')}
    indices = set()
    for field in fields[kind]:
        indices.update(taskpic_indices(getattr(owner, field, '')))
    if kind == 'solution':
        for field in fields['answer']:
            indices.difference_update(taskpic_indices(getattr(owner, field, '')))
    images = list(task.images.all())
    _, answers = classify_task_images(task)
    answer_ids = {image.pk for image in answers}
    return [images[i] for i in sorted(indices)
            if i < len(images) and images[i].pk in answer_ids]


def unplaced_material_images(task):
    """Рисунки ответов/решений, на которые не ссылается ни один подпункт.

    Карточка задачи с подпунктами показывает ответы только подпунктов;
    рисунок общего ответа или решения самой задачи выводим отдельно,
    чтобы он не пропал из карточки.
    """
    placed = set()
    for subitem in task.subitems.all():
        placed.update(material_indices(subitem))
    images = list(task.images.all())
    _, answers = classify_task_images(task)
    return [image for image in answers if images.index(image) not in placed]


def images_for_group(task, group='statement'):
    """Картинки для веб-блока: ``statement``, ``answers`` или ``all``."""
    if group == 'all':
        return list(task.images.all())
    statement, answers = classify_task_images(task)
    if group == 'answers':
        return answers
    return statement

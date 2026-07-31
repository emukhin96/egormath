"""Генерация .tex-документа листка на пакете egor.

Текст задач хранится в базе как доверенный LaTeX (его пишут учителя),
экранируются только «обычные» поля: название листка, класс, автор.
"""

import hashlib

from problems.latex_utils import escape_latex

# Опции \usepackage{egor} по вариантам сборки
VARIANT_OPTIONS = {
    'student': '',
    'answers': 'answers=table',
    'teacher': 'answers=inline,solutions',
}

DEFAULT_RUBRIC = 'Задачи'


def _opt(content):
    """Опциональный аргумент [..]; фигурные скобки защищают ']' внутри."""
    return '[{%s}]' % content


def task_to_tex(task):
    """\\task{звёзды}{колонки}{условие}[подпункты][ответ][решение]"""
    parts = [
        '\\task{%d}{%d}{%%\n%s%%\n}' % (task.stars, task.columns,
                                        task.text_latex.strip()),
    ]
    subitems = task.subitems_latex.strip()
    answer = task.answer_latex.strip()
    solution = task.solution_latex.strip()
    # Хвостовые пустые аргументы опускаем, промежуточные передаём пустыми
    tail = []
    if solution:
        tail = [subitems, answer, solution]
    elif answer:
        tail = [subitems, answer]
    elif subitems:
        tail = [subitems]
    for value in tail:
        parts.append(_opt(value))
    return ''.join(parts)


def worksheet_to_tex(worksheet, variant='student'):
    options = VARIANT_OPTIONS[variant]
    usepackage = ('\\usepackage[%s]{egor}' % options) if options \
        else '\\usepackage{egor}'

    lines = [
        '\\documentclass[a5paper,10pt]{article}',
        usepackage,
        '',
        '\\begin{document}',
    ]

    bighead = '\\bighead{%s}{%s}{%s}' % (
        escape_latex(worksheet.title),
        escape_latex(worksheet.grade_label),
        escape_latex(worksheet.display_author),
    )
    if worksheet.subtitle:
        bighead += _opt(escape_latex(worksheet.subtitle))
    lines.append(bighead)
    lines.append('')

    items = list(worksheet.ordered_items())
    current_rubric = None
    for i, item in enumerate(items):
        rubric = item.rubric.strip()
        if i == 0 and not rubric:
            rubric = DEFAULT_RUBRIC
        if rubric and rubric != current_rubric:
            rubr = '\\rubr{%s}' % rubric
            if item.rubric_note.strip():
                rubr += _opt(item.rubric_note.strip())
            lines.append('')
            lines.append(rubr)
            current_rubric = rubric
        lines.append('')
        lines.append(task_to_tex(item.task))

    if items:
        lines.append('')
        lines.append('\\end{enumerate}')
    lines.append('')
    lines.append('\\end{document}')
    return '\n'.join(lines)


def tex_hash(tex_content):
    return hashlib.sha256(tex_content.encode('utf-8')).hexdigest()

"""Генерация .tex-документа листка на пакете egor.

Текст задач хранится в базе как доверенный LaTeX (его пишут учителя),
экранируются только «обычные» поля: название листка, класс, автор.
"""

import hashlib
import re

from problems.latex_utils import escape_latex

# Опции \usepackage{egor} по вариантам сборки
VARIANT_OPTIONS = {
    'student': '',
    'answers': 'answers=table',
    'teacher': 'answers=inline,solutions',
}

# Метки подпунктов как у \asbuk (без ё, й, ъ, ы, ь) — для сводного ответа
CYRILLIC_LABELS = 'абвгдежзиклмнопрстуфхцчшщэюя'


def _opt(content):
    """Опциональный аргумент [..]; фигурные скобки защищают ']' внутри."""
    return '[{%s}]' % content


def subitem_label(index):
    """Метка подпункта по позиции в листке (перенумерация заново)."""
    if index < len(CYRILLIC_LABELS):
        return CYRILLIC_LABELS[index]
    return str(index + 1)


def _combined_answer(task, subitems):
    """Общий ответ задачи + ответы выбранных подпунктов («а) …; б) …»)."""
    parts = []
    if task.answer_latex.strip():
        parts.append(task.answer_latex.strip())
    sub_answers = [
        '%s)~%s' % (subitem_label(i), s.answer_latex.strip())
        for i, s in enumerate(subitems) if s.answer_latex.strip()
    ]
    if sub_answers:
        parts.append('; '.join(sub_answers))
    return ' '.join(parts)


# Ссылка на картинку в тексте задачи: \taskpic{N}, N — номер по порядку
TASKPIC_REF_RE = re.compile(r'\\taskpic\{(\d+)\}')


def _resolve_taskpics(text, filenames, used):
    """Заменяет ссылки \\taskpic{N} на \\taskpic{имя-файла}.

    Ссылки на несуществующие номера убираются молча — так PDF компилируется
    и до загрузки картинок (двухшаговый импорт из .tex).
    """
    def repl(match):
        index = int(match.group(1)) - 1
        if 0 <= index < len(filenames):
            used.add(index)
            return '\\taskpic{%s}' % filenames[index]
        return ''
    return TASKPIC_REF_RE.sub(repl, text)


def task_to_tex(item):
    """\\task{звёзды}{колонки}{условие}[подпункты][ответ][решение]

    Работает от элемента листка: звёзды/колонки — с учётом переопределений,
    подпункты — только выбранные (пустой выбор = все).
    """
    task = item.task
    subitem_objs = item.selected_subitems()
    filenames = [image.filename for image in task.images.all()]
    used = set()
    body = _resolve_taskpics(task.text_latex.strip(), filenames, used)
    sub_texts = [
        _resolve_taskpics(s.text_latex.strip(), filenames, used)
        for s in subitem_objs
    ]
    # Пунктуация подпунктов: «;» между пунктами, «.» после последнего
    # (в базе тексты хранятся без знака препинания на конце)
    sub_lines = []
    for i, text in enumerate(sub_texts):
        punct = '.' if i == len(sub_texts) - 1 else ';'
        if text and text[-1] not in ';.!?:':
            text += punct
        sub_lines.append('\\item %s' % text)
    # Картинки без ссылки в тексте — в конец условия;
    # \taskpic копит их в условии, блок выпускает \flushpics
    for i, name in enumerate(filenames):
        if i not in used:
            body += '\n\\taskpic{%s}' % name
    # Без подпунктов колонки обнуляются: \columned{0} печатает только
    # условие, а columns>=1 с пустым списком падают на «missing \item»
    # (пустой [{}] всё равно передаётся, когда дальше идёт ответ)
    columns = item.effective_columns if sub_lines else 0
    parts = [
        '\\task{%d}{%d}{%%\n%s%%\n}' % (
            item.effective_stars, columns, body),
    ]
    subitems = '\n'.join(sub_lines)
    answer = _combined_answer(task, subitem_objs)
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


def text_to_tex(item):
    """Произвольный текст между задачами — \\plaintext пакета egor."""
    return '\\plaintext{%%\n%s%%\n}' % item.text_latex.strip()


def rubric_to_tex(item):
    """Элемент-рубрика — \\rubr{...}[пояснение]; сам открывает список."""
    tex = '\\rubr{%s}' % item.rubric.strip()
    if item.rubric_note.strip():
        tex += _opt(item.rubric_note.strip())
    return tex


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
    list_open = False
    list_has_item = False
    for item in items:
        if item.is_text:
            lines.append('')
            if list_open and not list_has_item:
                # Текст сразу после \rubr: enumerate уже открыт, но пункта
                # ещё нет — пустой \item[] (нумерацию не сдвигает) не даёт
                # LaTeX упасть на «perhaps a missing \item»
                lines.append('\\item[]')
                list_has_item = True
            lines.append(text_to_tex(item))
            continue
        if item.is_rubric:
            # \rubr сам открывает список задач (или продолжает через resume)
            lines.append('')
            lines.append(rubric_to_tex(item))
            list_open = True
            list_has_item = False
            continue
        if not list_open:
            # Задача до первой рубрики — список стартуем вручную
            lines.append('')
            lines.append('\\begin{enumerate}')
            list_open = True
        lines.append('')
        lines.append(task_to_tex(item))
        list_has_item = True

    if list_open:
        lines.append('')
        lines.append('\\end{enumerate}')
    if any(item.task_id and item.task.images.all() for item in items):
        lines.append('')
        lines.append('\\flushpics')
    lines.append('')
    lines.append('\\end{document}')
    return '\n'.join(lines)


def tex_hash(tex_content):
    return hashlib.sha256(tex_content.encode('utf-8')).hexdigest()

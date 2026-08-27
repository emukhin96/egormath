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

# TeX Live 2025-11 убрал \tbl_save_outer_table_cols: из ядра, а bidi
# (xelatex, его подтягивает egor) всё ещё вставляет вызов в \@@array.
# Без заглушки падают array/tabular/cases — в том числе формулы систем
# в \plaintext после импорта Word/TeX. Определяем команду, только если
# её нет: на старых ядрах оставляем настоящую реализацию.
ARRAY_BIDI_SHIM = (
    '\\ExplSyntaxOn\n'
    '\\cs_if_exist:NF \\tbl_save_outer_table_cols:\n'
    '  {\\cs_gset_eq:NN \\tbl_save_outer_table_cols: \\scan_stop:}\n'
    '\\ExplSyntaxOff'
)

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


def _for_task_opt(text):
    """Готовит текст для опционального аргумента \\task.

    Аргумент не \\long: пустая строка (\\par) его обрывает. \\mbox{}\\\\
    даёт перенос и после display-формулы (иначе «no line here to end»).
    """
    return re.sub(r'\n\s*\n+', r' \\mbox{}\\\\ ', text.strip())


def _join_labeled(parts, wrapper='stack'):
    """Склеивает куски ответа/решения, каждый на своей строке.

    Голый \\\\ в answers=table завершает строку таблицы пакета egor.
    Ответы короткие — \\shortstack по ширине содержимого.
    Решения могут быть с абзацами и display-формулами — minipage.
    """
    if not parts:
        return ''
    needs_wrap = len(parts) > 1 or any('\\\\' in p for p in parts)
    if wrapper == 'mini':
        # Всегда minipage: после «Решение.» идёт перенос, блок на всю строку
        body = ' \\mbox{}\\\\ '.join(parts)
        return '\\begin{minipage}[t]{\\linewidth}%%\n%s%%\n\\end{minipage}' % body
    body = ' \\\\ '.join(parts)
    if not needs_wrap:
        return parts[0]
    return '\\shortstack[l]{%s}' % body


def _combined_answer(task, subitems):
    """Общий ответ задачи + ответы выбранных подпунктов (каждый с новой строки)."""
    parts = []
    if task.effective_answer_latex:
        parts.append(_for_task_opt(task.effective_answer_latex))
    parts.extend(
        '%s)~%s' % (subitem_label(i),
                    _for_task_opt(s.effective_answer_latex))
        for i, s in enumerate(subitems) if s.effective_answer_latex
    )
    return _join_labeled(parts, 'stack')


def _combined_solution(task, subitems):
    """Общее решение задачи + решения подпунктов (каждый с новой строки)."""
    parts = []
    if task.effective_solution_latex:
        parts.append(_for_task_opt(task.effective_solution_latex))
    parts.extend(
        '%s)~%s' % (subitem_label(i),
                    _for_task_opt(s.effective_solution_latex))
        for i, s in enumerate(subitems) if s.effective_solution_latex
    )
    text = _join_labeled(parts, 'mini')
    if not text:
        return ''
    # egor печатает «\textit{Решение}. #1» в одной строке — перенос, чтобы
    # minipage не сдвигался на ширину слова
    return '\\mbox{}\\\\ %s' % text


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
    body_used = set()
    body = _resolve_taskpics(task.text_latex.strip(), filenames, body_used)
    used = set(body_used)
    sub_texts = []
    deferred_pics = set()
    for subitem in subitem_objs:
        subitem_used = set()
        sub_text = _resolve_taskpics(
            subitem.text_latex.strip(), filenames, subitem_used)
        # Пакет egor не выводит \\taskpic из опционального
        # аргумента подпунктов, поэтому переносим ссылки в тело.
        sub_text = re.sub(r'\s*\\taskpic\{[^{}]+\}', '', sub_text)
        deferred_pics.update(subitem_used)
        used.update(subitem_used)
        sub_texts.append(sub_text)
    # Пунктуация подпунктов: «;» между пунктами, «.» после последнего
    # (в базе тексты хранятся без знака препинания на конце)
    sub_lines = []
    for i, text in enumerate(sub_texts):
        punct = '.' if i == len(sub_texts) - 1 else ';'
        if text and text[-1] not in ';.!?:':
            text += punct
        sub_lines.append('\\item %s' % text)
    # Без подпунктов колонки обнуляются: \columned{0} печатает только
    # условие, а columns>=1 с пустым списком падают на «missing \item»
    # (пустой [{}] всё равно передаётся, когда дальше идёт ответ)
    columns = item.effective_columns if sub_lines else 0
    subitems = '\n'.join(sub_lines)
    answer = _combined_answer(task, subitem_objs)
    answer_used = set()
    answer = _resolve_taskpics(answer, filenames, answer_used)
    answer = re.sub(r'\s*\\taskpic\{[^{}]+\}', '', answer)
    deferred_pics.update(answer_used)
    used.update(answer_used)
    solution = _combined_solution(task, subitem_objs)
    solution_used = set()
    solution = _resolve_taskpics(solution, filenames, solution_used)
    solution = re.sub(r'\s*\\taskpic\{[^{}]+\}', '', solution)
    deferred_pics.update(solution_used)
    used.update(solution_used)
    # Рисунки из optional-аргументов и рисунки без ссылки
    # выводим один раз в основном теле задачи.
    for i, name in enumerate(filenames):
        if ((i in deferred_pics and i not in body_used)
                or i not in used):
            body += '\n\\taskpic{%s}' % name
    parts = [
        '\\task{%d}{%d}{%%\n%s%%\n}' % (
            item.effective_stars, columns, body),
    ]
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


# Команды egor для стилей текстового элемента (WorksheetItem.text_style)
TEXT_STYLE_COMMANDS = {
    'plain': 'plaintext',
    'rule': 'ruletext',
    'light': 'lighttext',
    'memo': 'memotext',
}


def text_to_tex(item):
    """Произвольный текст между задачами — \\plaintext/\\ruletext/… egor."""
    command = TEXT_STYLE_COMMANDS.get(item.text_style, 'plaintext')
    return '\\%s{%%\n%s%%\n}' % (command, item.text_latex.strip())


def rubric_to_tex(item):
    """Элемент-рубрика — \\rubr{...}[пояснение]; сам открывает список."""
    tex = '\\rubr{%s}' % item.rubric.strip()
    if item.rubric_note.strip():
        tex += _opt(item.rubric_note.strip())
    return tex


def _drop_empty_rubrics(items):
    """Убирает рубрики, после которых до следующей нет задач и текста.

    \\rubr открывает enumerate: если все задачи рубрики скрыты, LaTeX
    падает на «perhaps a missing \\item». Текстовый элемент после
    пустой рубрики оставляем — для него уже есть \\item[].
    """
    kept = []
    i = 0
    n = len(items)
    while i < n:
        item = items[i]
        if item.is_rubric:
            has_content = False
            for nxt in items[i + 1:]:
                if nxt.is_rubric:
                    break
                if nxt.task_id or nxt.is_text:
                    has_content = True
                    break
            if not has_content:
                i += 1
                continue
        kept.append(item)
        i += 1
    return kept


def worksheet_to_tex(worksheet, variant='student', exclude_ids=None):
    """exclude_ids — pk элементов, скрытых для конкретной ссылки/ученика."""
    exclude_ids = exclude_ids or set()
    options = VARIANT_OPTIONS[variant]
    usepackage = ('\\usepackage[%s]{egor}' % options) if options \
        else '\\usepackage{egor}'

    lines = [
        '\\documentclass[a5paper,10pt]{article}',
        usepackage,
        ARRAY_BIDI_SHIM,
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

    items = _drop_empty_rubrics([
        item for item in worksheet.ordered_items()
        if item.pk not in exclude_ids
    ])
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
        if not list_has_item:
            # Пустой enumerate (рубрика без видимых задач и без текста)
            # всё равно нужно закрыть без ошибки «missing \\item»
            lines.append('\\item[]')
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

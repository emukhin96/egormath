"""Генерация Beamer-презентации из листка.

Оформление — пакет egorbeamer (не egor.sty). Текст задач — доверенный
LaTeX; экранируются только название, класс, автор, рубрики.
"""

import re

from problems.latex_utils import escape_latex

from .latex import (_drop_empty_rubrics, _resolve_taskpics, subitem_label)

THEMES = ('light', 'night', 'paper')
ASPECTS = ('169', '43')
SIZES = ('11pt', '12pt', '14pt')
CONTENTS = ('problems', 'answers', 'solutions')
REVEALS = ('click', 'show', 'hidden')

DEFAULTS = {
    'theme': 'light',
    'aspect': '169',
    'size': '12pt',
    'content': 'problems',
    'reveal': 'click',
    'stars': True,
    'footer': True,
}

_TASKPIC_CMD_RE = re.compile(r'\s*\\taskpic\{[^{}]+\}')


def normalize_beamer_options(**kwargs):
    """Нормализует опции презентации; неизвестные значения → умолчания."""
    opts = dict(DEFAULTS)
    for key, value in kwargs.items():
        if value is None or key not in opts:
            continue
        opts[key] = value
    if opts['theme'] not in THEMES:
        opts['theme'] = DEFAULTS['theme']
    if opts['aspect'] not in ASPECTS:
        opts['aspect'] = DEFAULTS['aspect']
    if opts['size'] not in SIZES:
        opts['size'] = DEFAULTS['size']
    if opts['content'] not in CONTENTS:
        opts['content'] = DEFAULTS['content']
    if opts['reveal'] not in REVEALS:
        opts['reveal'] = DEFAULTS['reveal']
    opts['stars'] = bool(opts['stars'])
    opts['footer'] = bool(opts['footer'])
    return opts


def _pkg_options(opts):
    parts = [
        'theme=%s' % opts['theme'],
        'content=%s' % opts['content'],
        'reveal=%s' % opts['reveal'],
        'stars' if opts['stars'] else 'nostars',
        'footer' if opts['footer'] else 'nofooter',
    ]
    return ','.join(parts)


def _join_parts(parts):
    return '\n\n'.join(p.strip() for p in parts if p and p.strip())


def _wrap_cmd(name, body):
    """\\name{% ... } — тело с переносами, как у \\plaintext в latex.py."""
    return '\\%s{%%\n%s%%\n}' % (name, body.strip())


def _title_slide(worksheet):
    title = escape_latex(worksheet.title)
    grade = escape_latex(worksheet.grade_label)
    author = escape_latex(worksheet.display_author)
    tex = '\\egortitle{%s}{%s}{%s}' % (title, grade, author)
    if worksheet.subtitle:
        tex += '[%s]' % escape_latex(worksheet.subtitle)
    return tex


def _rubric_slide(item):
    name = escape_latex(item.rubric.strip())
    tex = '\\egorsection{%s}' % name
    if item.rubric_note.strip():
        tex += '[%s]' % escape_latex(item.rubric_note.strip())
    return tex


def _text_slide(item):
    body = item.text_latex.strip()
    style = item.text_style
    if style == 'rule':
        inner = '\\begin{block}{Правило}\n%s\n\\end{block}' % body
        title = 'Правило'
    elif style == 'memo':
        inner = '\\begin{exampleblock}{Памятка}\n%s\n\\end{exampleblock}' % body
        title = 'Памятка'
    else:
        inner = body
        title = ''
    if title:
        return '\\begin{frame}[t]{%s}\n%s\n\\end{frame}' % (title, inner)
    return '\\begin{frame}[t]\n%s\n\\end{frame}' % inner


def _subitem_lines(item, filenames, used, deferred):
    """Пункты enumerate с кириллическими метками; картинки — в тело."""
    subitem_objs = item.selected_subitems()
    lines = []
    for i, subitem in enumerate(subitem_objs):
        sub_used = set()
        text = _resolve_taskpics(
            subitem.text_latex.strip(), filenames, sub_used)
        text = _TASKPIC_CMD_RE.sub('', text)
        deferred.update(sub_used)
        used.update(sub_used)
        punct = '.' if i == len(subitem_objs) - 1 else ';'
        if text and text[-1] not in ';.!?:':
            text += punct
        lines.append('\\item[%s)] %s' % (subitem_label(i), text))
    return lines, subitem_objs


def _labeled_parts(task_text, subitems, attr):
    parts = []
    if task_text:
        parts.append(task_text.strip())
    parts.extend(
        '%s)~%s' % (subitem_label(i), getattr(s, attr).strip())
        for i, s in enumerate(subitems) if getattr(s, attr)
    )
    return _join_parts(parts)


def _task_slide(item, number):
    task = item.task
    filenames = [image.filename for image in task.images.all()]
    body_used = set()
    body = _resolve_taskpics(task.text_latex.strip(), filenames, body_used)
    used = set(body_used)
    deferred = set()
    sub_lines, subitems = _subitem_lines(item, filenames, used, deferred)

    answer = _labeled_parts(
        task.effective_answer_latex, subitems, 'effective_answer_latex')
    answer_used = set()
    if answer:
        answer = _resolve_taskpics(answer, filenames, answer_used)
    used.update(answer_used)

    solution = _labeled_parts(
        task.effective_solution_latex, subitems, 'effective_solution_latex')
    solution_used = set()
    if solution:
        solution = _resolve_taskpics(solution, filenames, solution_used)
    used.update(solution_used)

    for i, name in enumerate(filenames):
        if i not in used or (i in deferred and i not in body_used):
            body += '\n\\taskpic{%s}' % name

    stars = item.effective_stars
    if stars:
        frametitle = '%d.\\ \\egorstars{%d}' % (number, stars)
    else:
        frametitle = '%d.' % number

    chunks = [body]
    if sub_lines:
        enum = '\\begin{enumerate}\n%s\n\\end{enumerate}' % '\n'.join(sub_lines)
        columns = item.effective_columns
        if columns >= 2:
            enum = '\\begin{multicols}{%d}\n%s\n\\end{multicols}' % (
                columns, enum)
        chunks.append(enum)
    if answer:
        chunks.append(_wrap_cmd('egoranswer', answer))
    if solution:
        chunks.append(_wrap_cmd('egorsolution', solution))
    return '\\begin{frame}[t]{%s}\n%s\n\\end{frame}' % (
        frametitle, '\n\n'.join(chunks))


def worksheet_to_beamer(worksheet, exclude_ids=None, **kwargs):
    """Собрать .tex презентации. kwargs — опции normalize_beamer_options."""
    opts = normalize_beamer_options(**kwargs)
    exclude_ids = exclude_ids or set()
    lines = [
        '\\documentclass[aspectratio=%s,%s]{beamer}' % (
            opts['aspect'], opts['size']),
        '\\usepackage[%s]{egorbeamer}' % _pkg_options(opts),
        '',
        '\\begin{document}',
        '',
        _title_slide(worksheet),
        '',
    ]
    items = _drop_empty_rubrics([
        item for item in worksheet.ordered_items()
        if item.pk not in exclude_ids
    ])
    number = 0
    for item in items:
        if item.is_rubric:
            lines.append(_rubric_slide(item))
            lines.append('')
            continue
        if item.is_text:
            lines.append(_text_slide(item))
            lines.append('')
            continue
        number += 1
        lines.append(_task_slide(item, number))
        lines.append('')
    lines.append('\\end{document}')
    return '\n'.join(lines)

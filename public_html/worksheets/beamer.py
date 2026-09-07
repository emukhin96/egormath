"""Генерация Beamer-презентации из листка.

Оформление — пакет egorbeamer (не egor.sty). Текст задач — доверенный
LaTeX; экранируются только название, класс, автор, рубрики.
"""

import re

from problems.latex_utils import escape_latex

from .latex import (_drop_empty_rubrics, _opt, _resolve_taskpics, subitem_label)

THEMES = ('light', 'night', 'grid')
ASPECTS = ('169', '43')
SIZES = ('11pt', '12pt', '14pt')
CONTENTS = ('problems', 'answers', 'solutions')
REVEALS = ('click', 'show', 'hidden', 'end')
ITEMS = ('all', 'click')
ITEMFLOWS = ('stack', 'solo')
FONTS = ('cm', 'school', 'inter')

DEFAULTS = {
    'theme': 'light',
    'aspect': '169',
    'size': '12pt',
    'content': 'problems',
    'reveal': 'click',
    'items': 'all',
    'itemflow': 'stack',
    'font': 'school',
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
    if opts['items'] not in ITEMS:
        opts['items'] = DEFAULTS['items']
    if opts['itemflow'] not in ITEMFLOWS:
        opts['itemflow'] = DEFAULTS['itemflow']
    if opts['font'] not in FONTS:
        opts['font'] = DEFAULTS['font']
    opts['stars'] = bool(opts['stars'])
    opts['footer'] = bool(opts['footer'])
    return opts


def _pkg_options(opts):
    parts = [
        'theme=%s' % opts['theme'],
        'content=%s' % opts['content'],
        'reveal=%s' % opts['reveal'],
        'items=%s' % opts['items'],
        'itemflow=%s' % opts['itemflow'],
        'font=%s' % opts['font'],
        'fontsize=%s' % opts['size'],
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
        tex += _opt(escape_latex(worksheet.subtitle))
    return tex


def _rubric_slide(item):
    name = escape_latex(item.rubric.strip())
    tex = '\\egorsection{%s}' % name
    if item.rubric_note.strip():
        tex += _opt(escape_latex(item.rubric_note.strip()))
    return tex


def _content_frame(body, title='', label='', valign='t', breaks=False):
    """Кадр с пользовательским LaTeX: fragile первым (verbatim, \\verb)."""
    opts = 'fragile,%s' % valign
    if breaks:
        opts += ',allowframebreaks'
    if label:
        opts += ',label=%s' % label
    if title:
        return '\\begin{frame}[%s]{%s}\n%s\n\\end{frame}' % (opts, title, body)
    return '\\begin{frame}[%s]\n%s\n\\end{frame}' % (opts, body)


def _text_slide(item):
    body = item.text_latex.strip()
    style = item.text_style
    if style == 'rule':
        heading = 'Правило'
    elif style == 'memo':
        heading = 'Памятка'
    else:
        heading = ''
    # Без block/exampleblock: vmode-плашка сетки растягивается на кадр.
    if heading:
        inner = (
            '{\\usebeamercolor[fg]{frametitle}\\Large\\bfseries %s\\par}\n'
            '\\vspace{0.75em}\n%s' % (heading, body))
    else:
        inner = body
    # Не parbox: аргумент макроса ломает \\verb / verbatim даже в fragile.
    inner = '\\vspace*{\\fill}\n%s\n\\vspace*{\\fill}' % inner
    return _content_frame(inner, valign='t')


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
        lines.append('\\item[{%s)}] %s' % (subitem_label(i), text))
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


def _task_slide(item, number, frame_breaks=False):
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

    chunks = ['\\egortask{%d}' % number, body]
    if sub_lines:
        columns = item.effective_columns
        if columns >= 2:
            enum = '\\begin{egoritems}[%d]\n%s\n\\end{egoritems}' % (
                columns, '\n'.join(sub_lines))
        else:
            enum = '\\begin{egoritems}\n%s\n\\end{egoritems}' % (
                '\n'.join(sub_lines))
        chunks.append(enum)
    chunks.append('\\egorworkarea')
    if answer:
        chunks.append(_wrap_cmd('egoranswer', answer))
    if solution:
        chunks.append(_wrap_cmd('egorsolution', solution))
    return _content_frame(
        '\n\n'.join(chunks), frametitle, label='egortask-%d' % number,
        breaks=frame_breaks)


def worksheet_to_beamer(worksheet, exclude_ids=None, **kwargs):
    """Собрать .tex презентации. kwargs — опции normalize_beamer_options."""
    opts = normalize_beamer_options(**kwargs)
    exclude_ids = exclude_ids or set()
    lines = [
        # Кегль — опция пакета, не класса: [14pt]{beamer} требует
        # size14.clo (extsizes), которого нет на LaTeX API.
        '\\documentclass[aspectratio=%s]{beamer}' % opts['aspect'],
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
        # allowframebreaks несовместим с оверлеями (reveal=click / items=click).
        frame_breaks = (
            opts['content'] == 'solutions'
            and opts['reveal'] == 'show'
            and opts['items'] == 'all'
        )
        lines.append(_task_slide(item, number, frame_breaks=frame_breaks))
        lines.append('')
    lines.append('\\egorappendix')
    lines.append('')
    lines.append('\\end{document}')
    return '\n'.join(lines)

"""Нормализованный .egor.tex из черновика — для ручной правки."""

from __future__ import annotations

from .subitems import join_subitem_answers, join_subitem_solutions


def _esc(text):
    return (text or '').replace('\\', r'\textbackslash{}').replace(
        '{', r'\{').replace('}', r'\}')


def emit_egor_tex(draft: dict) -> str:
    header = draft.get('header') or {}
    title = header.get('title') or draft.get('title') or 'Листок'
    left = header.get('left') or (
        f'{draft.get("grade")} класс' if draft.get('grade') else '')
    right = header.get('right') or ''
    subtitle = header.get('subtitle') or ''
    lines = [
        '\\documentclass[a5paper,11pt]{article}',
        '\\usepackage{egor}',
        '',
        '\\begin{document}',
        '\\bighead{%s}{%s}{%s}%s' % (
            _esc(title), _esc(left), _esc(right),
            ('[%s]' % _esc(subtitle)) if subtitle else ''),
        '',
    ]
    for el in draft.get('elements') or []:
        kind = el.get('kind')
        if kind == 'rubric':
            note = el.get('note') or ''
            if note:
                lines.append('\\rubr{%s}[%s]' % (el.get('rubric', ''), note))
            else:
                lines.append('\\rubr{%s}' % (el.get('rubric') or ''))
            lines.append('')
        elif kind == 'text':
            cmd = {
                'rule': 'ruletext', 'light': 'lighttext', 'memo': 'memotext',
            }.get(el.get('style'), 'plaintext')
            lines.append('\\%s{%%\n%s%%\n}' % (cmd, el.get('text') or ''))
            lines.append('')
        elif kind == 'task':
            if el.get('skip'):
                continue
            lines.append(_emit_task(el))
            lines.append('')
    lines.append('\\end{document}')
    lines.append('')
    return '\n'.join(lines)


def _emit_task(el):
    stars = int(el.get('stars') or 0)
    columns = int(el.get('columns') or 0)
    text = (el.get('text') or '').strip()
    subitems = el.get('subitems') or []
    answer = join_subitem_answers(el) or (el.get('answer') or '').strip()
    solution = join_subitem_solutions(el) or (el.get('solution') or '').strip()
    parts = ['\\task{%d}{%d}{%%\n%s%%\n}' % (stars, columns, text)]
    tail = []
    if solution:
        tail = [_subitems_arg(subitems), answer, solution]
    elif answer:
        tail = [_subitems_arg(subitems), answer]
    elif subitems:
        tail = [_subitems_arg(subitems)]
    for value in tail:
        parts.append('[{%s}]' % value)
    return ''.join(parts)


def _subitems_arg(subitems):
    if not subitems:
        return ''
    return '\n'.join('\\item %s' % chunk for chunk in subitems)

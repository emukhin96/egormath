"""Преобразование LaTeX-текста задач в HTML для веб-страниц.

Формулы ($…$ и $$…$$) не трогаем — их рендерит KaTeX в браузере.
Обрабатываются «форматирующие» конструкции, которые иначе видны как
сырой код: комментарии %, переносы \\ и \par, аннотации \annot{…},
неразрывный пробел ~, экранированные символы (\%, \& …) и таблицы
tabular (превращаются в HTML-таблицу).
"""

import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

# Служебные маркеры: подставляются до HTML-экранирования, а после него
# заменяются на разметку. В текстах задач эти символы не встречаются.
_BR = '\x01'
_NBSP = '\x02'
_ANNOT_OPEN = '\x03'
_ANNOT_CLOSE = '\x04'

# Все разделители формул, которые рендерит KaTeX (static/js/math.js):
# $$…$$, \[…\], $…$, \(…\) — внутри них текст не преобразуем
_MATH_RE = re.compile(
    r'\$\$.*?\$\$|\\\[.*?\\\]|\$.*?\$|\\\(.*?\\\)', re.S)
_TABULAR_RE = re.compile(
    r'\\begin\{tabular\}\s*(\{[^{}]*\})?(.*?)\\end\{tabular\}', re.S)
_ANNOT_RE = re.compile(r'\\annot\{((?:[^{}]|\{[^{}]*\})*)\}', re.S)
_COMMENT_RE = re.compile(r'(?<!\\)%[^\n]*')
_TASKPIC_RE = re.compile(r'\s*\\taskpic(?:\[[^\]]*\])?\{[^}]*\}')

# Замены в тексте вне формул (внутри $…$ всё это понимает KaTeX)
_UNESCAPE = [('\\%', '%'), ('\\&', '&'), ('\\_', '_'), ('\\#', '#'),
             ('\\,', ' ')]


def _plain(text):
    """Замены в фрагменте вне формул: переносы, ~, экранированные символы."""
    text = re.sub(r'\\par\b', _BR + _BR, text)
    text = text.replace('\\\\', _BR)
    text = re.sub(r'(?<!\\)~', _NBSP, text)
    for src, dst in _UNESCAPE:
        text = text.replace(src, dst)
    return text


def _prepare(text):
    """Все преобразования фрагмента вне формул: taskpic, annot, _plain."""
    text = _TASKPIC_RE.sub('', text)
    text = _ANNOT_RE.sub(
        lambda m: _ANNOT_OPEN + m.group(1).strip() + _ANNOT_CLOSE, text)
    return _plain(text)


def _markers_to_html(html):
    return (html
            .replace(_BR + _BR, '<br><br>')
            .replace(_BR, '<br>')
            .replace(_NBSP, '&nbsp;')
            .replace(_ANNOT_OPEN, '<span class="tex-annot">')
            .replace(_ANNOT_CLOSE, '</span>'))


def _fragment_html(text):
    """Экранированный HTML фрагмента: формулы нетронуты, остальное — _plain."""
    parts = []
    pos = 0
    for m in _MATH_RE.finditer(text):
        parts.append(_plain(text[pos:m.start()]))
        parts.append(m.group(0))
        pos = m.end()
    parts.append(_plain(text[pos:]))
    return _markers_to_html(escape(''.join(parts)))


def _table_html(body):
    """tabular → <table>: строки по \\\\, ячейки по неэкранированному &."""
    body = body.replace('\\hline', '')
    rows = []
    for row in body.split('\\\\'):
        cells = [c.strip() for c in re.split(r'(?<!\\)&', row)]
        if not any(cells):
            continue
        rows.append('<tr>'
                    + ''.join(f'<td>{_fragment_html(c)}</td>' for c in cells)
                    + '</tr>')
    return '<table class="tex-table">' + ''.join(rows) + '</table>'


def tex_to_web_html(source):
    """HTML-версия текста задачи для веб-страниц (формулы рендерит KaTeX).

    Сначала прячутся таблицы (внутри tabular есть свои $…$ и \\\\),
    затем выделяются формулы, и все остальные преобразования применяются
    только к фрагментам вне формул — команды внутри $…$ достаются KaTeX
    нетронутыми. Комментарии режутся первыми: в TeX % — комментарий
    и в тексте, и в математике.
    """
    text = _COMMENT_RE.sub('', source or '').strip()

    tables = []

    def stash(match):
        tables.append(match.group(2))
        return f'\x05{len(tables) - 1}\x06'

    text = _TABULAR_RE.sub(stash, text)

    parts = []
    pos = 0
    for m in _MATH_RE.finditer(text):
        parts.append(_prepare(text[pos:m.start()]))
        parts.append(m.group(0))
        pos = m.end()
    parts.append(_prepare(text[pos:]))

    html = _markers_to_html(escape(''.join(parts)))
    for i, body in enumerate(tables):
        html = html.replace(f'\x05{i}\x06', _table_html(body))
    return mark_safe(html)


def _safe_cut(text, limit):
    """Обрезка tex-исходника, не разрезающая формулу или команду посередине."""
    cut = text[:limit]
    # незакрытая формула $…: откат до её начала
    if cut.count('$') % 2:
        cut = cut[:cut.rfind('$')]
    # незакрытые аргументы команд: откат до последней открытой скобки
    while cut.count('{') > cut.count('}'):
        cut = cut[:cut.rfind('{')]
    # недописанная команда в конце (…\taskpi, …\\)
    cut = re.sub(r'\\+[a-zA-Z]*$', '', cut)
    return cut.rstrip()


def tex_preview_html(source, limit=220):
    """Сокращённое HTML-превью условия для списков.

    Обрезает tex-исходник по безопасной границе (не внутри формулы
    или команды) и только потом преобразует в HTML — усечённого
    HTML или сломанных формул не бывает.
    """
    text = _COMMENT_RE.sub('', source or '').strip()
    if len(text) > limit:
        text = _safe_cut(text, limit) + '…'
    return tex_to_web_html(text)

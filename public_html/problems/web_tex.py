"""Преобразование LaTeX-текста задач в HTML для веб-страниц.

Формулы ($…$ и $$…$$) не трогаем — их рендерит KaTeX в браузере.
Обрабатываются «форматирующие» конструкции пакета egor, которые иначе
видны как сырой код: комментарии %, переносы \\ и \par, пометки на полях
(\annot, \annotnoframe, \oge, \fipi, \rev, \complex, \starred, \home),
\source, \textbit, неразрывный пробел ~, экранированные символы
(\%, \& …) и таблицы tabular (превращаются в HTML-таблицу).
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
_NOFRAME_OPEN = '\x07'
_NOFRAME_CLOSE = '\x08'
_SOURCE_OPEN = '\x0b'
_SOURCE_CLOSE = '\x0c'
_BOLDIT_OPEN = '\x0e'
_BOLDIT_CLOSE = '\x0f'

# Все разделители формул, которые рендерит KaTeX (static/js/math.js):
# $$…$$, \[…\], $…$, \(…\) — внутри них текст не преобразуем
_MATH_RE = re.compile(
    r'\$\$.*?\$\$|\\\[.*?\\\]|\$.*?\$|\\\(.*?\\\)', re.S)
_TABULAR_RE = re.compile(
    r'\\begin\{tabular\}\s*(\{[^{}]*\})?(.*?)\\end\{tabular\}', re.S)
_ARG = r'\{((?:[^{}]|\{[^{}]*\})*)\}'
_ANNOT_RE = re.compile(r'\\annot' + _ARG, re.S)
_NOFRAME_RE = re.compile(r'\\annotnoframe' + _ARG, re.S)
_SOURCE_RE = re.compile(r'\\source' + _ARG, re.S)
_TEXTBIT_RE = re.compile(r'\\textbit' + _ARG, re.S)
_COMMENT_RE = re.compile(r'(?<!\\)%[^\n]*')
_TASKPIC_RE = re.compile(r'\s*\\taskpic(?:\[[^\]]*\])?\{[^}]*\}')


def _wrap(open_marker, close_marker):
    return lambda m: open_marker + m.group(1).strip() + close_marker


# Команды egor.sty вне формул → маркеры (порядок важен: сперва алиасы,
# у которых нет аргументов, потом команды с аргументом)
_COMMANDS = [
    (re.compile(r'\\oge\b'), _ANNOT_OPEN + 'ОГЭ' + _ANNOT_CLOSE),
    (re.compile(r'\\fipi\b'), _ANNOT_OPEN + 'ФИПИ' + _ANNOT_CLOSE),
    # \rev = \annotnoframe{$\circlearrowright$} — пометка «повторение»
    (re.compile(r'\\rev\b'), _NOFRAME_OPEN + '↻' + _NOFRAME_CLOSE),
    (re.compile(r'\\(?:complex|starred)\b'),
     _NOFRAME_OPEN + '★' + _NOFRAME_CLOSE),
    (re.compile(r'\\home\b'), _NOFRAME_OPEN + '⌂' + _NOFRAME_CLOSE),
    (_ANNOT_RE, _wrap(_ANNOT_OPEN, _ANNOT_CLOSE)),
    (_NOFRAME_RE, _wrap(_NOFRAME_OPEN, _NOFRAME_CLOSE)),
    (_SOURCE_RE, _wrap(_SOURCE_OPEN, _SOURCE_CLOSE)),
    (_TEXTBIT_RE, _wrap(_BOLDIT_OPEN, _BOLDIT_CLOSE)),
]

# Замены в тексте вне формул (внутри $…$ всё это понимает KaTeX)
_UNESCAPE = [('\\%', '%'), ('\\&', '&'), ('\\_', '_'), ('\\#', '#'),
             ('\\,', ' ')]


def _sub_outside_math(pattern, repl, text):
    """pattern.sub(repl, text), но совпадения внутри формул не трогаются.

    Аргумент команды при этом может содержать формулу ($…$ внутри
    \\annot{…} остаётся и рендерится KaTeX уже внутри span).
    """
    spans = [m.span() for m in _MATH_RE.finditer(text)]

    def guarded(match):
        start = match.start()
        for a, b in spans:
            if a <= start < b:
                return match.group(0)
        return repl(match) if callable(repl) else repl

    return pattern.sub(guarded, text)


def _split_outside_math(text, pattern):
    """Разбиение по разделителю, стоящему вне формул.

    Нужен таблицам: перенос \\\\ внутри $\\begin{matrix}…$ в ячейке —
    часть формулы, а не конец строки таблицы.
    """
    spans = [m.span() for m in _MATH_RE.finditer(text)]
    parts = []
    last = 0
    for m in re.finditer(pattern, text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        parts.append(text[last:m.start()])
        last = m.end()
    parts.append(text[last:])
    return parts


def _plain(text):
    """Замены в фрагменте вне формул: переносы, ~, экранированные символы."""
    text = re.sub(r'\\par\b', _BR + _BR, text)
    text = text.replace('\\\\', _BR)
    text = re.sub(r'(?<!\\)~', _NBSP, text)
    for src, dst in _UNESCAPE:
        text = text.replace(src, dst)
    return text


def _markers_to_html(html):
    return (html
            .replace(_BR + _BR, '<br><br>')
            .replace(_BR, '<br>')
            .replace(_NBSP, '&nbsp;')
            .replace(_ANNOT_OPEN, '<span class="tex-annot">')
            .replace(_ANNOT_CLOSE, '</span>')
            .replace(_NOFRAME_OPEN,
                     '<span class="tex-annot tex-annot-noframe">')
            .replace(_NOFRAME_CLOSE, '</span>')
            .replace(_SOURCE_OPEN, '<span class="tex-source">')
            .replace(_SOURCE_CLOSE, '</span>')
            .replace(_BOLDIT_OPEN, '<b><i>')
            .replace(_BOLDIT_CLOSE, '</i></b>'))


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
    """tabular → <table>: строки по \\\\, ячейки по неэкранированному &.

    Разделители ищутся только вне формул: \\\\ и & внутри $…$
    (например, в matrix или cases в ячейке) принадлежат формуле.
    """
    body = body.replace('\\hline', '')
    rows = []
    for row in _split_outside_math(body, r'\\\\'):
        cells = [c.strip() for c in _split_outside_math(row, r'(?<!\\)&')]
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

    text = _sub_outside_math(_TABULAR_RE, stash, text)
    text = _sub_outside_math(_TASKPIC_RE, '', text)
    for pattern, repl in _COMMANDS:
        text = _sub_outside_math(pattern, repl, text)

    parts = []
    pos = 0
    for m in _MATH_RE.finditer(text):
        parts.append(_plain(text[pos:m.start()]))
        parts.append(m.group(0))
        pos = m.end()
    parts.append(_plain(text[pos:]))

    html = _markers_to_html(escape(''.join(parts)))
    for i, body in enumerate(tables):
        html = html.replace(f'\x05{i}\x06', _table_html(body))
    return mark_safe(html)


def _safe_cut(text, limit):
    """Обрезка tex-исходника, не разрезающая формулу или команду посередине."""
    # граница внутри формулы любого вида ($…$, $$…$$, \(…\), \[…\]) —
    # откат к началу этой формулы
    for m in _MATH_RE.finditer(text):
        if m.start() < limit < m.end():
            limit = m.start()
            break
        if m.start() >= limit:
            break
    cut = text[:limit]
    # незакрытая формула $… (непарный $ в самом исходнике): откат до начала
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

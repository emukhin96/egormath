"""Утилиты для работы с LaTeX-текстом задач."""

import re

# Спецсимволы LaTeX для экранирования "обычного" текста (заголовки и т.п.)
_LATEX_ESCAPE = {
    '\\': r'\textbackslash{}',
    '&': r'\&',
    '%': r'\%',
    '$': r'\$',
    '#': r'\#',
    '_': r'\_',
    '{': r'\{',
    '}': r'\}',
    '~': r'\textasciitilde{}',
    '^': r'\textasciicircum{}',
}

_escape_re = re.compile('|'.join(re.escape(c) for c in _LATEX_ESCAPE))


def escape_latex(text):
    """Экранирует спецсимволы LaTeX в обычном тексте (не в тексте задач!)."""
    if not text:
        return ''
    return _escape_re.sub(lambda m: _LATEX_ESCAPE[m.group()], text)


_ITEM_RE = re.compile(r'\\item\b')


def split_items(text):
    """Разбивает LaTeX-текст подпунктов по \\item; текст до первого \\item
    (если есть) считается первым подпунктом. Служебные хвостовые знаки
    срезаются (см. strip_subitem_punct): фрагменты перечисления хранятся
    без знака, законченные предложения — со своим знаком."""
    chunks = [strip_subitem_punct(c) for c in _ITEM_RE.split(text)]
    return [c for c in chunks if c]


def strip_subitem_punct(text):
    """Срезает знак препинания в конце подпункта — если он «служебный».

    Подпункт-предложение (начинается с заглавной буквы и заканчивается
    «.») сохраняет точку: «Приведите пример.» — законченная фраза.
    Вопросительный знак сохраняем всегда: «чему равен $x$?» и «$x>0$?»
    меняют смысл, если заменить «?» на «;»/«.». Фрагменты перечисления
    хранятся без служебных «;»/«.» — система расставляет их при выводе.
    """
    text = text.strip()
    if not text:
        return text
    if text.endswith('?'):
        return text
    if text[0].isupper() and text.endswith('.'):
        return text
    if text.endswith((';', '.')):
        text = text[:-1].rstrip()
    return text


# Уже обёрнутые формулы не трогаем (те же разделители, что KaTeX)
_MATH_SPAN_RE = re.compile(
    r'\$\$.*?\$\$|\\\[.*?\\\]|\$.*?\$|\\\(.*?\\\)', re.S)

# Текстовые команды — не повод оборачивать в $…$
_TEXT_CMD = (
    r'item|par|newline|textbf|textit|emph|text|annot|annotnoframe|'
    r'begin|end|section|subsection|taskpic|label|ref|cite|'
    r'hspace|vspace|newline|noindent'
)
_SEED_RE = re.compile(
    r'\\(?!(?:' + _TEXT_CMD + r')\b)[a-zA-Z]+\*?'
    r'|[A-Za-z0-9)]\s*[\^_]'
    r'|[A-Za-z0-9]\s*=\s*(?:[A-Za-z0-9\\(+\-]|\\)'
)
_MATHY_RE = re.compile(r"[A-Za-z0-9\\{}\(\)\[\]\^_+\-=<>|/*']")


def wrap_bare_math(text):
    """Оборачивает голый TeX в $…$, уже обёрнутые формулы не трогает.

    Модель часто пишет ``\\frac`` и ``a^2`` без долларов — KaTeX тогда
    показывает сырой код. Промпт это не гарантирует; обёртка детерминирована
    и идемпотентна.
    """
    if not text:
        return text
    if text.count('$') % 2:
        return text
    parts = []
    last = 0
    for match in _MATH_SPAN_RE.finditer(text):
        parts.append(_wrap_chunk(text[last:match.start()]))
        parts.append(match.group(0))
        last = match.end()
    parts.append(_wrap_chunk(text[last:]))
    return ''.join(parts)


def _wrap_chunk(chunk):
    if not chunk or not _SEED_RE.search(chunk):
        return chunk
    spans = []
    for match in _SEED_RE.finditer(chunk):
        start, end = _expand_math(chunk, match.start(), match.end())
        if start >= end:
            continue
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        elif spans and not chunk[spans[-1][1]:start].strip():
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    if not spans:
        return chunk
    out = []
    last = 0
    for start, end in spans:
        out.append(chunk[last:start])
        piece = chunk[start:end].strip()
        if piece:
            out.append('$%s$' % piece)
        last = end
    out.append(chunk[last:])
    return ''.join(out)


def _expand_math(text, start, end):
    while start > 0 and _can_extend(text, start - 1):
        start -= 1
    length = len(text)
    while end < length and _can_extend(text, end):
        end += 1
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _can_extend(text, index):
    char = text[index]
    if char in '\n\r':
        return False
    if char.isspace():
        return True
    if _MATHY_RE.match(char):
        return True
    if char == '.':
        left = text[index - 1] if index else ''
        right = text[index + 1] if index + 1 < len(text) else ''
        return left.isdigit() and right.isdigit()
    return False


def strip_latex(text):
    """
    Грубо "раздевает" LaTeX-текст до обычного текста для поиска по ключевым
    словам: убирает команды, скобки, окружения; математику оставляет как есть
    (внутри могут быть значимые числа).
    """
    if not text:
        return ''
    s = text
    s = re.sub(r'\\begin\{[^}]*\}|\\end\{[^}]*\}', ' ', s)
    s = re.sub(r'\\[a-zA-Z@]+\*?', ' ', s)   # команды
    s = re.sub(r'[{}\[\]$&%#_^~]', ' ', s)   # структурные символы
    s = re.sub(r'\\\\|\\[,;!:]', ' ', s)     # переносы и пробелы LaTeX
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

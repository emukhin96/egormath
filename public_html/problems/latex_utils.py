"""Утилиты для работы с LaTeX-текстом задач."""

import json
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


# JSON съедает \\f/\\t/\\b/\\r как управляющие символы (Gemini часто
# пишет "\frac" вместо "\\frac" в JSON). Восстанавливаем, только если
# дальше идут буквы команды: \x0c+rac → \frac, tab+imes → \times.
# Настоящие \r\n и перевод строки перед кириллицей не трогаем.
_JSON_EATEN_LATEX = (
    (re.compile('\x0c(?=[A-Za-z])'), r'\\f'),
    (re.compile('\t(?=[A-Za-z])'), r'\\t'),
    (re.compile('\x08(?=[A-Za-z])'), r'\\b'),
    (re.compile('\r(?=[A-Za-z])'), r'\\r'),
    # \\n+eq → \neq; обычный абзац (цифра/кириллица) не совпадает
    (re.compile('\n(?=(?:eq|ewline|otin|ot\\b|eg\\b|u\\b|abla|i\\b))'),
     r'\\n'),
)


def restore_json_eaten_latex(text):
    """Вернуть \\frac/\\times, которые json.loads превратил в form feed/tab."""
    if not text:
        return text
    for pattern, repl in _JSON_EATEN_LATEX:
        text = pattern.sub(repl, text)
    return text


# JSON-эскейпы, которые json.loads превращает в управляющие символы.
# Внутри строки "\frac" — это LaTeX, не form feed: удваиваем слэш до разбора.
_JSON_CTRL_ESC = frozenset('nrtbf')
_HEX = frozenset('0123456789abcdefABCDEF')


def protect_latex_json_escapes(raw):
    """В строках JSON удвоить слэш у TeX-команд, не трогая \\\" и \\\\.

    Gemini часто пишет ``\\frac`` как один слэш. Тогда ``json.loads``
    читает ``\\f`` как form feed. Здесь смотрим сырой текст: если после
    ``\\f``/``\\t``/``\\b``/``\\r`` идёт буква команды — вставляем второй
    слэш. ``\\n`` не трогаем: в корректном JSON это перевод строки
    (``hello\\nWorld``), его не отличить от ``\\neq``. ``\\r\\n`` тоже
    оставляем. Уже экранированное ``\\\\frac`` не меняется: ``\\\\``
    съедается как экранированный слэш, ``f`` остаётся буквой.
    """
    if not raw:
        return raw
    out = []
    i = 0
    n = len(raw)
    in_string = False
    while i < n:
        ch = raw[i]
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue
        if ch == '\\' and i + 1 < n:
            nxt = raw[i + 1]
            if nxt in '"\\/':
                out.append(raw[i:i + 2])
                i += 2
                continue
            if nxt == 'u':
                hexpart = raw[i + 2:i + 6]
                after = raw[i + 6] if i + 6 < n else ''
                if (len(hexpart) == 4 and all(c in _HEX for c in hexpart)
                        and not after.isalpha()):
                    out.append(raw[i:i + 6])
                    i += 6
                    continue
                # \underline / \union или \u без 4 hex — TeX, не юникод
                out.append('\\\\')
                out.append('u')
                i += 2
                continue
            if nxt in _JSON_CTRL_ESC:
                after = raw[i + 2] if i + 2 < n else ''
                if nxt == 'n' or (nxt == 'r' and after == 'n'):
                    out.append(raw[i:i + 2])
                    i += 2
                    continue
                if after.isalpha():
                    out.append('\\\\')
                    out.append(nxt)
                    i += 2
                    continue
                out.append(raw[i:i + 2])
                i += 2
                continue
            if nxt.isalpha():
                out.append('\\\\')
                out.append(nxt)
                i += 2
                continue
        if ch == '"':
            in_string = False
        out.append(ch)
        i += 1
    return ''.join(out)


def loads_neuro_json(raw):
    """json.loads с защитой TeX-команд в строках (см. protect_latex_json_escapes)."""
    return json.loads(protect_latex_json_escapes(raw))


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

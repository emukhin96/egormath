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
    хранятся без служебных «;»/«,»/«.» — система расставляет их при выводе.
    """
    text = text.strip()
    if not text:
        return text
    if text.endswith('?'):
        return text
    if text[0].isupper() and text.endswith('.'):
        return text
    if text.endswith((';', '.', ',')):
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


# Свой разбор JSON нейросети: json.loads нельзя — \\, / \\{ ломают его,
# а \\frac/\\neq он превращает в form feed и перевод строки.
# Штатные эскейпы (\\n \\t \\r \\b \\f) декодируем как JSON, если это не
# известная TeX-команда (\\neq, \\frac, \\times, \\right, …).
# Настоящий перевод строки внутри кавычек разрешён (как в JSON5).
_FENCE_RE = re.compile(r'^```(?:json)?\s*|\s*```$', re.I)
_HEX = frozenset('0123456789abcdefABCDEF')
_JSON_ESC = {
    'b': '\b',
    'f': '\f',
    'n': '\n',
    'r': '\r',
    't': '\t',
}
# TeX-команды, чьё имя начинается с буквы JSON-эскейпа. \\n + «шаг» —
# перевод строки; \\n + eq — \\neq.
_TEX_JSON_COLLISIONS = frozenset({
    'nabla', 'natural', 'ne', 'neg', 'neq', 'newcommand', 'newline',
    'nexists', 'ngtr', 'ni', 'nleftarrow', 'nLeftrightarrow', 'nleq',
    'nleqslant', 'nless', 'nmid', 'noindent', 'nparallel', 'nprec',
    'nRightarrow', 'nrightarrow', 'nsim', 'nsubseteq', 'nsucc',
    'nsupseteq', 'nu', 'nvDash', 'nvdash', 'nVdash', 'not', 'notin',
    'normalsize',
    'tan', 'tanh', 'tau', 'tbinom', 'text', 'textbf', 'textbackslash',
    'textit', 'textrm', 'textsc', 'textsf', 'textsl', 'textnormal',
    'texttt', 'textup', 'tfrac', 'theta', 'thickspace', 'thinspace',
    'tilde', 'times', 'to', 'top', 'triangle', 'triangleleft',
    'trianglelefteq', 'triangleq', 'triangleright', 'trianglerighteq',
    'widetilde',
    'fbox', 'flat', 'flushleft', 'flushright', 'footnotesize',
    'forall', 'frac',
    'backslash', 'bar', 'because', 'begin', 'beta', 'bfseries',
    'big', 'Big', 'bigcap', 'bigcup', 'bigg', 'Bigg', 'biggl',
    'Biggl', 'biggr', 'Biggr', 'bigl', 'Bigl', 'bigoplus',
    'bigotimes', 'bigr', 'Bigr', 'bigvee', 'bigwedge', 'binom',
    'bigskip', 'bot', 'bowtie', 'bullet',
    'mathbb', 'mathbf', 'mathcal', 'mathfrak',
    'mathit', 'mathrm', 'mathscr', 'mathsf', 'mathtt', 'boldsymbol',
    'rangle', 'rceil', 'restriction', 'rfloor', 'rho', 'right',
    'rightarrow', 'Rightarrow', 'rightharpoondown', 'rightharpoonup',
    'rightleftharpoons', 'rmoustache', 'rule', 'rvert',
})


class NeuroJsonError(ValueError):
    """Ответ модели нельзя разобрать даже как TeX-JSON."""


def loads_neuro_json(raw):
    """Разобрать JSON черновика нейросети, сохраняя TeX-команды."""
    if not isinstance(raw, str):
        raise NeuroJsonError('ожидалась JSON-строка')
    text = _FENCE_RE.sub('', raw.strip())
    return _NeuroJson(text).parse_value()


class _NeuroJson:
    def __init__(self, text):
        self.s = text
        self.i = 0
        self.n = len(text)

    def peek(self):
        return self.s[self.i] if self.i < self.n else ''

    def skip_ws(self):
        while self.i < self.n and self.s[self.i] in ' \t\r\n':
            self.i += 1

    def parse_value(self):
        self.skip_ws()
        ch = self.peek()
        if ch == '{':
            return self._object()
        if ch == '[':
            return self._array()
        if ch == '"':
            return self._string()
        if ch == 't':
            return self._literal('true', True)
        if ch == 'f':
            return self._literal('false', False)
        if ch == 'n':
            return self._literal('null', None)
        if ch == '-' or ch.isdigit():
            return self._number()
        raise NeuroJsonError(
            'неожиданный символ %r на позиции %d' % (ch, self.i))

    def _literal(self, word, value):
        if self.s[self.i:self.i + len(word)] != word:
            raise NeuroJsonError('ожидалось %s' % word)
        self.i += len(word)
        return value

    def _object(self):
        self.i += 1
        result = {}
        self.skip_ws()
        if self.peek() == '}':
            self.i += 1
            return result
        while True:
            self.skip_ws()
            if self.peek() != '"':
                raise NeuroJsonError('ожидался ключ')
            key = self._string()
            self.skip_ws()
            if self.peek() != ':':
                raise NeuroJsonError('ожидалось :')
            self.i += 1
            result[key] = self.parse_value()
            self.skip_ws()
            if self.peek() == ',':
                self.i += 1
                self.skip_ws()
                if self.peek() == '}':
                    self.i += 1
                    return result
                continue
            if self.peek() == '}':
                self.i += 1
                return result
            raise NeuroJsonError('ожидалась запятая или }')

    def _array(self):
        self.i += 1
        result = []
        self.skip_ws()
        if self.peek() == ']':
            self.i += 1
            return result
        while True:
            result.append(self.parse_value())
            self.skip_ws()
            if self.peek() == ',':
                self.i += 1
                self.skip_ws()
                if self.peek() == ']':
                    self.i += 1
                    return result
                continue
            if self.peek() == ']':
                self.i += 1
                return result
            raise NeuroJsonError('ожидалась запятая или ]')

    def _string(self):
        self.i += 1
        out = []
        while self.i < self.n:
            ch = self.s[self.i]
            self.i += 1
            if ch == '"':
                return ''.join(out)
            if ch != '\\':
                out.append(ch)
                continue
            if self.i >= self.n:
                raise NeuroJsonError('обрыв строки после \\')
            nxt = self.s[self.i]
            self.i += 1
            if nxt == '"':
                out.append('"')
            elif nxt == '\\':
                out.append('\\')
            elif nxt == '/':
                out.append('/')
            elif nxt == 'u':
                hexpart = self.s[self.i:self.i + 4]
                after = self.s[self.i + 4] if self.i + 4 < self.n else ''
                if (len(hexpart) == 4 and all(c in _HEX for c in hexpart)
                        and not after.isalpha()):
                    out.append(chr(int(hexpart, 16)))
                    self.i += 4
                else:
                    out.append('\\')
                    out.append('u')
            elif nxt in _JSON_ESC:
                name = nxt
                j = self.i
                while j < self.n and self.s[j].isalpha():
                    name += self.s[j]
                    j += 1
                if name in _TEX_JSON_COLLISIONS:
                    out.append('\\')
                    out.append(nxt)
                else:
                    out.append(_JSON_ESC[nxt])
            else:
                # \, \{ \left \alpha — не JSON-эскейпы, оставляем TeX
                out.append('\\')
                out.append(nxt)
        raise NeuroJsonError('незакрытая строка')

    def _number(self):
        start = self.i
        if self.peek() == '-':
            self.i += 1
        if not self.peek().isdigit():
            raise NeuroJsonError('ожидалось число')
        while self.peek().isdigit():
            self.i += 1
        if self.peek() == '.':
            self.i += 1
            while self.peek().isdigit():
                self.i += 1
        if self.peek() in 'eE':
            self.i += 1
            if self.peek() in '+-':
                self.i += 1
            while self.peek().isdigit():
                self.i += 1
        return json_number(self.s[start:self.i])


def json_number(text):
    if any(c in text for c in '.eE'):
        return float(text)
    return int(text)


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


def ensure_displaystyle_fractions(text):
    """В инлайн-формулах с ``\\frac`` добавляет ``\\displaystyle``.

    Display-математика (``$$`` / ``\\[``) уже крупная. Повторный вызов
    не дублирует команду.
    """
    if not text or '\\frac' not in text:
        return text

    def repl(match):
        span = match.group(0)
        if span.startswith('$$') or span.startswith('\\['):
            return span
        if '\\frac' not in span or '\\displaystyle' in span:
            return span
        if span.startswith('$'):
            return r'$\displaystyle ' + span[1:]
        if span.startswith('\\('):
            return r'\(\displaystyle ' + span[2:]
        return span

    return _MATH_SPAN_RE.sub(repl, text)


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

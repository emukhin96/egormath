"""Числовые слоты маски: число, упорядоченная пара, конечное множество,
числовой промежуток. Разбор строится на примитивах ``check_answer``
(``parse_number``, ``parse_interval``), сравнение — точное для дробей и с
допуском для иррациональных значений (``\\sqrt{2}`` и т.п.)."""
import math
import re
from fractions import Fraction

from ..check_answer import _strip_var, normalize, parse_number

EMPTY_WORDS = ('∅', '{}', 'нет', 'нет решений', 'решений нет', 'нет корней',
               'корней нет', 'пустое множество', 'none')
ALL_WORDS = ('r', '\\mathbb{r}', 'ℝ', 'любое число', 'любое', 'все числа',
             'x - любое', 'x любое', 'вся прямая', 'вся числовая прямая',
             'числовая прямая')

_VAR = r'[a-zA-Zа-яА-Я](?:_\{?\d+\}?)?'
_IN_RE = re.compile(r'^' + _VAR + r'\s*(?:\\in|∈)\s*')
_INTERVAL_TOKEN_RE = re.compile(
    r'[(\[]\s*[^;()\[\]]+?\s*;\s*[^;()\[\]]+?\s*[)\]]')
_UNION_RE = re.compile(r'\s*(?:∪|,|;|\bили\b|\bor\b)\s*')
_AND_RE = re.compile(r'\s+(?:\bи\b|\band\b)\s+', re.I)
_OP = r'(<=|>=|<|>)'
_CHAIN_RE = re.compile(
    r'^(.+?)\s*' + _OP + r'\s*' + _VAR + r'\s*' + _OP + r'\s*(.+)$')
_LEFT_RE = re.compile(r'^' + _VAR + r'\s*(<=|>=|<|>|!=)\s*(.+)$')
_RIGHT_RE = re.compile(r'^(.+?)\s*(<=|>=|<|>|!=)\s*' + _VAR + r'$')

INF = float('inf')


# --- числа ---------------------------------------------------------------------

def numeric_value(text):
    """Строка → Fraction (точно) или float (иррациональное); None — не число.
    Понимает школьные дроби и любое числовое LaTeX-выражение без переменных."""
    # MathLive сокращает односимвольный аргумент: \sqrt8 вместо \sqrt{8}.
    text = re.sub(r'(\\sqrt(?:\[[^\]]+\])?)\s*([0-9])', r'\1{\2}', text or '')
    text = normalize(_strip_var(text))
    text = re.sub(r'\\operatorname\{arctg\}|\\arctg\b', r'\\arctan', text)
    if not text:
        return None
    value = parse_number(text)
    if value is not None:
        return value
    from . import expressions
    # Lark-грамматика не распознаёт константу π: вводим свободный
    # временный символ и заменяем его константой после безопасного разбора.
    pi_pattern = r'\\pi(?![A-Za-z])|π|\bpi\b'
    marker = None
    if re.search(pi_pattern, text):
        from sympy import Symbol, pi
        marker = next((c for c in 'QPXYZABC' if c not in text), None)
        if marker is None:
            return None
        text = re.sub(pi_pattern, marker, text)
    tree = expressions.raw_tree(text)
    if tree is None:
        return None
    # Сокращение x/x не превращает запись с переменной в числовую границу.
    pending = [tree]
    while pending:
        node = pending.pop()
        if expressions._is_tree(node):
            pending.extend(node.children)
            # Сокращение 0*sqrt(-1) не устраняет недопустимый вещественный корень.
            # Проверяем каждый исходный корень до вычисления всего выражения.
            if node.data == 'square_root':
                root = expressions.evaluate(expressions.resolve(node))
                if marker and root is not None:
                    root = root.subs(Symbol(marker), pi)
                if (root is None or root.is_real is not True
                        or root.is_finite is not True):
                    return None
        elif expressions._is_symbol_token(node) and str(node) != marker:
            return None
    expr = expressions.evaluate(expressions.resolve(tree))
    if marker and expr is not None:
        expr = expr.subs(Symbol(marker), pi)
    if expr is None or not getattr(expr, 'is_number', False):
        return None
    try:
        if expr.is_Rational:
            return Fraction(int(expr.p), int(expr.q))
        result = float(expr.evalf())
    except Exception:  # noqa: BLE001
        return None
    if not math.isfinite(result):
        return None
    return result


def _as_finite_float(value):
    """float, если значение помещается в double; иначе None (в т.ч. inf)."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def numbers_equal(a, b, tolerance=None):
    if a is None or b is None:
        return False
    # Сначала точное сравнение дробей: 10^{999} не влезает в float.
    if isinstance(a, Fraction) and isinstance(b, Fraction):
        if tolerance is None:
            return a == b
        try:
            tol = tolerance if isinstance(tolerance, Fraction) else Fraction(tolerance)
        except (TypeError, ValueError, OverflowError, ZeroDivisionError):
            return False
        if tol < 0:
            return False
        return abs(a - b) <= tol
    fa, fb = _as_finite_float(a), _as_finite_float(b)
    if fa is None or fb is None:
        return False
    if tolerance is None:
        tolerance = 1e-9 * max(1.0, abs(fb))
    try:
        return abs(fa - fb) <= float(tolerance)
    except (TypeError, ValueError, OverflowError):
        return False


def _unique_numbers(values, tolerance=None, *, equal=None):
    """Убрать численно равные повторы: ``±0`` и ``0; 0`` — одно число."""
    equal = equal or numbers_equal
    out = []
    for value in values:
        if not any(equal(value, other, tolerance) for other in out):
            out.append(value)
    return out


def _multiset_equal(items_a, items_b, tolerance=None, equal=numbers_equal):
    if len(items_a) != len(items_b):
        return False
    rest = list(items_b)
    for item in items_a:
        for i, other in enumerate(rest):
            if equal(item, other, tolerance):
                rest.pop(i)
                break
        else:
            return False
    return True


# --- множество чисел и пары ----------------------------------------------------

MAX_COLLECTION_LEN = 2000
MAX_COLLECTION_ITEMS = 64
MAX_COLLECTION_DEPTH = 16
_SET_START_RE = re.compile(
    r'(?:^|∪|\\cup|[,;({]|\bили|\bor|\bи|\band|'
    r'\\setminus|\\backslash|∖|\\in|∈|=)\s*$', re.I)
_DIFFERENCE_RE = re.compile(
    r'^(?:r|ℝ|\\mathbb\s*(?:\{r\}|r))\s*'
    r'(?:\\setminus|\\backslash|∖)\s*(\{.*\})$', re.I)


def _collection_text(text):
    """Сохранить разделители явного множества до десятичной нормализации.

    В {0,1} запятая разделяет элементы; во вложенной дроби или MathLive
    {,} она остаётся десятичной. Аргументы команд LaTeX — не множества.
    """
    text = (text or '').replace('$', ' ')
    if len(text) > MAX_COLLECTION_LEN or '\x00' in text:
        return None
    for command in (r'\left', r'\right', r'\displaystyle'):
        text = text.replace(command, '')
    for command in (r'\,', r'\;', r'\:', r'\!', r'\ ', '~'):
        text = text.replace(command, ' ')
    # Сохраняем происхождение явных скобок \{…\}, даже внутри LaTeX.
    explicit, out = set(), []
    i = 0
    while i < len(text):
        if text[i:i+2] in (r'\{', r'\}'):
            if text[i+1] == '{':
                explicit.add(len(out))
            out.append(text[i+1])
            i += 2
        else:
            out.append(text[i])
            i += 1
    text = ''.join(out)
    chars, stack = list(text), []
    for i, char in enumerate(text):
        if char in '{([':
            if i in explicit and stack and stack[-1][0] == '{' and not stack[-1][1]:
                return None  # Множество внутри числителя/знаменателя — не число.
            is_set = char == '{' and (i in explicit or bool(_SET_START_RE.search(text[:i])))
            # Если элементы уже разделены «;», запятая внутри — десятичная:
            # \{-2,5; 1\} — это {-2,5; 1}, а не {-2; 5; 1}.
            comma_separates = is_set and not _has_top_level_semicolon(text, i)
            stack.append((char, is_set, comma_separates))
            if len(stack) > MAX_COLLECTION_DEPTH:
                return None
        elif char in '})]':
            if not stack or (char == '}') != (stack[-1][0] == '{'):
                return None
            stack.pop()
        elif char == ',' and stack and stack[-1][:2] == ('{', True) and stack[-1][2]:
            if text[max(0, i-1):i+2] != '{,}':
                chars[i] = ';'
    if stack:
        return None
    return normalize(''.join(chars))


def _has_top_level_semicolon(text, start):
    """Есть ли «;» на верхнем уровне скобки, открытой в позиции start."""
    depth = 0
    for char in text[start:]:
        if char in '{([':
            depth += 1
        elif char in '})]':
            depth -= 1
            if depth == 0:
                return False
        elif char == ';' and depth == 1:
            return True
    return False


def _split_top(text, separator):
    """Делить только вне скобок, с ограничением вложенности и числа частей."""
    parts, start, depth = [], 0, 0
    i = 0
    while i < len(text):
        char = text[i]
        if char in '({[':
            depth += 1
            if depth > MAX_COLLECTION_DEPTH:
                return None
        elif char in ')}]':
            depth -= 1
            if depth < 0:
                return None
        if depth == 0:
            match = separator.match(text, i)
            if match:
                parts.append(text[start:i].strip())
                if len(parts) >= MAX_COLLECTION_ITEMS:
                    return None
                i = match.end()
                start = i
                continue
        i += 1
    if depth:
        return None
    parts.append(text[start:].strip())
    return parts


def _split_items(text):
    text = text.strip()
    unwrapped = text
    while unwrapped.startswith('(') and unwrapped.endswith(')'):
        depth = 0
        for i, char in enumerate(unwrapped):
            depth += (char == '(') - (char == ')')
            if depth == 0:
                break
        if i != len(unwrapped)-1:
            break
        unwrapped = unwrapped[1:-1].strip()
    if unwrapped.startswith('{') and unwrapped.endswith('}'):
        text = unwrapped
    if text.startswith('{') and text.endswith('}'):
        text = text[1:-1].strip()
    if not text or text.lower() in EMPTY_WORDS:
        return []
    parts = _split_top(text, re.compile(r'[;,]'))
    return [p for p in parts if p] if parts is not None else None


def parse_set(text, *, value_parser=None, equal=None):
    """Конечное множество чисел; один ± в элементе означает обе ветви."""
    value_parser = value_parser or numeric_value
    text = _collection_text(text)
    if not text:
        return None
    items = _split_items(text)
    if items is None:
        return None
    values = []
    for item in items:
        item = _strip_var(item).replace('±', r'\pm')
        count = item.count(r'\pm')
        if count > 1 or len(item) > 300:
            return None
        branches = [item.replace(r'\pm', sign) for sign in ('+', '-')] if count else [item]
        for branch in branches:
            value = value_parser(branch)
            if value is None:
                return None
            values.append(value)
            if len(values) > MAX_COLLECTION_ITEMS:
                return None
    return _unique_numbers(values, equal=equal)


def sets_equal(a, b, tolerance=None):
    return _multiset_equal(
        _unique_numbers(a, tolerance), _unique_numbers(b, tolerance), tolerance)


def _pair_text(text):
    """Снять оформление, сохранив координатные и десятичные запятые."""
    text = text or ''
    if len(text) > MAX_COLLECTION_LEN or '\x00' in text:
        return None
    text = text.replace('$', ' ')
    for command in (r'\left', r'\right', r'\displaystyle',
                    r'\,', r'\;', r'\:', r'\!', r'\ ', '~'):
        text = text.replace(command, ' ')
    brackets = _pair_brackets(text)
    if brackets is None:
        return None
    for match in re.finditer(r'\\\{', text):
        if any(start < match.start() < end for start, end in brackets.items()):
            return None  # Явное множество внутри координаты/дроби — не число.
    return text.replace(r'\{', '{').replace(r'\}', '}').strip()


def _pair_brackets(text):
    """Точные пары скобок; здесь смешанные скобки промежутков недопустимы."""
    stack, ends = [], {}
    opening = {')': '(', ']': '[', '}': '{'}
    for i, char in enumerate(text):
        if char in '({[':
            stack.append((char, i))
            if len(stack) > MAX_COLLECTION_DEPTH:
                return None
        elif char in ')}]':
            if not stack or stack[-1][0] != opening[char]:
                return None
            _, start = stack.pop()
            ends[start] = i
    return None if stack else ends


def _pair_coordinates(group, *, explicit, coordinate_comma, value_parser=None):
    """Разделить кортеж до normalize; имена x/y/z нельзя просто выкинуть."""
    parts = _split_top(group, re.compile(';'))
    if parts is not None and len(parts) == 1 and explicit and coordinate_comma:
        parts = _split_top(group, re.compile(','))
        if parts is not None and len(parts) != 2:
            return None  # (2,5,-3) неоднозначно: не угадываем десятичную запятую.
    if parts is None or not 2 <= len(parts) <= MAX_COLLECTION_ITEMS:
        return None
    if any(not p or len(p) > 300 for p in parts):
        return None
    # В координатах допустима только полная именованная запись x/y[/z].
    # Например, (y=-4;x=3) — это (3;-4), а не (-4;3).
    if any('=' in p for p in parts):
        expected = ('x', 'y', 'z')[:len(parts)]
        named = {}
        for part in parts:
            match = re.fullmatch(r'([xyz])\s*=\s*([^=]+)', part)
            if not match or match[1] in named:
                return None
            named[match[1]] = match[2]
        if len(parts) > 3 or set(named) != set(expected):
            return None
        parts = [named[name] for name in expected]
    value_parser = value_parser or numeric_value
    values = [value_parser(p) for p in parts]
    return tuple(values) if all(v is not None for v in values) else None


def parse_pairs(text, *, coordinate_comma=True, value_parser=None, equal=None):
    """Множество упорядоченных кортежей, включая {…} и A×B.

    ``(2,5; -3)`` содержит десятичную запятую; ``(2.5,-3)`` —
    координатную. Свободный автоподбор отключает второй вариант, поскольку
    без контекста пары запятая может принадлежать промежутку или числу.
    """
    text = _pair_text(text)
    if not text:
        return None
    ends = _pair_brackets(text)
    if ends is None:
        return None
    product = _split_top(text, re.compile(r'\\times(?![A-Za-z])|×'))
    if product is None:
        return None
    if len(product) > 1:
        if len(product) != 2:
            return None
        factors = []
        for factor in product:
            brackets = _pair_brackets(factor)
            if not factor.startswith('{') or brackets.get(0) != len(factor)-1 \
                    or '=' in factor:
                return None
            values = parse_set(factor, value_parser=value_parser, equal=equal)
            if values is None:
                return None
            factors.append(values)
        if len(factors[0]) * len(factors[1]) > MAX_COLLECTION_ITEMS:
            return None
        return [(x, y) for x in factors[0] for y in factors[1]]
    wrapped_set = text.startswith('{') and ends.get(0) == len(text)-1
    if wrapped_set:
        text = text[1:-1].strip()
        if not text.startswith('('):
            return None  # {1;2} — множество чисел, не упорядоченная пара.
        ends = _pair_brackets(text)
    if text.startswith('(') and ends.get(0) == len(text)-1:
        pair = _pair_coordinates(text[1:-1], explicit=True,
                                 coordinate_comma=coordinate_comma, value_parser=value_parser)
        return [pair] if pair is not None else None
    groups = _split_top(text, re.compile('[;,]'))
    if groups is None or any(not group for group in groups):
        return None
    pairs = []
    for group in groups:
        brackets = _pair_brackets(group)
        if not group.startswith('(') or brackets.get(0) != len(group)-1:
            # Единственный кортеж без внешних скобок: 2,5; -3.
            if wrapped_set:
                return None
            pair = _pair_coordinates(text, explicit=False, coordinate_comma=False,
                                     value_parser=value_parser)
            return [pair] if pair is not None else None
        pair = _pair_coordinates(group[1:-1], explicit=True,
                                 coordinate_comma=coordinate_comma, value_parser=value_parser)
        if pair is None:
            if wrapped_set:
                return None
            # Скобки могут окружать только число: (9/10); (0).
            pair = _pair_coordinates(text, explicit=False, coordinate_comma=False,
                                     value_parser=value_parser)
            return [pair] if pair is not None else None
        pairs.append(pair)
    return pairs if pairs and len({len(p) for p in pairs}) == 1 else None


def _pair_equal(a, b, tolerance=None):
    return len(a) == len(b) and all(
        numbers_equal(x, y, tolerance) for x, y in zip(a, b))


def pairs_equal(a, b, tolerance=None, *, unordered=False):
    # Для длин сторон порядок внутри варианта не задан. Координаты
    # остаются упорядоченными, пока редактор явно не включил эту опцию.
    if unordered:
        # Канонический порядок исключает зависимость жадного сравнения
        # от ввода при близких float-значениях. Fraction остаются точными.
        a = sorted(tuple(sorted(pair)) for pair in a)
        b = sorted(tuple(sorted(pair)) for pair in b)
    compare = _pair_equal

    def unique(pairs):
        out = []
        for pair in pairs:
            if not any(compare(pair, other, tolerance) for other in out):
                out.append(pair)
        return out
    return _multiset_equal(unique(a), unique(b), tolerance, equal=compare)


# --- числовые промежутки -------------------------------------------------------

_INTERVAL_PARSE_RE = re.compile(
    r'^([(\[])\s*(.+?)\s*;\s*(.+?)\s*([)\]])$')


def _bound_value(text):
    """Конец промежутка: Fraction, float (иррациональное) или ±inf; None."""
    text = normalize(text)
    if '=' in text:
        return None
    # «- \infty» с пробелом после знака — та же бесконечность
    compact = re.sub(r'\s+', '', text)
    if re.fullmatch(r'[+-]?(?:\\infty|inf|бесконечность|беск)', compact, re.I):
        return -INF if compact.startswith('-') else INF
    return numeric_value(text)


def _parse_interval_token(token):
    """Скобочная запись с дробями и иррациональными концами."""
    m = _INTERVAL_PARSE_RE.match(token.strip())
    if not m:
        return None
    lo, hi = _bound_value(m.group(2)), _bound_value(m.group(3))
    if lo is None or hi is None:
        return None
    left = '(' if lo == -INF else m.group(1)
    right = ')' if hi == INF else m.group(4)
    return (lo, hi, left, right)


def _bound(op, value, is_low):
    """``<``/``<=`` и значение → (граница, скобка)."""
    closed = op.endswith('=')
    if is_low:
        return value, '[' if closed else '('
    return value, ']' if closed else ')'


_AFFINE_TOKEN_RE = re.compile(r'\\frac|[0-9]+(?:\.[0-9]+)?|[a-zA-Zа-яА-Я]|[()+*/{}-]')
_COMPARE_RE = re.compile(r'(<=|>=|!=|<|>|=)')


class _AffineParser:
    """Малый парсер a*x+b на Fraction, без символьного вычислителя."""

    def __init__(self, text):
        compact = re.sub(r'\s+', '', text)
        self.tokens = _AFFINE_TOKEN_RE.findall(compact)
        if ''.join(self.tokens) != compact or len(compact) > 300 or len(self.tokens) > 128:
            raise ValueError
        self.index = 0
        self.variables = set()

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else ''

    def take(self):
        token = self.peek()
        if not token:
            raise ValueError
        self.index += 1
        return token

    @staticmethod
    def bounded(value):
        if any(max(v.numerator.bit_length(), v.denominator.bit_length()) > 2048 for v in value):
            raise ValueError
        return value

    def expression(self, depth=0):
        if depth > MAX_COLLECTION_DEPTH:
            raise ValueError
        value = self.product(depth+1)
        while self.peek() in ('+', '-'):
            op = self.take()
            other = self.product(depth+1)
            sign = 1 if op == '+' else -1
            value = self.bounded(tuple(a+sign*b for a, b in zip(value, other)))
        return value

    def product(self, depth):
        value = self.factor(depth)
        while self.peek() and self.peek() not in ('+', '-', ')', '}'):
            op = self.take() if self.peek() in ('*', '/') else '*'
            other = self.factor(depth)
            if op == '/':
                if other[0] or not other[1]:
                    raise ValueError
                value = (value[0]/other[1], value[1]/other[1])
            else:
                if value[0] and other[0]:
                    raise ValueError
                value = (value[0]*other[1]+value[1]*other[0], value[1]*other[1])
            value = self.bounded(value)
        return value

    def argument(self, depth):
        """Аргумент \\frac: группа либо один символ (в том числе \\frac24)."""
        if self.peek() == '{':
            return self.factor(depth+1)
        token = self.peek()
        if token and token[0].isdigit():
            first = token[0]
            if len(token) > 1:
                self.tokens[self.index] = token[1:]
            else:
                self.take()
            return Fraction(0), Fraction(first)
        if token and token.isalpha() and len(token) == 1:
            return self.factor(depth+1)
        raise ValueError

    def factor(self, depth):
        if depth > MAX_COLLECTION_DEPTH:
            raise ValueError
        token = self.take()
        if token in ('+', '-'):
            value = self.factor(depth+1)
            return value if token == '+' else tuple(-v for v in value)
        if token in ('(', '{'):
            value = self.expression(depth+1)
            if self.take() != (')' if token == '(' else '}'):
                raise ValueError
            return value
        if token == r'\frac':
            numerator = self.argument(depth+1)
            denominator = self.argument(depth+1)
            if denominator[0] or not denominator[1]:
                raise ValueError
            return self.bounded(tuple(v/denominator[1] for v in numerator))
        if token.isalpha() and len(token) == 1:
            self.variables.add(token)
            return Fraction(1), Fraction(0)
        try:
            return self.bounded((Fraction(0), Fraction(token)))
        except (ValueError, ZeroDivisionError):
            raise ValueError from None

    def parse(self):
        value = self.expression()
        if self.peek():
            raise ValueError
        return value


def _affine_inequality(piece):
    """Линейная запись с одной переменной, включая цепочки неравенств."""
    parts = _COMPARE_RE.split(piece)
    if len(parts) < 3 or len(parts) > 17:
        return None
    values, variables = [], set()
    try:
        for text in parts[::2]:
            parser = _AffineParser(text)
            values.append(parser.parse())
            variables.update(parser.variables)
        if len(variables) != 1:
            return None
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    result = [(-INF, INF, '(', ')')]
    for i, op in enumerate(parts[1::2]):
        a = values[i][0]-values[i+1][0]
        b = values[i][1]-values[i+1][1]
        if not a:
            truth = {'<': b < 0, '<=': b <= 0, '>': b > 0, '>=': b >= 0,
                     '!=': b != 0, '=': b == 0}[op]
            one = [(-INF, INF, '(', ')')] if truth else []
        else:
            bound = -b/a
            if a < 0:
                op = {'<': '>', '<=': '>=', '>': '<', '>=': '<=',
                      '!=': '!=', '=': '='}[op]
            if op == '=':
                one = [(bound, bound, '[', ']')]
            elif op == '!=':
                one = [(-INF, bound, '(', ')'), (bound, INF, '(', ')')]
            elif op.startswith('>'):
                one = [(bound, INF, '[' if op == '>=' else '(', ')')]
            else:
                one = [(-INF, bound, '(', ']' if op == '<=' else ')')]
        result = _intersect_lists(result, one)
    return result


def _inequality(piece):
    """Одно неравенство → список промежутков или None."""
    piece = piece.strip()
    affine = _affine_inequality(piece)
    if affine is not None:
        return affine
    m = _CHAIN_RE.match(piece)
    if m:
        a, op1, op2, b = m.group(1), m.group(2), m.group(3), m.group(4)
        if op1[0] != op2[0]:
            return None
        lo, hi = (_bound_value(a), _bound_value(b)) if op1[0] == '<' \
            else (_bound_value(b), _bound_value(a))
        lo_op, hi_op = (op1, op2) if op1[0] == '<' else (op2, op1)
        if lo is None or hi is None:
            return None
        return [(lo, hi, '[' if lo_op.endswith('=') else '(',
                 ']' if hi_op.endswith('=') else ')')]
    m = _LEFT_RE.match(piece)
    if m:
        op, value = m.group(1), _bound_value(m.group(2))
    else:
        m = _RIGHT_RE.match(piece)
        if not m:
            return None
        value, op = _bound_value(m.group(1)), m.group(2)
        # ``5 < x`` — то же, что ``x > 5``
        op = {'<': '>', '<=': '>=', '>': '<', '>=': '<=', '!=': '!='}[op]
    if value is None:
        return None
    if op == '!=':
        return [(-INF, value, '(', ')'), (value, INF, '(', ')')]
    if op[0] == '>':
        return [(value, INF, '[' if op.endswith('=') else '(', ')')]
    return [(-INF, value, '(', ']' if op.endswith('=') else ')')]


def _normalize_intervals(intervals):
    """Убрать пустые, склеить пересекающиеся и соприкасающиеся."""
    cleaned = []
    for lo, hi, left, right in intervals:
        if lo > hi or (lo == hi and (left == '(' or right == ')')):
            continue
        if lo == -INF:
            left = '('
        if hi == INF:
            right = ')'
        cleaned.append((lo, hi, left, right))
    cleaned.sort(key=lambda t: (t[0], t[2] == '(', t[1]))
    merged = []
    for cur in cleaned:
        if merged:
            lo, hi, left, right = merged[-1]
            touching = cur[0] < hi or (
                cur[0] == hi and (right == ']' or cur[2] == '['))
            if touching:
                if cur[1] > hi or (cur[1] == hi and cur[3] == ']'):
                    hi, right = cur[1], cur[3]
                merged[-1] = (lo, hi, left, right)
                continue
        merged.append(cur)
    return frozenset(merged)


def _intersect_one(a, b):
    """Пересечение двух промежутков или None, если пусто."""
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    if lo > hi:
        return None
    left = '(' if ((lo == a[0] and a[2] == '(') or (lo == b[0] and b[2] == '(')) else '['
    right = ')' if ((hi == a[1] and a[3] == ')') or (hi == b[1] and b[3] == ')')) else ']'
    if lo == hi and (left == '(' or right == ')'):
        return None
    return (lo, hi, left, right)


def _intersect_lists(left, right):
    out = []
    for a in left:
        for b in right:
            one = _intersect_one(a, b)
            if one:
                out.append(one)
    return out


def _parse_range_atom(piece, tokens):
    piece = piece.strip()
    if not piece:
        return None
    m = re.fullmatch(r'\x00(\d+)\x00', piece)
    if m:
        index = int(m.group(1))
        if index >= len(tokens):
            return None
        parsed = _parse_interval_token(tokens[index])
        return None if parsed is None else [parsed]
    if piece.lower() in ALL_WORDS:
        return [(-INF, INF, '(', ')')]
    difference = _DIFFERENCE_RE.fullmatch(piece)
    if difference:
        values = parse_set(difference.group(1))
        if values is None:
            return None
        bounds = [-INF] + sorted(values) + [INF]
        return [(lo, hi, '(', ')') for lo, hi in zip(bounds, bounds[1:])]
    inequality = _inequality(piece)
    if inequality is not None:
        return inequality
    values = parse_set(piece)
    return [(v, v, '[', ']') for v in values] if values is not None else None


def parse_range(text):
    """Числовое множество: скобочная запись, объединения, неравенства
    (``x>5, x<-5``; ``1<x<4``; ``x \\le -5 или x>5``), «нет решений», R.
    Возвращает нормализованное множество промежутков; None — не разобрано."""
    text = _collection_text(text)
    if not text:
        return None
    text = _IN_RE.sub('', text).strip()
    low = text.lower()
    if low in EMPTY_WORDS:
        return frozenset()
    if low in ALL_WORDS:
        return frozenset({(-INF, INF, '(', ')')})
    finite = parse_set(text)
    if finite is not None:
        return _normalize_intervals([(v, v, '[', ']') for v in finite])
    tokens = []

    def _stash(m):
        tokens.append(m.group(0))
        return f'\x00{len(tokens) - 1}\x00'

    rest = _INTERVAL_TOKEN_RE.sub(_stash, text)
    intervals = []
    saw_atom = False
    union_parts = _split_top(rest, _UNION_RE)
    if union_parts is None:
        return None
    for union_part in union_parts:
        and_parts = _split_top(union_part, _AND_RE)
        if and_parts is None:
            return None
        and_parts = [p for p in and_parts if p.strip()]
        if not and_parts:
            continue
        acc = None
        for part in and_parts:
            parsed = _parse_range_atom(part, tokens)
            if parsed is None:
                return None
            saw_atom = True
            acc = parsed if acc is None else _intersect_lists(acc, parsed)
        intervals.extend(acc)
        if len(intervals) > MAX_COLLECTION_ITEMS:
            return None
    if not saw_atom:
        return None
    return _normalize_intervals(intervals)


def _bound_equal(a, b, tolerance=None):
    """Конечные границы — через ``numbers_equal`` (Fraction и float √2);
    бесконечности сравниваются точно."""
    if a in (-INF, INF) or b in (-INF, INF):
        return a == b
    return numbers_equal(a, b, tolerance)


def _interval_equal(a, b, tolerance=None):
    return (a[2] == b[2] and a[3] == b[3]
            and _bound_equal(a[0], b[0], tolerance)
            and _bound_equal(a[1], b[1], tolerance))


def ranges_equal(a, b, tolerance=None):
    if a is None or b is None:
        return False
    if a == b:
        return True
    return _multiset_equal(list(a), list(b), tolerance, equal=_interval_equal)

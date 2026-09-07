"""Числовые слоты маски: число, упорядоченная пара, конечное множество,
числовой промежуток. Разбор строится на примитивах ``check_answer``
(``parse_number``, ``parse_interval``), сравнение — точное для дробей и с
допуском для иррациональных значений (``\\sqrt{2}`` и т.п.)."""
import math
import re
from fractions import Fraction

from ..check_answer import (_endpoint, _expand_pm, _strip_var, normalize,
                            parse_interval, parse_number)

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
_PAIR_GROUP_RE = re.compile(r'\(([^()]*)\)')

INF = float('inf')


# --- числа ---------------------------------------------------------------------

def numeric_value(text):
    """Строка → Fraction (точно) или float (иррациональное); None — не число.
    Понимает школьные дроби и любое числовое LaTeX-выражение без переменных."""
    text = normalize(_strip_var(text or ''))
    if not text:
        return None
    value = parse_number(text)
    if value is not None:
        return value
    from .expressions import parse_expr
    expr = parse_expr(text)
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


def _unique_numbers(values, tolerance=None):
    """Убрать численно равные повторы: ``±0`` и ``0; 0`` — одно число."""
    out = []
    for value in values:
        if not any(numbers_equal(value, other, tolerance) for other in out):
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

def _split_items(text):
    text = text.strip()
    if text.startswith('{') and text.endswith('}'):
        text = text[1:-1].strip()
    if not text or text.lower() in EMPTY_WORDS:
        return []
    parts = re.split(r'[;,]', text) if (';' in text or ',' in text) else [text]
    return [p.strip() for p in parts if p.strip()]


def parse_set(text):
    """Конечное множество чисел: ``-2; 1``, ``\\{-2;1\\}``, ``x=\\pm3``,
    ``нет корней`` → список значений (пустой = нет решений); None — не разобрано."""
    text = normalize(text or '')
    if not text:
        return None
    items = _expand_pm([_strip_var(i) for i in _split_items(text)])
    values = [numeric_value(i) for i in items]
    if any(v is None for v in values):
        return None
    return _unique_numbers(values)


def sets_equal(a, b, tolerance=None):
    return _multiset_equal(
        _unique_numbers(a, tolerance), _unique_numbers(b, tolerance), tolerance)


def parse_pairs(text):
    """``(2,5; -3); (5; -6)`` → список кортежей чисел одинаковой длины;
    одна пара без скобок ``2; -3`` тоже допускается. None — не разобрано."""
    text = normalize(text or '')
    if not text:
        return None
    groups = _PAIR_GROUP_RE.findall(text)
    if groups:
        leftover = _PAIR_GROUP_RE.sub(' ', text)
        leftover = re.sub(r'[\s,;]+', '', leftover)
        if leftover:
            return None
    else:
        if ';' not in text:
            return None
        groups = [text]
    pairs = []
    for group in groups:
        parts = [p.strip() for p in group.split(';')]
        if len(parts) < 2 or any(not p for p in parts):
            return None
        values = [numeric_value(p) for p in parts]
        if any(v is None for v in values):
            return None
        pairs.append(tuple(values))
    if len({len(p) for p in pairs}) != 1:
        return None
    return pairs


def _pair_equal(a, b, tolerance=None):
    return len(a) == len(b) and all(
        numbers_equal(x, y, tolerance) for x, y in zip(a, b))


def pairs_equal(a, b, tolerance=None):
    return _multiset_equal(a, b, tolerance, equal=_pair_equal)


# --- числовые промежутки -------------------------------------------------------

_INTERVAL_PARSE_RE = re.compile(
    r'^([(\[])\s*(.+?)\s*;\s*(.+?)\s*([)\]])$')


def _bound_value(text):
    """Конец промежутка: Fraction, float (иррациональное) или ±inf; None."""
    value = _endpoint(text)
    if value is not None:
        return value
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


def _inequality(piece):
    """Одно неравенство → список промежутков или None."""
    piece = piece.strip()
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
        parsed = _parse_interval_token(tokens[int(m.group(1))])
        if parsed is None:
            parsed = parse_interval(tokens[int(m.group(1))])
        return None if parsed is None else [parsed]
    return _inequality(piece)


def parse_range(text):
    """Числовое множество: скобочная запись, объединения, неравенства
    (``x>5, x<-5``; ``1<x<4``; ``x \\le -5 или x>5``), «нет решений», R.
    Возвращает нормализованное множество промежутков; None — не разобрано."""
    text = normalize(text or '')
    if not text:
        return None
    text = _IN_RE.sub('', text).strip()
    low = text.lower()
    if low in EMPTY_WORDS:
        return frozenset()
    if low in ALL_WORDS:
        return frozenset({(-INF, INF, '(', ')')})
    tokens = []

    def _stash(m):
        tokens.append(m.group(0))
        return f'\x00{len(tokens) - 1}\x00'

    rest = _INTERVAL_TOKEN_RE.sub(_stash, text)
    intervals = []
    saw_atom = False
    for union_part in _UNION_RE.split(rest):
        and_parts = [p for p in _AND_RE.split(union_part) if p.strip()]
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

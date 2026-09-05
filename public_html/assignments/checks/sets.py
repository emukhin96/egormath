"""Числовые слоты маски: число, упорядоченная пара, конечное множество,
числовой промежуток. Разбор строится на примитивах ``check_answer``
(``parse_number``, ``parse_interval``), сравнение — точное для дробей и с
допуском для иррациональных значений (``\\sqrt{2}`` и т.п.)."""
import re
from fractions import Fraction

from ..check_answer import (_endpoint, _expand_pm, _strip_var, normalize,
                            parse_interval, parse_number)

EMPTY_WORDS = ('∅', '{}', 'нет', 'нет решений', 'решений нет', 'нет корней',
               'корней нет', 'пустое множество', 'none')
ALL_WORDS = ('r', '\\mathbb{r}', 'ℝ', 'любое число', 'любое', 'все числа',
             'x - любое', 'x любое')

_VAR = r'[a-zA-Zа-яА-Я](?:_\{?\d+\}?)?'
_IN_RE = re.compile(r'^' + _VAR + r'\s*(?:\\in|∈)\s*')
_INTERVAL_TOKEN_RE = re.compile(
    r'[(\[]\s*[^;()\[\]]+?\s*;\s*[^;()\[\]]+?\s*[)\]]')
_SPLIT_RE = re.compile(r'\s*(?:∪|,|;|\bили\b|\bor\b|\bи\b)\s*')
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
    return result if result == result else None  # NaN


def numbers_equal(a, b, tolerance=None):
    if a is None or b is None:
        return False
    if tolerance is None:
        if isinstance(a, Fraction) and isinstance(b, Fraction):
            return a == b
        tolerance = 1e-9 * max(1.0, abs(float(b)))
    return abs(float(a) - float(b)) <= float(tolerance)


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
    return values


def sets_equal(a, b, tolerance=None):
    return _multiset_equal(a, b, tolerance)


def parse_pairs(text):
    """``(2,5; -3); (5; -6)`` → список кортежей чисел одинаковой длины;
    одна пара без скобок ``2; -3`` тоже допускается. None — не разобрано."""
    text = normalize(text or '')
    if not text:
        return None
    groups = _PAIR_GROUP_RE.findall(text)
    if not groups:
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
        lo, hi = (_endpoint(a), _endpoint(b)) if op1[0] == '<' \
            else (_endpoint(b), _endpoint(a))
        lo_op, hi_op = (op1, op2) if op1[0] == '<' else (op2, op1)
        if lo is None or hi is None:
            return None
        return [(lo, hi, '[' if lo_op.endswith('=') else '(',
                 ']' if hi_op.endswith('=') else ')')]
    m = _LEFT_RE.match(piece)
    if m:
        op, value = m.group(1), _endpoint(m.group(2))
    else:
        m = _RIGHT_RE.match(piece)
        if not m:
            return None
        value, op = _endpoint(m.group(1)), m.group(2)
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
    for piece in _SPLIT_RE.split(rest):
        piece = piece.strip()
        if not piece:
            continue
        m = re.fullmatch(r'\x00(\d+)\x00', piece)
        if m:
            parsed = parse_interval(tokens[int(m.group(1))])
            if parsed is None:
                return None
            intervals.append(parsed)
            continue
        parsed = _inequality(piece)
        if parsed is None:
            return None
        intervals.extend(parsed)
    if not intervals:
        return None
    return _normalize_intervals(intervals)


def ranges_equal(a, b):
    return a == b

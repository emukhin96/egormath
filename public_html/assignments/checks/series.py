"""Точное сравнение объединений арифметических серий с периодом, кратным π.

Ветвь серии — ``c + (a + b·n)·π``: ``a``, ``b`` рациональные, ``c`` —
сумма рациональных кратных arctg u (0 < u < 1, u — алгебраическое число;
к ней сводятся arcsin, arccos, arctg и школьный arcctg числового
аргумента). Серии с одинаковым ``c`` сравниваются по классам остатков,
как раньше; разные ``c`` должны отличаться не на рациональное кратное π —
иначе ответ «не удалось проверить», а не ошибочное «неверно».
"""
import re
from fractions import Fraction
from itertools import product
from math import gcd

MAX_PERIOD = 10000
MAX_BRANCHES = 24
# Серии проверяются в процессе приложения, без вычислителя: аргумент
# arc-функции — короткое алгебраическое число, иначе «не удалось проверить».
MAX_ARGUMENT_OPS = 24
# Точное равенство констант — minimal_polynomial: только квадратные корни,
# не больше MAX_RADICALS разных, чтобы степень многочлена оставалась малой.
MAX_RADICALS = 4
# Независимых знаков ± в одной записи серии (2³ ветви).
MAX_PM = 3
_PRECISION = 60

_ARC = r'(?:arcsin|arccos|arctg|arcctg|arctan|arccot)'
# Имена arc-функций в любой оболочке: \arcsin, \operatorname{arctg},
# \mathrm{arcctg}, голое arctg. Остальные буквы (кроме n/k/m/l) запрещены.
_ARC_TOKEN_RE = re.compile(r'\\(?:operatorname|mathrm)\s*\{\s*' + _ARC + r'\s*\}|\\?' + _ARC)
_ALLOWED_RE = re.compile(r'\\(?:frac|dfrac|tfrac|cdot|sqrt)(?![A-Za-z])')
_SIGN_RE = re.compile(
    r'\(\s*-\s*1\s*\)\s*\^\s*(?:\{\s*([nkml])\s*(?:([+-])\s*(\d+)\s*)?\}|([nkml]))')
_INTEGER_RE = re.compile(
    r'(?<![A-Za-z\\])[nkml]\s*(?:\\in|∈)\s*'
    r'(?:\\math(?:bb|bf)\s*\{\s*Z\s*\}|\\mathbb\s*Z|ℤ|Z)(?![A-Za-z])\s*\)?')
_LIST_TAIL_RE = re.compile(r'(?<![A-Za-z\\])[nkml]\s*,\s*$')


def _lcm(a, b):
    return a * b // gcd(a, b)


def _numeric(value):
    from sympy import N
    return N(value, _PRECISION)


def _few_radicals(value):
    from sympy import Pow, Rational
    radicals = {p for p in value.atoms(Pow) if not p.exp.is_Integer}
    return len(radicals) <= MAX_RADICALS and all(p.exp == Rational(1, 2) for p in radicals)


def _is_zero(value):
    """Точный ноль алгебраического числа; None — не удалось решить."""
    if abs(_numeric(value)) > Fraction(1, 10 ** 40):
        return False
    if not _few_radicals(value):
        return None
    from sympy import minimal_polynomial, Symbol
    try:
        x = Symbol('x')
        return minimal_polynomial(value, x) == x
    except Exception:  # noqa: BLE001 — не алгебраическое или слишком сложное
        return None


def _sign(value):
    zero = _is_zero(value)
    if zero is None:
        return None
    return 0 if zero else (1 if _numeric(value) > 0 else -1)


def _arctg(t):
    """arctg t → (рациональное кратное π, знак, u) при 0 < u < 1; u = 0 — нет константы."""
    from sympy import radsimp
    sign = _sign(t)
    if sign is None:
        return None
    if sign == 0:
        return Fraction(0), 1, None
    if sign < 0:
        res = _arctg(-t)
        return None if res is None else (-res[0], -res[1], res[2])
    above = _sign(t - 1)
    if above is None:
        return None
    if above == 0:
        return Fraction(1, 4), 1, None
    if above > 0:
        res = _arctg(radsimp(1 / t))
        return None if res is None else (Fraction(1, 2) - res[0], -res[1], res[2])
    from sympy import atan, pi
    value = atan(t)
    ratio = value / pi
    if ratio.is_Rational:
        # sympy сам узнаёт табличные углы: arctg(2-√3) = π/12.
        return Fraction(int(ratio.p), int(ratio.q)), 1, None
    return Fraction(0), 1, radsimp(t)


def _arc_term(func, arg):
    """Значение arc-функции → (рациональное кратное π, знак, u)."""
    from sympy import asin, acos, atan, sqrt, radsimp
    if (arg.free_symbols or arg.count_ops() > MAX_ARGUMENT_OPS
            or not _few_radicals(arg) or not arg.is_real):
        return None
    if func is atan:
        return _arctg(arg)
    if func is acos:
        res = _arc_term(asin, arg)
        return None if res is None else (Fraction(1, 2) - res[0], -res[1], res[2])
    if func is asin:
        edge = _sign(1 - arg * arg)
        if edge is None or edge < 0:
            return None
        if edge == 0:
            sign = _sign(arg)
            return Fraction(sign, 2), 1, None
        return _arctg(radsimp(arg / sqrt(1 - arg * arg)))
    return None


def _constant(expr):
    """Свободный член ветви → (рациональное кратное π, ((коэф., u), …))."""
    from sympy import Add, asin, acos, atan, pi
    rational = Fraction(0)
    terms = []
    for term in Add.make_args(expr):
        ratio = term / pi
        if ratio.is_Rational:
            rational += Fraction(int(ratio.p), int(ratio.q))
            continue
        coefficient, rest = term.as_coeff_Mul()
        if not coefficient.is_Rational or not isinstance(rest, (asin, acos, atan)):
            return None
        res = _arc_term(type(rest), rest.args[0])
        if res is None:
            return None
        coefficient = Fraction(int(coefficient.p), int(coefficient.q))
        rational += coefficient * res[0]
        if res[2] is not None:
            terms.append((coefficient * res[1], res[2]))
    merged = []
    for coefficient, u in terms:
        for i, (other, v) in enumerate(merged):
            same = _is_zero(u - v)
            if same is None:
                return None
            if same:
                merged[i] = (other + coefficient, v)
                break
        else:
            merged.append((coefficient, u))
    return rational, tuple((c, u) for c, u in merged if c)


def _sign_choices(piece):
    """(-1)^n раскрывается в чётные и нечётные n: (текст, n → 2n + остаток)."""
    match = _SIGN_RE.search(piece)
    if not match:
        return [(piece, None)]
    if len(_SIGN_RE.findall(piece)) > 1:
        return None
    shift = int(match.group(3) or 0) * (-1 if match.group(2) == '-' else 1)
    out = []
    rest = piece[match.end():]
    # Множитель (±1) перед следующим сомножителем — явное умножение:
    # разбор формул не умножает скобку на \frac без знака.
    times = '' if re.match(r'\s*(?:\\cdot|[-+)}*/]|$)', rest) else '\\cdot '
    for parity in (0, 1):
        value = '(1)' if (parity + shift) % 2 == 0 else '(-1)'
        out.append((piece[:match.start()] + value + times + rest, parity))
    return out


def _pm_choices(piece):
    """Знаки ± независимы, кроме пары ± и ∓ (верхний с верхним)."""
    if '∓' in piece:
        if piece.count('±') != 1 or piece.count('∓') != 1:
            return None
        return [piece.replace('±', '+').replace('∓', '-'),
                piece.replace('±', '-').replace('∓', '+')]
    parts = piece.split('±')
    if len(parts) > MAX_PM + 1:
        return None
    out = []
    for signs in product('+-', repeat=len(parts) - 1):
        out.append(parts[0] + ''.join(sign + part for sign, part in zip(signs, parts[1:])))
    return out


def _branch(choice, parity):
    """Текст одной ветви → (рациональный сдвиг, период, константа) в долях π."""
    from sympy import Symbol, expand, diff, pi
    from .expressions import parse_expr
    residual = _ARC_TOKEN_RE.sub('', choice)
    residual = _ALLOWED_RE.sub('', residual)
    # Не разрешаем другие функции, степени и произвольные переменные: (-1)^n
    # уже раскрыто, а целая степень вроде 9^{9^9} считалась бы в процессе
    # приложения без лимита времени.
    if re.search(r'[^0-9Qnkml{}()\[\]\s+*/.\-]', residual):
        return None
    # π уже заменено на Q: «2k\\pi» — это «2kQ», буква k стоит вплотную к Q.
    choice = re.sub(r'(?<![A-PR-Za-z])[kml](?![A-PR-Za-z])', 'n', choice)
    # Разбор формул не умножает дробь на букву через пробел (\\frac{2}{5} n \\pi).
    choice = re.sub(r'(?<=[}\dnQ)])\s+(?=[nQ(\\])', '', choice)
    expr = parse_expr(choice)
    n, marker = Symbol('n'), Symbol('Q')
    if expr is None or not getattr(expr, 'free_symbols', set()) <= {n, marker}:
        return None
    try:
        expr = expand(expr.subs(marker, pi))
        if parity is not None:
            expr = expand(expr.subs(n, 2 * n + parity))
        if diff(expr, n, 2) != 0:
            return None
        period = diff(expr, n) / pi
        if not period.is_Rational or not period:
            return None
        constant = _constant(expand(expr.subs(n, 0)))
        if constant is None:
            return None
        offset, key = constant
        b = abs(Fraction(int(period.p), int(period.q)))
    except (ArithmeticError, AttributeError, TypeError, ValueError):
        return None
    if max(abs(offset.numerator), offset.denominator, b.numerator, b.denominator) > MAX_PERIOD:
        return None
    return offset, b, key


def _strip_integer(text):
    """Убирает «n, k ∈ Z»: перечень целых параметров начинается после
    запятой или скобки, а не буквой серии (πk, n, k ∈ Z)."""
    while True:
        match = _INTEGER_RE.search(text)
        if not match:
            return text
        start = match.start()
        while True:
            tail = _LIST_TAIL_RE.search(text[:start])
            if not tail or not re.search(r'(?:^|[,;(])\s*$', text[:tail.start()]):
                break
            start = tail.start()
        end = match.end()
        if match.group().endswith(')'):
            opening = re.search(r'\(\s*$', text[:start])
            if opening:
                start = opening.start()
            else:
                end -= 1
        text = text[:start] + text[end:]


def parse(text):
    """Поддерживает рациональные сдвиг и период, arc-функции числового
    аргумента и (-1)^n; не решает уравнения."""
    text = (text or '').strip()
    if len(text) > 2000:
        return None
    text = re.sub(r'\\(?:displaystyle|left|right)|\$|\\[()[\]]', '', text)
    text = _strip_integer(re.sub(r'\\[ ,;:!]|\\q?quad', ' ', text))
    text = text.strip(' ,;.')
    text = text.replace('\\pm', '±').replace('\\mp', '∓')
    # Скобка перед следующим сомножителем — явное умножение (как и для (±1)).
    text = re.sub(r'\)\s*(?=\\(?:frac|dfrac|tfrac|sqrt|arc|operatorname|mathrm|pi)|arc|\()',
                  r')\\cdot ', text)
    if 'Q' in text:
        return None
    text = re.sub(r'\\pi(?![A-Za-z])|π|\bpi\b', 'Q', text)
    pieces = [p.strip() for p in re.split(r'[,;]|\\cup|∪', text) if p.strip()]
    out = []
    for piece in pieces:
        piece = re.sub(r'^[xyt](?:_\{?\d+\}?)?\s*=\s*', '', piece)
        choices = _pm_choices(piece)
        if choices is None:
            return None
        for choice in choices:
            signs = _sign_choices(choice)
            if signs is None:
                return None
            for variant, parity in signs:
                branch = _branch(variant, parity)
                if branch is None:
                    return None
                out.append(branch)
                if len(out) > MAX_BRANCHES:
                    return None
    return out or None


def _residues(branches):
    denominator = 1
    for offset, period in branches:
        denominator = _lcm(denominator, offset.denominator)
        denominator = _lcm(denominator, period.denominator)
        if denominator > MAX_PERIOD:
            return None
    periods = [int(p * denominator) for _, p in branches]
    step = 1
    for period in periods:
        step = _lcm(step, period)
        if step > MAX_PERIOD:
            return None
    residues = set()
    for (offset, _), period in zip(branches, periods):
        residues.update(range(int(offset * denominator) % period, step, period))
    return denominator, step, frozenset(residues)


def _groups(branches):
    """Ветви по константе: [(константа, ветви)]; константы сравниваются точно."""
    groups = []
    for offset, period, key in branches:
        for group in groups:
            same = _same_constant(group[0], key)
            if same is None:
                return None
            if same:
                group[1].append((offset, period))
                break
        else:
            groups.append((key, [(offset, period)]))
    return groups


def _same_constant(left, right):
    if len(left) != len(right):
        return False
    unmatched = list(right)
    for coefficient, u in left:
        for i, (other, v) in enumerate(unmatched):
            if other != coefficient:
                continue
            same = _is_zero(u - v)
            if same is None:
                return None
            if same:
                del unmatched[i]
                break
        else:
            return False
    return True


def _value(key):
    from sympy import atan, Rational
    return sum((Rational(c.numerator, c.denominator) * atan(u) for c, u in key), Rational(0))


def canonical(branches):
    if not branches or len(branches) > MAX_BRANCHES:
        return None
    groups = _groups(branches)
    if groups is None:
        return None
    out = []
    for key, items in groups:
        residues = _residues(items)
        if residues is None:
            return None
        out.append((key, residues))
    return out


def _independent(keys):
    """Разные константы не отличаются на рациональное кратное π (численно,
    с запасом точности); иначе точное сравнение невозможно."""
    from sympy import pi
    values = [_value(key) for key in keys]
    for i, left in enumerate(values):
        for right in values[i + 1:]:
            ratio = _numeric((left - right) / pi)
            approx = Fraction(str(ratio)).limit_denominator(MAX_PERIOD)
            if abs(Fraction(str(ratio)) - approx) < Fraction(1, 10 ** 30):
                return False
    return True


def _equal_residues(a, b):
    denominator = _lcm(a[0], b[0])
    sa, sb = a[1] * (denominator // a[0]), b[1] * (denominator // b[0])
    step = _lcm(sa, sb)
    if step > MAX_PERIOD:
        return None
    ra = {x * (denominator // a[0]) + k * sa for x in a[2] for k in range(step // sa)}
    rb = {x * (denominator // b[0]) + k * sb for x in b[2] for k in range(step // sb)}
    return ra == rb


def equal(left, right):
    a, b = canonical(left), canonical(right)
    if a is None or b is None:
        return None
    pairs, unmatched = [], list(b)
    for key, residues in a:
        for i, (other, other_residues) in enumerate(unmatched):
            same = _same_constant(key, other)
            if same is None:
                return None
            if same:
                pairs.append((residues, other_residues))
                del unmatched[i]
                break
        else:
            pairs.append((residues, None))
    if not unmatched and all(other is not None for _, other in pairs):
        results = [_equal_residues(residues, other) for residues, other in pairs]
        if all(result is True for result in results):
            # Совпали и константы, и остатки — равенство не зависит от того,
            # связаны ли константы между собой.
            return True
        if any(result is None for result in results):
            return None
    keys = [key for key, _ in a] + [key for key, _ in unmatched]
    if len(keys) > 1 and not _independent(keys):
        return None
    return False

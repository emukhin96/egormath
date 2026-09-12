"""Точное сравнение объединений арифметических серий кратных π."""
import re
from fractions import Fraction
from math import gcd

MAX_PERIOD = 10000
MAX_BRANCHES = 24


def _lcm(a, b):
    return a * b // gcd(a, b)


def parse(text):
    """Поддерживает рациональные сдвиг и период; не решает уравнения."""
    from sympy import Symbol, expand
    from .expressions import parse_expr
    text = (text or '').strip()
    if len(text) > 2000:
        return None
    text = re.sub(r'\\(?:displaystyle|left|right)|\$|\\[()[\]]', '', text)
    text = re.sub(r'(?<![A-Za-z])[nkm]\s*(?:\\in|∈)\s*(?:\\mathbb\{Z\}|ℤ|Z)', '', text)
    text = text.strip(' ,;')
    text = re.sub(r'^x\s*=\s*', '', text)
    text = text.replace('\\pm', '±')
    if 'Q' in text:
        return None
    text = re.sub(r'\\pi(?![A-Za-z])|π|\bpi\b', 'Q', text)
    pieces = [p.strip() for p in re.split(r'[,;]|\\cup|∪', text) if p.strip()]
    out = []
    n, p = Symbol('n'), Symbol('Q')
    for piece in pieces:
        if piece.count('±') > 1:
            return None
        choices = [piece.replace('±', '+'), piece.replace('±', '-')] if '±' in piece else [piece]
        for choice in choices:
            # Не разрешаем функции, степени и произвольные переменные.
            residual = re.sub(r'\\(?:frac|cdot)\b', '', choice)
            if re.search(r'[^0-9Qnkm{}()\s+*/.\-]', residual):
                return None
            choice = re.sub(r'[km]', 'n', choice)
            expr = parse_expr(choice)
            if expr is None or not getattr(expr, 'free_symbols', set()) <= {n, p}:
                return None
            try:
                expr = expand(expr)
                offset = expr.subs(n, 0) / p
                period = expand(expr - expr.subs(n, 0)) / (n * p)
                if not offset.is_Rational or not period.is_Rational or not period:
                    return None
                a, b = Fraction(int(offset.p), int(offset.q)), abs(Fraction(int(period.p), int(period.q)))
                if max(abs(a.numerator), a.denominator, b.numerator, b.denominator) > MAX_PERIOD:
                    return None
                out.append((a, b))
            except (ArithmeticError, AttributeError, TypeError, ValueError):
                return None
            if len(out) > MAX_BRANCHES:
                return None
    return out or None


def canonical(branches):
    if not branches or len(branches) > MAX_BRANCHES:
        return None
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


def equal(left, right):
    a, b = canonical(left), canonical(right)
    if a is None or b is None:
        return None
    denominator = _lcm(a[0], b[0])
    sa, sb = a[1] * (denominator // a[0]), b[1] * (denominator // b[0])
    step = _lcm(sa, sb)
    if step > MAX_PERIOD:
        return None
    ra = {x * (denominator // a[0]) + k * sa for x in a[2] for k in range(step // sa)}
    rb = {x * (denominator // b[0]) + k * sb for x in b[2] for k in range(step // sb)}
    return ra == rb

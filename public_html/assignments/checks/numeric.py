"""Ограниченная числовая арифметика без символьного упрощения.

Каждый узел вычисляется отдельно: 0*(1/0) не превращается в допустимый
нуль. Размер степеней ограничивается до возведения, а не после него.
"""
import re
from decimal import Decimal, DecimalException, localcontext
from fractions import Fraction

from ..check_answer import normalize, parse_number
from . import expressions

MAX_BITS = 2048
MAX_NODES = 128
MAX_DEPTH = 16
_NUMBER = re.compile(r'\d+(?:\.\d+)?')
_MIXED = re.compile(r'(?<![\w.^_\\}])(\d+)\s*\\frac\s*'
                    r'(?:\{(\d+)\}|(\d))\s*(?:\{(\d+)\}|(\d))')


class Uncertain(ValueError):
    """Потеря точности требует отдельной символьной проверки."""


def bounded(value):
    if isinstance(value, Fraction):
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_BITS:
            raise ValueError
    elif (not isinstance(value, Decimal) or not value.is_finite()
          or value != 0 and abs(value.adjusted()) > 1000):
        raise ValueError
    return value


def as_decimal(value):
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    return value


def calculate(operation, a, b):
    with localcontext() as context:
        context.prec = 80
        context.Emax, context.Emin = 1000, -1000
        if not isinstance(a, Fraction) or not isinstance(b, Fraction):
            a, b = as_decimal(a), as_decimal(b)
            if operation in ('add', 'sub') and a != 0 and b != 0:
                # Оставляем запас точности до допустимого сравнения 1e-9.
                if abs(a.adjusted() - b.adjusted()) > 50:
                    raise Uncertain
        if operation == 'add':
            result = a + b
        elif operation == 'sub':
            result = a - b
        elif operation == 'mul':
            result = a * b
            if result == 0 and a != 0 and b != 0:
                raise ValueError
        elif operation == 'div':
            if b == 0:
                raise ValueError
            result = a / b
            if result == 0 and a != 0:
                raise ValueError
        else:
            raise ValueError
        if isinstance(result, Decimal) and operation in ('add', 'sub'):
            if max(abs(a), abs(b)) and abs(result) < max(abs(a), abs(b)) * Decimal('1e-50'):
                raise Uncertain
        return bounded(result)


def equal(a, b):
    if isinstance(a, Fraction) and isinstance(b, Fraction):
        return a == b
    if a == 0 or b == 0:
        return a == b
    with localcontext() as context:
        context.prec = 80
        a, b = as_decimal(a), as_decimal(b)
        return abs(a-b) <= abs(b) * Decimal('1e-9')


def power(base, exponent):
    if not isinstance(exponent, Fraction) or abs(exponent) > 1000:
        raise ValueError
    if base == 0 and exponent <= 0:
        raise ValueError
    if exponent.denominator != 1:
        base = root(base, exponent.denominator)
        exponent = Fraction(exponent.numerator)
    degree = int(exponent)
    if isinstance(base, Fraction):
        for part in (base.numerator, base.denominator):
            if abs(part) > 1 and part.bit_length() * abs(degree) > MAX_BITS:
                raise ValueError
    result = base ** degree
    if result == 0 and base != 0:
        raise ValueError
    return bounded(result)


def root(value, degree=2):
    if not isinstance(degree, (int, Fraction)) or degree != int(degree):
        raise ValueError
    degree = int(degree)
    if not 1 <= degree <= 1000 or value < 0 and degree % 2 == 0:
        raise ValueError
    if isinstance(value, Fraction):
        # integer_nthroot работает только с уже ограниченными целыми;
        # пользовательская строка в Sympy не передаётся.
        from sympy import integer_nthroot
        numerator, exact_n = integer_nthroot(abs(value.numerator), degree)
        denominator, exact_d = integer_nthroot(value.denominator, degree)
        if exact_n and exact_d:
            return Fraction(-numerator if value < 0 else numerator, denominator)
    value = as_decimal(value)
    result = abs(value).sqrt() if degree == 2 else abs(value) ** (Decimal(1) / degree)
    if result == 0 and value != 0:
        raise ValueError
    return bounded(-result if value < 0 else result)


def prepare(text):
    """Одинаковый смысл смешанных чисел в быстром и точном вычислителях."""
    if len(text) > 300 or r'\{' in text or r'\}' in text or '=' in text:
        return None
    text = re.sub(r'π|(?<!\\)\bpi\b', lambda _: r'\pi', text)
    # Не допускаем грамматически сложные функции, переменные и множества.
    lexical = re.sub(r'\\(?:dfrac|tfrac|frac|sqrt|pi|left|right|cdot|times|displaystyle)(?![A-Za-z])', '', text)
    if re.search(r'[^\d\s.,+*/^(){}\[\]|$−–—-]', lexical):
        return None
    text = normalize(text)
    text = _MIXED.sub(lambda m: '(' + m[1] + '+\\frac{'
                      + (m[2] or m[3]) + '}{' + (m[4] or m[5]) + '})', text)
    text = re.sub(r'(\\sqrt(?:\[[^\]]+\])?)\s*([0-9])', r'\1{\2}', text)
    return text if len(text) <= 300 else None


def parse(text):
    """Fraction/Decimal либо None; только вещественные числовые выражения."""
    text = prepare(text)
    if text is None:
        return None
    simple = parse_number(text)
    if simple is not None:
        return bounded(simple)
    tree = expressions.raw_tree(text.replace(r'\pi', 'Q'))
    if tree is None:
        return None
    remaining = MAX_NODES

    def visit(node, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > MAX_DEPTH:
            raise ValueError
        if not expressions._is_tree(node):
            if str(node) == 'Q':
                from sympy import pi
                return Decimal(str(pi.evalf(85)))
            if not _NUMBER.fullmatch(str(node)):
                raise ValueError
            return bounded(Fraction(str(node)))
        name = str(node.data)
        if name == '_ambig':
            # Не выбираем удобное толкование неоднозначного ввода.
            values = [visit(c, depth+1) for c in node.children]
            if not values or any(v != values[0] for v in values):
                raise ValueError
            return values[0]
        args = [c for c in node.children if expressions._is_tree(c)
                or _NUMBER.fullmatch(str(c)) or str(c) == 'Q']
        values = [visit(c, depth+1) for c in args]
        if name in ('number', 'latex_string', 'group_curly_parentheses',
                    'group_round_parentheses', 'group_square_brackets'):
            if len(values) != 1:
                raise ValueError
            return values[0]
        if name in ('add', 'sub') and len(values) == 1:
            return values[0] if name == 'add' else -values[0]
        if name == 'abs' and len(values) == 1:
            return abs(values[0])
        if name == 'square_root':
            if len(values) == 1:
                return root(values[0])
            if len(values) == 2:
                return root(values[1], values[0])
            raise ValueError
        if len(values) != 2:
            raise ValueError
        a, b = values
        if name == 'superscript':
            return power(a, b)
        name = {'adjacent_expressions': 'mul', 'fraction': 'div'}.get(name, name)
        return calculate(name, a, b)

    try:
        with localcontext() as context:
            context.prec = 80
            context.Emax, context.Emin = 1000, -1000
            return visit(tree)
    except Uncertain:
        raise
    except (ValueError, DecimalException, OverflowError, ZeroDivisionError, RecursionError):
        return None


def worker_text(text):
    """Сохраняет вещественную ветвь нечётного корня в точной проверке."""
    tree = expressions.raw_tree((prepare(text) or '').replace(r'\pi', 'Q'))
    remaining = MAX_NODES

    def render(node, depth=0):
        nonlocal remaining
        remaining -= 1
        if node is None or remaining < 0 or depth > MAX_DEPTH:
            raise Uncertain
        if not expressions._is_tree(node):
            if str(node) == 'Q':
                return r'\pi'
            if not _NUMBER.fullmatch(str(node)):
                raise Uncertain
            return str(node)
        name = str(node.data)
        args = [render(c, depth+1) for c in node.children
                if expressions._is_tree(c) or _NUMBER.fullmatch(str(c)) or str(c) == 'Q']
        if name in ('number', 'latex_string', 'group_curly_parentheses',
                    'group_round_parentheses', 'group_square_brackets') and len(args) == 1:
            return args[0]
        if name in ('add', 'sub') and len(args) == 1:
            return ('-' if name == 'sub' else '') + '(' + args[0] + ')'
        if name == 'abs' and len(args) == 1:
            return r'\left|' + args[0] + r'\right|'
        if name == 'square_root' and len(args) in (1, 2):
            degree, value = ('2', args[0]) if len(args) == 1 else args
            n, v = parse(degree), parse(value)
            if not isinstance(n, Fraction) or n.denominator != 1 or not 1 <= n <= 1000 or v is None:
                raise Uncertain
            if int(n) % 2 and v < 0:
                return r'(-\sqrt[' + degree + ']{-(' + value + ')})'
            return r'\sqrt[' + degree + ']{' + value + '}'
        if len(args) != 2:
            raise Uncertain
        a, b = args
        if name == 'superscript':
            exponent = parse(b)
            if exponent is None:
                raise Uncertain
            if isinstance(exponent, Fraction) and exponent.denominator % 2 == 1 \
                    and exponent.denominator != 1:
                base = parse(a)
                if base is None:
                    raise Uncertain
                if base < 0:
                    return (r'(-\sqrt[' + str(exponent.denominator) + ']{-('
                            + a + ')})^{' + str(exponent.numerator) + '}')
            return '(' + a + ')^{' + b + '}'
        op = {'add': '+', 'sub': '-', 'mul': r'\cdot ',
              'adjacent_expressions': r'\cdot ', 'div': '/', 'fraction': '/'}.get(name)
        if op is None:
            raise Uncertain
        return '(' + a + ')' + op + '(' + b + ')'

    return render(tree)

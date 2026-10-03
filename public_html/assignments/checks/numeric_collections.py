"""Точные числа в коллекциях и проверке допуска; вызывается внутри вычислителя."""
from ..check_answer import OK, UNKNOWN, WRONG, normalize, parse_number
from . import sets


class InvalidNumeric(ValueError):
    """Разобранная запись содержит недопустимую числовую операцию."""


def literal(text):
    """Быстрый путь: только школьное число без арифметических действий."""
    return parse_number(normalize(sets._strip_var(text)))


def _number(text):
    from . import formulas
    number = literal(text)
    if number is not None:
        return number
    item = formulas._parse(text, numeric=True)
    if item is None:
        return None
    if any(c.free_symbols for c in (item.expression, *item.components, *item.denominators)):
        raise InvalidNumeric('переменная в числовом ответе')
    defined = formulas._defined(item, formulas.Reference((), (), ()))
    if defined is False:
        raise InvalidNumeric('недопустимая промежуточная операция')
    return item.expression if defined is True else None


def _equal(a, b, tolerance=None):
    from sympy import simplify
    difference = simplify(a-b)
    same = difference == 0 or difference.equals(0)
    if same is None:
        raise ValueError('равенство не установлено')
    return bool(same)


def check_number_with_tolerance(value, reference, tolerance):
    """Включённая граница допуска проверяется без промежуточного округления."""
    from sympy import simplify, sympify
    from ..check_answer import MAX_EXPR_LEN
    if len(reference) > MAX_EXPR_LEN or len(tolerance) > MAX_EXPR_LEN:
        raise ValueError('слишком длинный эталон или допуск')
    expected, limit = _number(reference), _number(tolerance)
    if expected is None or limit is None or sympify(limit).is_nonnegative is not True:
        raise ValueError('эталон или допуск не разобран как допустимое число')
    if len(value) > MAX_EXPR_LEN:
        return UNKNOWN
    try:
        student = _number(value)
    except InvalidNumeric:
        return WRONG
    if student is None:
        return UNKNOWN
    distance = simplify(abs(student-expected)-limit)
    if distance.is_nonpositive is True:
        return OK
    if distance.is_positive is True:
        return WRONG
    return UNKNOWN


def _pairs_equal(a, b, *, unordered=False):
    def compare(left, right, tolerance=None):
        if unordered:
            return sets._multiset_equal(left, right, equal=_equal)
        return len(left) == len(right) and all(_equal(x, y) for x, y in zip(left, right))

    def unique(pairs):
        out = []
        for pair in pairs:
            if not any(compare(pair, other) for other in out):
                out.append(pair)
        return out
    return sets._multiset_equal(unique(a), unique(b), equal=compare)


def check(value, reference, *, kind, unordered=False):
    parser = sets.parse_set if kind == 'set' else sets.parse_pairs
    if len(reference) > sets.MAX_COLLECTION_LEN:
        raise ValueError('слишком длинный эталон')
    expected = parser(reference, value_parser=_number, equal=_equal)
    if expected is None:
        raise ValueError('числовой эталон не разобран')
    if len(value) > sets.MAX_COLLECTION_LEN:
        return UNKNOWN
    try:
        student = parser(value, value_parser=_number, equal=_equal)
    except InvalidNumeric:
        return WRONG
    if student is None:
        return UNKNOWN
    same = (sets._multiset_equal(expected, student, equal=_equal)
            if kind == 'set' else _pairs_equal(expected, student, unordered=unordered))
    return OK if same else WRONG

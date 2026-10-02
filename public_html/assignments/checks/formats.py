"""Строгие записи ответа: цифры, десятичное число и отношение."""
import re
from fractions import Fraction

DIGITS_RE = re.compile(r'[0-9]+')
DECIMAL_RE = re.compile(r'-?[0-9]+(?:,[0-9]+)?')


def digits(text):
    return bool(len(text) <= 256 and DIGITS_RE.fullmatch(text))


def decimal(text):
    if len(text) > 256 or not DECIMAL_RE.fullmatch(text):
        return None
    return Fraction(text.replace(',', '.'))


def ratio(text, *, allow_quotient=False):
    """Числовые выражения в обеих частях; порядок проверяет слот."""
    if allow_quotient and ':' not in text:
        text += ':1'
    return proportion(text)


def proportion(text):
    """Отношение числовых выражений: дроби допустимы в обеих частях."""
    from decimal import DecimalException
    from . import numeric
    if len(text) > 601 or '=' in text:
        return None
    parts = text.split(':')
    if len(parts) != 2:
        return None
    # Проверяем синтаксис обеих частей до возможного точного fallback.
    parts = [numeric.prepare(part) for part in parts]
    if any(part is None for part in parts):
        return None
    a, b = (numeric.parse(part) for part in parts)
    if a is None or b is None:
        return None
    if b == 0:
        return None
    try:
        result = numeric.calculate('div', a, b)
    except numeric.Uncertain:
        raise
    except (ValueError, DecimalException, OverflowError, ZeroDivisionError):
        return None
    return result


def check_ratio_exact(value, reference, *, allow_reverse=False, allow_quotient=False):
    """Пограничная арифметика проверяется только в ограниченном процессе."""
    from ..check_answer import OK, UNKNOWN, WRONG
    from . import formulas, numeric
    if allow_quotient and ':' not in value:
        value += ':1'
    parts, expected = value.split(':'), reference.split(':')
    if len(parts) != 2 or len(expected) != 2:
        return WRONG
    parts = [numeric.prepare(part) for part in parts]
    expected = [numeric.prepare(part) for part in expected]
    if any(part is None for part in (*parts, *expected)):
        return WRONG
    def quotient(pair):
        return '(' + pair[0] + ')/(' + pair[1] + ')'
    try:
        parts = [numeric.worker_text(part) for part in parts]
        expected = [numeric.worker_text(part) for part in expected]
        spec, _ = formulas.parse_reference(quotient(expected))
        direct = formulas.check(quotient(parts), spec)
        if direct == OK or not allow_reverse:
            return direct
        # Перестановка не должна узаконить исходное деление на ноль.
        reverse_text = quotient(parts[::-1]) + '+0/(' + parts[1] + ')'
        reverse = formulas.check(reverse_text, spec)
        return OK if reverse == OK else UNKNOWN if UNKNOWN in (direct, reverse) else WRONG
    except formulas.FormulaUnavailable:
        # Недоступность вычислителя — не вердикт: наверх, сверка повторится.
        raise
    except ValueError:
        return UNKNOWN


def check_proportion_exact(value, reference):
    """Точная проверка отношения, допускающего перестановку частей."""
    return check_ratio_exact(value, reference, allow_reverse=True)


def oge_kind(codes):
    """Не угадывать формат при неоднозначных экзаменационных метках."""
    kinds = set()
    for code in codes or []:
        match = re.fullmatch(r'OGE_[0-9]{4}_([0-9]{2})', str(code))
        if match:
            number = int(match[1])
            kinds.add('digits' if number in {1, 7, 11, 13, 19}
                      else 'decimal' if 1 <= number <= 19 else None)
    # Пустая строка отличает конфликт меток от отсутствия формата ОГЭ.
    return kinds.pop() if len(kinds) == 1 else ('' if kinds else None)

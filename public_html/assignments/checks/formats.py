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


def ratio(text):
    parts = text.split(':')
    if len(parts) != 2:
        return None
    a, b = (decimal(p.strip()) for p in parts)
    if a is None or b is None or b == 0:
        return None
    return a / b


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

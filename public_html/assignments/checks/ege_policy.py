"""Формат ЕГЭ выбирается по линии и вопросу, эталон берётся из автора."""
import re
from fractions import Fraction

from . import formats, sets


def plain_answer(answer):
    text = re.sub(r'\\(?:displaystyle|left|right)|\$|\\[()[\]]', '', answer or '')
    return text.strip().rstrip(';').strip()


def _decimal_reference(text):
    raw = text.replace('{,}', ',').strip()
    if formats.decimal(raw) is not None:
        return raw
    value = sets.numeric_value(raw)
    if not isinstance(value, Fraction):
        return ''
    denominator = value.denominator
    for divisor in (2, 5):
        while denominator % divisor == 0:
            denominator //= divisor
    if denominator != 1:
        return ''
    # Точное деление без float и округления периодической дроби.
    from decimal import Decimal, localcontext
    with localcontext() as ctx:
        ctx.prec = max(32, len(str(abs(value.numerator))) + value.denominator.bit_length() + 2)
        return format(Decimal(value.numerator) / Decimal(value.denominator), 'f').replace('.', ',')


def ege_draft(answer, condition='', exam_codes=None, *, source_number='', subitem_label=''):
    """None — не ЕГЭ; '' — доказательство либо неоднозначный/неразобранный ответ."""
    from .mask import parse_mask
    numbers = {int(m[1]) for code in exam_codes or []
               if (m := re.fullmatch(r'EGE_PROFILE_2027_(\d{2})', str(code)))}
    if not numbers:
        return None
    if len(numbers) != 1:
        return ''
    number = numbers.pop()
    text = plain_answer(answer)
    if not text or re.search(r'докажите|обоснуйте|приведите\s+пример', condition or '', re.I):
        return ''

    def slot(kind, value):
        candidate = '{{' + kind + ': ' + value + '}}'
        return candidate if parse_mask(candidate).is_valid else ''

    if 1 <= number <= 13:
        prototype = '.'.join(str(source_number).split('.')[:2])
        count_question = bool(re.search(r'найдите\s+количество|сколько\s+(?:из\s+этих\s+)?точек', condition, re.I))
        kind = 'digits' if number == 9 and (
            prototype in {'9.1', '9.3', '9.6', '9.8'} or (not source_number and count_question)) else 'decimal'
        reference = _decimal_reference(text)
        return slot(kind, reference) if reference else ''
    if number in {16, 19}:
        return slot('range', text)
    if number == 14:
        if re.search(r'\\in\s*\\mathbb\{Z\}|∈\s*ℤ|(?<![A-Za-z])[nkm](?![A-Za-z])', text):
            return slot('series', text)
        # В книге списки корней разделены запятыми; десятичные запятые
        # нормализованного LaTeX защищены {,}.
        values = text.replace('{,}', '\x00').replace(',', ';').replace('\x00', '{,}')
        return slot('number', values) if sets.numeric_value(values) is not None else slot('range', values)
    if ':' in text and formats.ratio(text.replace('{,}', ',')) is not None:
        return slot('ratio', text.replace('{,}', ','))
    if sets.numeric_value(text) is not None:
        return slot('number', text)
    if number == 20:
        # Конкретные вопросы «да/нет» и наборы чисел обслуживает общий разбор.
        return None
    return slot('range', text)

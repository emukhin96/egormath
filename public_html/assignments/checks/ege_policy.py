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


# Единица после числового ответа части 2 («204 м», «60°», «3,1·10^{-21} Дж»):
# маска — слот без единицы и единица текстом после него.
UNIT_RE = re.compile(
    r'^(?P<value>.*?[\d}])\s*(?P<unit>°|\^\{?\\circ\}?'
    r'|(?:\\text\{\s*)?(?:мм|см|дм|км|м|кг|г|т|мин|ч|с|Вт|кВт|Ом|Дж|кДж|В|А|руб\.?|рублей|тыс\.\s*руб\.?|млн\s*руб\.?)\}?'
    r'|(?:\\mathrm\{\s*[cс]\s*\}|[cс])\s*\^\s*\{\s*-\s*1\s*\})\.?$')
# Ответ-формула с параметром условия (№17: «125\sqrt{2R}», «14,4\sqrt{2/(2-n)}»).
PARAMETER_RE = re.compile(r'(?<![A-Za-z\\])[A-Za-z](?![A-Za-z])')
# Параметр серии вне n, k, m, l (книга пишет «2πp, p ∈ Z»).
SERIES_PARAMS = 'nkml'


def _with_unit(text, draft):
    """Маска числа с единицей: слот по числу и единица текстом."""
    match = UNIT_RE.match(text)
    if not match or not match.group('value').strip():
        return ''
    inner = draft(match.group('value').strip())
    if not inner:
        return ''
    unit = match.group('unit')
    if unit == '°' or 'circ' in unit:
        return inner + '°'
    unit = re.sub(r'\\text\{\s*|\}$', '', unit).strip() if unit.startswith('\\text') else unit
    if re.search(r'\^\s*\{\s*-\s*1', unit):
        unit = '$\\text{с}^{-1}$'
    return f'{inner} {unit}'


def _rename_series_parameters(text):
    """«…+2πp, p ∈ Z» → свободная буква из n, k, m, l (их знает ``series``)."""
    used = set(re.findall(r'(?<![A-Za-z\\])([a-z])\s*(?:\\in|∈)', text))
    foreign = sorted(used - set(SERIES_PARAMS))
    free = [letter for letter in SERIES_PARAMS if letter not in used]
    for letter in foreign:
        if not free:
            return text
        text = re.sub(rf'(?<![A-Za-z\\]){letter}(?![A-Za-z])', free.pop(0), text)
    return text


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
    if number >= 14:
        with_unit = _with_unit(text, lambda value: ege_draft(
            value, condition, exam_codes, source_number=source_number,
            subitem_label=subitem_label))
        if with_unit:
            return with_unit
    if number == 20:
        # «да (например, 729)»: пример проверяет учитель, ответ — да/нет.
        yes_no = re.fullmatch(r'(да|нет)\s*[(,;].*', text, re.S)
        if yes_no:
            return slot('yesno', yes_no.group(1))
    # Только формула-значение: равенства и неравенства («x=2», «a>1»)
    # уходят в общий разбор, невалидная маска — тоже.
    if number in {15, 17, 18} and not re.search(
            r'[:;=<>≤≥≠]|\\in|\\[lg]e(?:q)?(?![A-Za-z])|\\ne(?:q)?(?![A-Za-z])', text):
        letters = sorted(set(PARAMETER_RE.findall(re.sub(r'\\[A-Za-z]+', ' ', text))))
        if letters and sets.numeric_value(text) is None:
            expression = slot('expression', f"{text} | positive: {','.join(letters)}")
            if expression:
                return expression
    if number == 14:
        text = _rename_series_parameters(text)
        if re.search(r'\\in\s*\\mathbb\{Z\}|∈\s*ℤ|(?<![A-Za-z])[nkm](?![A-Za-z])', text):
            # Десятичная запятая в сдвиге серии («arctg 5{,}5») — точкой:
            # ``series`` делит серии по «,» и «;».
            return slot('series', text.replace('{,}', '.'))
        # В книге списки корней разделены запятыми; десятичные запятые
        # нормализованного LaTeX защищены {,}.
        values = text.replace('{,}', '\x00').replace(',', ';').replace('\x00', '{,}')
        return slot('number', values) if sets.numeric_value(values) is not None else slot('range', values)
    if ':' in text:
        from . import numeric
        try:
            ratio = formats.ratio(text.replace('{,}', ','))
        except numeric.Uncertain:
            return ''
        if ratio is not None:
            return slot('ratio', text.replace('{,}', ','))
    if sets.numeric_value(text) is not None:
        return slot('number', text)
    if number == 20:
        # Конкретные вопросы «да/нет» и наборы чисел обслуживает общий разбор.
        return None
    return slot('range', text)

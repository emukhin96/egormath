"""Строгие записи ответа: цифры, десятичное число и отношение."""
import re
from fractions import Fraction

DIGITS_RE = re.compile(r'[0-9]+')
DECIMAL_RE = re.compile(r'-?[0-9]+(?:,[0-9]+)?')

# Подсказки о формате записи: показываются под полем при вводе (mask.js) и в
# бейдже «формат», когда сервер отверг запись, а не значение.
FORMAT_HINTS = {
    'digits': 'Только цифры подряд, без пробелов, запятых и дробей — например 215',
    'decimal': 'Целое число или десятичная дробь через запятую, без точки, '
               'обыкновенных дробей и единиц — например 0,8 или -2,5',
    'ratio': 'Отношение через двоеточие — например 2:3',
    'ratio_quotient': 'Отношение через двоеточие или его значение дробью — например 2:3 или 2/3',
    'proportion': 'Отношение через двоеточие в любом порядке — например 2:3 или 3:2',
    'proportion_quotient': 'Отношение через двоеточие или дробью в любом порядке — например 2:3 или 3/2',
}


def digits(text):
    return bool(len(text) <= 256 and DIGITS_RE.fullmatch(text))


def decimal(text):
    if len(text) > 256 or not DECIMAL_RE.fullmatch(text):
        return None
    return Fraction(text.replace(',', '.'))


def format_hint(kind, *, allow_quotient=False):
    key = kind + ('_quotient' if allow_quotient and kind in ('ratio', 'proportion') else '')
    return FORMAT_HINTS.get(key, '')


def wrong_format(kind, text, *, allow_quotient=False):
    """Запись заведомо не в формате бланка: ``4/5`` или ``0.8`` для decimal,
    ``0215,0`` для digits, дробь без двоеточия для ratio без ``quotient``.
    Неверное значение в правильном формате сюда не относится."""
    if kind == 'digits':
        return not digits(text)
    if kind == 'decimal':
        return decimal(text) is None
    if kind in ('ratio', 'proportion'):
        return ':' not in text and not allow_quotient
    return False


_RATIO_OPERATOR_NAMES = r'(?:sin|cos|tan|tg|cot|ctg|sec|csc|asin|acos|atan)'
_RATIO_TRIG = re.compile(
    r'(?:\\operatorname\s*\{\s*'
    rf'(?:{_RATIO_OPERATOR_NAMES}\s*|'
    rf'\\mathrm\s*\{{\s*{_RATIO_OPERATOR_NAMES}\s*\}}\s*)\}}'
    r'|\\(?:sin|cos|tan|tg|cot|ctg|sec|csc|arcsin|arccos|arctan)(?![A-Za-z])'
    r'|(?<![A-Za-z\\])(?:sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan)\b)'
    r'(?:\s*\^\s*(?:\{\s*\d+\s*\}|\d))?')


def _ratio_part(text):
    """Ограниченная арифметика быстро; числовая тригонометрия — в процессе."""
    from . import numeric
    prepared = numeric.prepare(text)
    if prepared is not None:
        return prepared
    # Проверяем только лексику: сами функции, исходные знаменатели и
    # вещественную область проверит ограниченный числовой вычислитель.
    # Удаление имён здесь не подменяет выражение при вычислении.
    skeleton, count = _RATIO_TRIG.subn('', text)
    skeleton = skeleton.replace(r'\circ', '').replace(r'\degree', '').replace('°', '')
    if not count or numeric.prepare(skeleton) is None:
        return None
    return text


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
    prepared = [numeric.prepare(part) for part in parts]
    if any(part is None for part in prepared):
        if all(_ratio_part(part) is not None for part in parts):
            raise numeric.Uncertain
        return None
    a, b = (numeric.parse(part) for part in prepared)
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
    parts = [_ratio_part(part) for part in parts]
    expected = [_ratio_part(part) for part in expected]
    if any(part is None for part in (*parts, *expected)):
        return WRONG
    def quotient(pair):
        return '(' + pair[0] + ')/(' + pair[1] + ')'
    try:
        parts = [numeric.worker_text(part) if numeric.prepare(part) is not None else part
                 for part in parts]
        expected = [numeric.worker_text(part) if numeric.prepare(part) is not None else part
                    for part in expected]
        spec = formulas.FormulaSpec(quotient(expected), False, numeric=True)
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


def check_proportion_exact(value, reference, *, allow_quotient=False):
    """Точная проверка отношения, допускающего перестановку частей."""
    return check_ratio_exact(value, reference, allow_reverse=True,
                             allow_quotient=allow_quotient)


def check_number_exact(value, reference):
    """Точное вещественное число; исходные области проверяет вычислитель."""
    from . import formulas
    return formulas.check(value, formulas.FormulaSpec(reference, False, numeric=True))


def check_number_with_tolerance(value, reference, tolerance):
    """Точные дроби без процесса; числовые выражения с исходными областями."""
    from . import formulas, numeric_collections
    from ..check_answer import MAX_EXPR_LEN, OK, UNKNOWN, WRONG
    if len(value) > MAX_EXPR_LEN:
        return UNKNOWN
    values = [numeric_collections.literal(text) for text in (value, reference, tolerance)]
    if all(number is not None for number in values):
        student, expected, limit = values
        if limit < 0:
            return UNKNOWN
        return OK if abs(student-expected) <= limit else WRONG
    return formulas.check(value, formulas.FormulaSpec(reference, False, numeric=True,
                                                      tolerance=tolerance))


def _collection_literals(value, reference, kind):
    from . import sets, numeric_collections
    parser = {'set': sets.parse_set, 'range': sets.parse_range}.get(kind, sets.parse_pairs)
    return (parser(reference, value_parser=numeric_collections.literal),
            parser(value, value_parser=numeric_collections.literal))


def collection_needs_worker(value, reference, *, kind):
    """Тот же быстрый путь для проверки и пропуска после сбоя процесса."""
    from . import sets
    if not (value or '').strip() or len(value) > sets.MAX_COLLECTION_LEN:
        return False
    return any(item is None for item in _collection_literals(value, reference, kind))


def validate_collection_reference(reference, *, kind, unordered=False):
    """Нелитеральный эталон должен пройти тот же ограниченный вычислитель."""
    from . import formulas
    expected, _ = _collection_literals(reference, reference, kind)
    if expected is not None:
        return
    mode = 'pair-unordered' if unordered else kind
    result = formulas._run_worker({'payload': reference, 'multiple': False,
                                   'mode': mode, 'numeric': True})
    if result.get('error'):
        raise ValueError(result['error'])
    if result.get('display') != reference:
        raise formulas.FormulaUnavailable('не удалось проверить ответ из нескольких значений')


def check_collection_exact(value, reference, *, kind, unordered=False):
    """Числовые списки: точные дроби сразу, арифметика в вычислителе."""
    from . import formulas, sets
    from ..check_answer import OK, UNKNOWN, WRONG
    if len(value) > sets.MAX_COLLECTION_LEN:
        return UNKNOWN
    expected, student = _collection_literals(value, reference, kind)
    if expected is not None and student is not None:
        if kind == 'set':
            same = sets.sets_equal(expected, student)
        elif kind == 'range':
            same = sets.ranges_equal(expected, student)
        else:
            same = sets.pairs_equal(expected, student, unordered=unordered)
        return OK if same else WRONG
    mode = kind if not unordered else 'pair-unordered'
    return formulas.check(value, formulas.FormulaSpec(reference, False, mode=mode,
                                                      numeric=True))


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

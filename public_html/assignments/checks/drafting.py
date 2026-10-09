"""Контекстный черновик: подписи берём из вопроса, эталоны — из ответа.

None означает, что контекст не распознан; пустая строка — что он распознан,
но безопасно сопоставить поля и эталоны не удалось. Задачи здесь не решаем.
"""
import re

from . import sets

_SOLVE = re.compile(r'реши\w*\s+(?:следующ\w*\s+)?(?:уравнен|неравенств|систем)|найди\w*\s+(?:все\s+)?корни', re.I)
_AGGREGATE_RE = re.compile(
    r'(?:укажите|найдите|запишите|вычислите)[^.?!]*?'
    r'(?:наибольш|наименьш|сумм|количеств|числ[оа]\b|произведени|длин[ау]\s+промежутк)', re.I)
_EQUATION_REQUEST = re.compile(
    r'(?:состав|запиш|напиш)\w*.{0,40}уравнен', re.I)
_ASSIGNMENT = re.compile(r'(?<![A-Za-z\\])([a-z](?:_\{?\d+\}?)?)\s*=\s*', re.I)
_GEOMETRY = re.compile(r'треугольник|ромб|квадрат|прямоугольник|трапец|окружност|круг|параллелограмм|пирамид|призм|цилиндр|конус|шар', re.I)
_UNIT = re.compile(r'(?<![а-яё])(мм|см|дм|км|м)(?:\s*(?:\^\{?([23])\}?|([²³])))?(?![а-яё])', re.I)


def _plain(text):
    text = (text or '').replace('$', '')
    text = re.sub(r'\\(?:text|mathrm)\{([^{}]*)\}', r'\1', text)
    return re.sub(r'\s+', ' ', text).strip().rstrip('.')


def _slot(kind, value):
    return '{{' + kind + ': ' + value + '}}'


def _equation(answer, condition):
    # Обычные школьные неизвестные; параметры a, b не становятся полями.
    variables = sorted(set(re.findall(r'(?<![A-Za-z\\])[xyz](?![A-Za-z])', condition)))
    # Решение неравенства — множество: подпись «x ∈», а не «x =».
    relation = r' \in' if re.search(r'неравенств', condition, re.I) else ' ='
    assignments = []
    for match in _ASSIGNMENT.finditer(answer):
        prefix = answer[:match.start()]
        if prefix.strip() and not re.search(
                r'(?:[,;]|\bи(?:ли)?)\s*$', prefix, re.I):
            continue
        assignments.append(match)
    if assignments:
        groups = {}
        for i, match in enumerate(assignments):
            variable = re.sub(r'_\{?\d+\}?', '', match[1])
            value = answer[match.end():assignments[i+1].start() if i+1 < len(assignments) else None]
            value = re.sub(r'\s+(?:и|или)\s*$', '', value.strip(' ,; ')).strip(' ,; ')
            groups.setdefault(variable, []).append(value)
        if variables and set(groups) != set(variables):
            return ''
        if len(groups) > 1 and any(len(values) != 1 for values in groups.values()):
            return ''  # Несколько решений системы нельзя разъединять по координатам.
        if len(groups) > 1 and any(sets.numeric_value(values[0]) is None for values in groups.values()):
            return ''
        fields = []
        for variable, values in groups.items():
            value = '; '.join(values)
            if sets.parse_range(value) is None:
                return ''
            # Автор записал ответ равенством (x=2) — подпись «x =» и для
            # неравенства; «x ∈» только для промежутка без явного «x =».
            fields.append(f'${variable} =$' + _slot('range', value))
        return ', '.join(fields)
    if len(variables) > 1:
        pairs = sets.parse_pairs(answer)
        if not pairs or any(len(pair) != len(variables) for pair in pairs):
            return ''
        if len(pairs) == 1:
            return ', '.join(f'${var} =$' + _slot('range', str(value))
                             for var, value in zip(variables, pairs[0]))
        return '$(' + '; '.join(variables) + ') =$' + _slot('pair', answer)
    if len(variables) != 1:
        return ''
    # У корней уравнения «и» перечисляет (x=1 и x=2 → 1; 2); в решении
    # неравенства «и» — пересечение (x>-3 и x<3), его оставляем parse_range.
    inequality = bool(re.search(r'неравенств', condition, re.I))
    value = re.sub(r'\s+или\s+' if inequality else r'\s+(?:и|или)\s+', '; ', answer)
    if sets.parse_range(value) is None:
        return ''
    if re.search(r'[<>≤≥]|\\(?:le|ge)(?:q|qslant)?(?![A-Za-z])', value):
        # Ответ сам записан неравенством (x<2): подпись «x ∈» неуместна.
        return _slot('range', value)
    return f'${variables[0]}{relation}$' + _slot('range', value)


def _geometry(answer, condition):
    questions = re.split(r'найдите|вычислите|определите', condition, flags=re.I)
    if len(questions) < 2:
        return ''
    question = questions[-1].strip().rstrip('.?')
    answer_units = list(_UNIT.finditer(answer))
    condition_units = list(_UNIT.finditer(condition))

    def single_unit(matches):
        names = {match[1].lower() for match in matches}
        return next(iter(names)) if len(names) == 1 else ''

    answer_unit = single_unit(answer_units)
    unit = answer_unit or single_unit(condition_units)
    value = _UNIT.sub('', answer).strip()
    # Две одноимённые длины можно однозначно назвать по их величине.
    if re.match(r'катеты\b', question, re.I):
        values = re.split(r'\s+и\s+|\s*;\s*', value)
        parsed = [(sets.numeric_value(v), v.strip()) for v in values]
        if len(parsed) != 2 or any(n is None for n, v in parsed):
            return ''
        parsed.sort(key=lambda pair: pair[0])
        if parsed[0][0] == parsed[1][0]:
            labels = ('Первый катет равен', 'второй катет равен')
        else:
            labels = ('Меньший катет равен', 'больший катет равен')
        return ', '.join(label + ' ' + _slot('number', v) + (' ' + unit if unit else '')
                         for label, (_, v) in zip(labels, parsed))
    quantities = [(r'площадь\b', 'S', 2), (r'периметр\b', 'P', 1),
                  (r'объ[её]м\b', 'V', 3)]
    for pattern, symbol, power in quantities:
        if not re.match(pattern, question, re.I):
            continue
        value = re.sub(r'^[SPV](?:_\{?[A-Z]+\}?)?\s*=\s*', '', value)
        if sets.numeric_value(value) is None:
            return ''
        names = set(re.findall(r'(?<![A-Za-z])[A-Z]{3,4}(?![A-Za-z])', question))
        if not names:
            names = set(re.findall(r'(?:ромб|треугольник|квадрат|прямоугольник|трапец|параллелограмм)[а-я]*\s+([A-Z]{3,4})(?![A-Za-z])', condition, re.I))
        # Используем обозначение только при однозначной привязке к фигуре.
        label = symbol + ('_{' + next(iter(names)) + '}' if len(names) == 1 else '')
        suffix = (' ' + unit + (f'$^{power}$' if power > 1 else '')) if unit else ''
        return f'${label} =$' + _slot('number', value) + suffix
    # Не теряем простой числовой ответ из-за незнакомой формулировки вопроса.
    if sets.numeric_value(value) is not None:
        if re.match(r'другое основание\b', question, re.I):
            return 'Другое основание равно ' + _slot('number', value) + (' ' + unit if unit else '')
        return _slot('number', value) + (' ' + answer_unit if answer_unit else '')
    return ''


def contextual_draft(answer, condition):
    """Выбирает смысл полей, не используя числа условия как эталоны."""
    answer, condition = _plain(answer), _plain(condition)
    if not condition:
        return None
    if _SOLVE.search(condition):
        # «Решите неравенство … В ответе укажите наибольшее целое решение /
        # сумму целых решений»: ответ — число, а не множество решений.
        if _AGGREGATE_RE.search(condition) and sets.numeric_value(answer) is not None:
            return None
        return _equation(answer, condition)
    if _EQUATION_REQUEST.search(condition) and '=' in answer:
        return _slot('equation', answer)
    if _ASSIGNMENT.search(answer):
        drafted = _equation(answer, condition)
        if drafted:
            return drafted
    if _GEOMETRY.search(condition) and re.search(r'найдите|вычислите|определите', condition, re.I):
        return _geometry(answer, condition)
    return None

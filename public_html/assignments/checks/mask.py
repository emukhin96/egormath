"""Маска ответа ученика: авторский шаблон вида
``Меньшая сторона равна {{number: 10}} см``.

Слот открывается только последовательностью ``{{имя_типа:`` — в LaTeX такого
не бывает, поэтому ``\\frac{1}{x^{2}}`` в тексте маски не путается со слотом.
Закрывающие ``}}`` ищутся с подсчётом баланса фигурных скобок (экранированные
``\\{`` ``\\}`` не считаются), так что внутри слота можно писать любой LaTeX.

Разделители: варианты ``choice`` — ``|``, правильный помечен ``*``;
несколько значений (пары, элементы множества) — ``;`` (запятая занята
десятичной дробью).
"""
import hashlib
import random
import re
from dataclasses import dataclass, field

from ..check_answer import OK, UNKNOWN, WRONG, _compact, normalize
from . import expressions, sets, formats, series, formulas

NUMBER = 'number'
DIGITS = 'digits'
DECIMAL = 'decimal'
RATIO = 'ratio'
PROPORTION = 'proportion'
CHOICE = 'choice'
SIMPLIFY = 'simplify'
FACTOR = 'factor'
PAIR = 'pair'
SET = 'set'
EQUATION = 'equation'
RANGE = 'range'
SERIES = 'series'
ORDER = 'order'
EXPRESSION = 'expression'
EXPRESSIONS = 'expressions'

KINDS = {
    NUMBER: 'число',
    DIGITS: 'последовательность цифр',
    DECIMAL: 'десятичное число',
    RATIO: 'отношение с заданным порядком',
    PROPORTION: 'отношение с допустимой перестановкой',
    CHOICE: 'выбор из вариантов',
    SIMPLIFY: 'выражение для упрощения',
    FACTOR: 'разложение на множители',
    PAIR: 'упорядоченная пара (пары)',
    SET: 'конечное множество чисел',
    EQUATION: 'уравнение',
    RANGE: 'числовое множество',
    SERIES: 'периодическое множество кратных π',
    ORDER: 'расставить в порядке',
    EXPRESSION: 'эквивалентное выражение',
    EXPRESSIONS: 'выражения в любом порядке',
}

# Пресеты — готовые списки вариантов для choice: имя → варианты
PRESETS = {
    'compare': ('<', '=', '>'),
    'sign': ('+', '0', '−'),
    'yesno': ('да', 'нет'),
    'truefalse': ('верно', 'неверно'),
    'parity': ('чётная', 'нечётная', 'общего вида'),
}

# Справка для формы учителя: (пример, пояснение)
HELP = (
    ('{{digits: 234}}', 'только цифры в точном порядке, без пробелов; 234,00 и 468/2 не принимаются'),
    ('{{decimal: -0,5}}', 'целое или десятичное число с запятой; дроби и выражения не принимаются'),
    ('{{ratio: 1:2}}', 'отношение: 2:4 и 8:16 верны; 2:1 и 0,5 неверны'),
    ('{{proportion: 1:2}}', 'отношение с перестановкой: 1:2, 2:1 и 4:2 верны; 0,5 неверно'),
    ('{{number: 10}}', 'число; принимается любая численно равная запись '
                       '(2,5 / 5/2 / \\frac{5}{2}); допуск — {{number: 3,14 ~ 0,01}}'),
    ('{{choice: мальчиков|*девочек}}', 'выпадающий список, правильный вариант со звёздочкой'),
    ('{{compare: >}}', 'пресет < = >'),
    ('{{sign: +}}', 'пресет + 0 −'),
    ('{{yesno: да}}', 'пресет да / нет'),
    ('{{truefalse: верно}}', 'пресет верно / неверно'),
    ('{{parity: чётная}}', 'пресет чётная / нечётная / общего вида '
                           '(к любому пресету можно дописать свои варианты через |)'),
    ('{{simplify: \\frac{2}{a+3}}}', 'выражение: эквивалентно эталону и не менее упрощено'),
    ('{{expression: 2a | positive: a}}', 'любое эквивалентное выражение; a — положительный параметр'),
    ('{{expressions: a\\sqrt{3}; 2a | positive: a}}', 'все выражения через ; в любом порядке, с учётом кратности'),
    ('{{factor: 2(x-1)(x+1)}}', 'разложение на неприводимые множители, порядок любой'),
    ('{{pair: (2,5; -3); (5; -6)}}', 'упорядоченные пары через ; порядок пар не важен'),
    ('{{pair: (8;12); (5;15) | unordered}}', 'варианты длин сторон; порядок внутри и между парами не важен'),
    ('{{set: -2; 1}}', 'множество чисел, порядок не важен; {{set: }} — «нет решений»'),
    ('{{equation: y=x+5}}', 'уравнение в приведённом виде (y-x=5 тоже верно, 2y=2x+10 — нет)'),
    ('{{range: 1; 4}}', 'корни уравнения: одно поле независимо от количества корней'),
    ('{{series: \\pi+2\\pi*n}}', 'периодическое множество рациональных кратных π'),
    ('{{range: (-\\infty;-5)\\cup(5;+\\infty)}}', 'числовое множество; неравенства '
                                               '(x<-5, x>5), «и» — пересечение, '
                                               'нет решений / ℝ, границы вроде \\sqrt{2} и 7/3'),
    ('{{order: \\sqrt[6]{5}|\\sqrt[5]{4}|2}}', 'элементы в правильном порядке; '
                                              'ученику показываются перемешанными'),
)

_OPEN_RE = re.compile(r'\{\{\s*([a-z]+)\s*:')
_TOLERANCE_RE = re.compile(r'^(.*?)\s*~\s*([^~]+)$')
_ANSWER_MATH_RE = re.compile(r'\$([^$]+)\$')
_COORDINATE_PAIR_RE = re.compile(
    r'(?:(?<![A-Za-zА-Яа-я])'
    r'(?P<label>(?:\\(?:vec|overrightarrow)\s*'
    r'(?:\{[^{}]+\}|[A-Za-zА-Яа-я](?:_\{?[0-9]+\}?)?)|'
    r'(?:[A-Za-z]{1,4}|[А-Я])(?:_\{?[0-9]+\}?)?))\s*)?'
    r'\(\s*(?P<x>[^;()]+?)\s*;\s*(?P<y>[^;()]+?)\s*\)')
_UNIT_TOKEN_RE = re.compile(
    r'сторон(?:а|ы)?|'
    r'(?:мм|см|дм|м|км)(?:\s*/\s*(?:с|мин|ч))|'
    r'(?:мм|см|дм|м|км|г|кг|с|мин|ч|Н)(?:\s*\^\s*[23])?|'
    r'°|градус(?:а|ов)?|раз(?:а)?|'
    r'единиц(?:а|ы)?|кв\.\s*ед\.|куб\.\s*ед\.', re.I)


@dataclass
class Slot:
    index: int
    kind: str
    raw: str
    preset: str = None
    reference: str = ''
    options: list = field(default_factory=list)
    correct: str = ''
    items: list = field(default_factory=list)
    tolerance: object = None
    data: object = None
    error: str = ''
    unordered_pair: bool = False

    @property
    def name(self):
        return f's{self.index}'

    @property
    def type_name(self):
        return self.preset or self.kind

    @property
    def is_valid(self):
        return not self.error

    @property
    def uses_math_field(self):
        return self.kind in (SIMPLIFY, FACTOR, EQUATION, EXPRESSION, EXPRESSIONS)

    @property
    def label(self):
        if self.kind == PAIR and self.unordered_pair:
            return 'группы чисел (порядок не важен)'
        return KINDS.get(self.kind, self.kind)

    def shuffled(self, seed=''):
        """Элементы ``order`` в перемешанном (но стабильном для seed) порядке:
        список (исходный индекс, текст)."""
        indices = list(range(len(self.items)))
        if len(indices) > 1:
            digest = hashlib.sha1(f'{seed}:{self.index}'.encode()).hexdigest()
            random.Random(digest).shuffle(indices)
            if indices == sorted(indices):
                indices = indices[1:] + indices[:1]
        return [(i, self.items[i]) for i in indices]

    def order_tokens(self, seed=''):
        """Исходный индекс → непрозрачный токен формы. Без SECRET_KEY
        клиент не восстановит правильную перестановку ``0|1|2|…``."""
        from django.conf import settings
        out = {}
        for i in range(len(self.items)):
            raw = f'{settings.SECRET_KEY}\0{seed}\0{self.index}\0{i}'.encode()
            out[i] = hashlib.sha1(raw).hexdigest()[:12]
        return out


@dataclass
class MaskSpec:
    source: str
    fragments: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def slots(self):
        return [f for f in self.fragments if isinstance(f, Slot)]

    @property
    def is_valid(self):
        return bool(self.slots) and not self.errors \
            and all(s.is_valid for s in self.slots)

    def slot(self, name):
        for s in self.slots:
            if s.name == name:
                return s
        return None


def _find_close(text, start):
    """Индекс закрывающих ``}}`` для слота, открытого перед ``start``;
    -1 — не закрыт. Экранированные скобки пропускаются."""
    depth = 2
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '\\':
            i += 2
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i - 1
        i += 1
    return -1


def _split_options(payload):
    return [p.strip() for p in payload.split('|')]


def _parse_choice(slot, payload):
    options = [o for o in _split_options(payload) if o]
    if slot.preset:
        # Пресет: первый (или помеченный *) вариант — правильный, остальные
        # дописываются к стандартному списку
        if not options:
            slot.error = 'не указан правильный вариант'
            return
        starred = [o.lstrip('*').strip() for o in options if o.startswith('*')]
        if len(starred) > 1:
            slot.error = 'правильный вариант должен быть один'
            return
        plain = [o.lstrip('*').strip() for o in options]
        canonical = {o.casefold().replace('ё', 'е'): o for o in PRESETS[slot.preset]}
        def preset_value(value):
            return canonical.get(value.casefold().replace('ё', 'е'), value)
        slot.correct = preset_value(starred[0] if starred else plain[0])
        slot.options = list(dict.fromkeys([*PRESETS[slot.preset], *(preset_value(o) for o in plain)]))
    else:
        if len(options) < 2:
            slot.error = 'нужно минимум два варианта через |'
            return
        starred = [o for o in options if o.startswith('*')]
        if len(starred) != 1:
            slot.error = 'ровно один вариант помечается звёздочкой как правильный'
            return
        slot.options = [o.lstrip('*').strip() for o in options]
        slot.correct = starred[0].lstrip('*').strip()
        if len(set(slot.options)) != len(slot.options):
            slot.error = 'варианты повторяются'
            return
    slot.reference = slot.correct


def _parse_number(slot, payload):
    tolerance = None
    m = _TOLERANCE_RE.match(payload)
    if m:
        payload, tol_text = m.group(1), m.group(2)
        tolerance = sets.numeric_value(tol_text)
        if tolerance is None or tolerance < 0:
            slot.error = 'допуск после ~ должен быть числом'
            return
    value = sets.numeric_value(payload)
    if value is None:
        slot.error = 'эталон не разобран как число'
        return
    slot.data, slot.tolerance, slot.reference = value, tolerance, payload.strip()


def _parse_format(slot, payload):
    if slot.kind == DIGITS:
        value = payload if formats.digits(payload) else None
        hint = 'эталон должен содержать только цифры 0–9 без пробелов'
    elif slot.kind == DECIMAL:
        value = formats.decimal(payload)
        hint = 'эталон: целое или десятичное число с запятой'
    else:
        from . import numeric
        try:
            value = (formats.proportion(payload) if slot.kind == PROPORTION
                     else formats.ratio(payload))
        except numeric.Uncertain:
            value = None
        hint = 'эталон: два числа через двоеточие, второе не равно нулю'
    if value is None:
        slot.error = hint
        return
    slot.data, slot.reference = value, payload


def _parse_expression(slot, payload):
    from sympy import Eq, Expr
    expr = expressions.parse_expr(payload)
    if slot.kind == EQUATION:
        if not isinstance(expr, Eq):
            slot.error = 'эталон должен быть уравнением с «=»'
            return
    elif not isinstance(expr, Expr) or isinstance(expr, Eq):
        slot.error = 'эталон не разобран как выражение'
        return
    slot.data, slot.reference = expr, payload.strip()


def _parse_pair(slot, payload):
    if len(payload) > sets.MAX_COLLECTION_LEN:
        slot.error = 'слишком длинный эталон пар'
        return
    option = re.search(r'\|\s*unordered\s*$', payload)
    if option:
        payload = payload[:option.start()].strip()
        slot.unordered_pair = True
    pairs = sets.parse_pairs(payload)
    if not pairs:
        slot.error = 'эталон: пары вида (a; b), несколько пар через ;'
        return
    slot.data, slot.reference = pairs, payload.strip()


def _parse_formula(slot, payload, *, validate=False):
    try:
        slot.data, slot.reference = formulas.parse_reference(
            payload, multiple=slot.kind == EXPRESSIONS, validate=validate,
            mode=slot.kind if slot.kind in (SIMPLIFY, FACTOR) else 'expression')
    except ValueError as error:
        slot.error = str(error)


def _parse_set(slot, payload):
    values = sets.parse_set(payload) if payload.strip() else []
    if values is None:
        slot.error = 'эталон: числа через ; (пусто — «нет решений»)'
        return
    slot.data = values
    slot.reference = payload.strip() or '∅'


def _parse_range(slot, payload):
    value = sets.parse_range(payload)
    if value is None:
        slot.error = 'эталон не разобран как число, множество чисел, промежуток или неравенство'
        return
    slot.data, slot.reference = value, payload.strip()

def _parse_series(slot, payload):
    value = series.parse(payload)
    if value is None or series.canonical(value) is None:
        slot.error = 'эталон: объединение серий вида π+2π*n'
        return
    slot.data, slot.reference = value, payload.strip()


def _parse_order(slot, payload):
    items = [o for o in _split_options(payload) if o]
    if len(items) < 2:
        slot.error = 'нужно минимум два элемента через |'
        return
    slot.items, slot.reference = items, ', '.join(items)


_PARSERS = {
    DIGITS: _parse_format, DECIMAL: _parse_format,
    RATIO: _parse_format, PROPORTION: _parse_format,
    NUMBER: _parse_number, CHOICE: _parse_choice, SIMPLIFY: _parse_formula,
    FACTOR: _parse_formula, EQUATION: _parse_expression, PAIR: _parse_pair,
    SET: _parse_set, RANGE: _parse_range, SERIES: _parse_series, ORDER: _parse_order,
    EXPRESSION: _parse_formula, EXPRESSIONS: _parse_formula,
}


def parse_mask(text, *, validate_references=False):
    """Текст маски → ``MaskSpec`` (фрагменты текста и слоты, ошибки).

    При показе сохранённых expression-полей не запускаем вычислитель.
    Формы сохранения и импорта передают validate_references=True, чтобы
    проверить математический эталон до записи.
    """
    text = text or ''
    spec = MaskSpec(source=text)
    pos = 0
    index = 0
    while True:
        m = _OPEN_RE.search(text, pos)
        if not m:
            break
        name = m.group(1)
        if name not in KINDS and name not in PRESETS:
            spec.errors.append(f'неизвестный тип слота «{name}»')
            pos = m.end()
            continue
        end = _find_close(text, m.end())
        if end < 0:
            spec.errors.append(f'слот {{{{{name}: …}}}} не закрыт двойной скобкой')
            break
        if m.start() > pos:
            spec.fragments.append(text[pos:m.start()])
        payload = text[m.end():end].strip()
        index += 1
        kind = CHOICE if name in PRESETS else name
        slot = Slot(index=index, kind=kind, raw=payload,
                    preset=name if name in PRESETS else None)
        if kind in (EXPRESSION, EXPRESSIONS, SIMPLIFY, FACTOR):
            _parse_formula(slot, payload, validate=validate_references)
        else:
            _PARSERS[kind](slot, payload)
        if slot.error:
            spec.errors.append(f'слот {index} ({{{{{name}: …}}}}): {slot.error}')
        spec.fragments.append(slot)
        pos = end + 2
    if pos < len(text):
        spec.fragments.append(text[pos:])
    if not spec.slots and not spec.errors and text.strip():
        spec.errors.append('в маске нет ни одного слота {{тип: …}}')
    return spec


# --- проверка -----------------------------------------------------------------

def _parse_order_positions(value, count):
    """Позиции слота order: список длины ``count`` (``None`` — пусто).
    Неполная перестановка допустима для показа формы; для сверки — нет."""
    parts = (value or '').split('|')
    if len(parts) != count:
        return None
    try:
        chosen = [int(p) if p.strip() != '' else None for p in parts]
    except ValueError:
        return None
    used = [i for i in chosen if i is not None]
    if any(i < 0 or i >= count for i in used) or len(used) != len(set(used)):
        return None
    return chosen


def _parse_order_value(value, count):
    chosen = _parse_order_positions(value, count)
    if chosen is None or any(i is None for i in chosen):
        return None
    if sorted(chosen) != list(range(count)):
        return None
    return chosen


def check_slot(slot, value):
    """Значение ученика для одного слота → '' / ok / wrong / unknown."""
    value = (value or '').strip()
    if not value or not slot.is_valid:
        return ''
    kind = slot.kind
    if kind == DIGITS:
        return OK if formats.digits(value) and value == slot.data else WRONG
    if kind == DECIMAL:
        student = formats.decimal(value)
        return OK if student is not None and student == slot.data else WRONG
    if kind == PROPORTION:
        from . import numeric
        from fractions import Fraction
        from decimal import DecimalException
        try:
            student = formats.proportion(value)
        except numeric.Uncertain:
            return formats.check_proportion_exact(value, slot.reference)
        if student is None:
            return WRONG
        if student == 0 or slot.data == 0:
            return OK if student == slot.data else WRONG
        try:
            equal = numeric.equal(student, slot.data) or numeric.equal(
                numeric.calculate('div', Fraction(1), student), slot.data)
        except (ValueError, DecimalException, OverflowError, ZeroDivisionError):
            return WRONG
        return OK if equal else WRONG
    if kind == RATIO:
        student = formats.ratio(value)
        equal = student is not None and student == slot.data
        return OK if equal else WRONG
    if kind == CHOICE:
        if _compact(value).replace('ё', 'е') == _compact(slot.correct).replace('ё', 'е'):
            return OK
        return WRONG if value in slot.options else UNKNOWN
    if kind == NUMBER:
        student = sets.numeric_value(value)
        if student is None:
            return UNKNOWN
        return OK if sets.numbers_equal(student, slot.data, slot.tolerance) else WRONG
    if kind == PAIR:
        student = sets.parse_pairs(value)
        if student is None:
            return UNKNOWN
        return OK if sets.pairs_equal(
            student, slot.data, unordered=slot.unordered_pair) else WRONG
    if kind == SET:
        student = sets.parse_set(value)
        if student is None:
            return UNKNOWN
        return OK if sets.sets_equal(student, slot.data) else WRONG
    if kind == RANGE:
        student = sets.parse_range(value)
        if student is None:
            return UNKNOWN
        return OK if sets.ranges_equal(student, slot.data) else WRONG
    if kind == SERIES:
        student = series.parse(value)
        equal = series.equal(student, slot.data)
        return UNKNOWN if equal is None else (OK if equal else WRONG)
    if kind in (EXPRESSION, EXPRESSIONS, SIMPLIFY, FACTOR):
        return formulas.check(value, slot.data, multiple=kind == EXPRESSIONS)
    if kind == EQUATION:
        return expressions.check_equation(value, slot.data)
    if kind == ORDER:
        order = _parse_order_value(value, len(slot.items))
        if order is None:
            return UNKNOWN
        return OK if order == list(range(len(slot.items))) else WRONG
    return UNKNOWN


def check_mask(spec, values, known=None):
    """Все слоты → (итог по задаче, {имя слота: результат}).
    Итог: ``ok`` — все слоты верны; ``wrong`` — хоть один неверен;
    ``unknown`` — что-то не разобрано или не заполнено; '' — пусто.
    ``known`` — готовые результаты слотов, чьё значение не менялось: их не
    пересчитываем (формульные слоты стоят дочернего процесса)."""
    results = {}
    for slot in spec.slots:
        if known and slot.name in known:
            results[slot.name] = known[slot.name]
            continue
        results[slot.name] = check_slot(slot, values.get(slot.name, ''))
    verdicts = list(results.values())
    if not any(verdicts):
        return '', results
    if WRONG in verdicts:
        return WRONG, results
    if UNKNOWN in verdicts or '' in verdicts:
        return UNKNOWN, results
    return OK, results


def has_values(values):
    return any((v or '').strip() for v in (values or {}).values())


# --- представление -----------------------------------------------------------

def slot_display(slot, value):
    """Значение слота в человекочитаемом виде (для учителя и итогов)."""
    value = (value or '').strip()
    if not value:
        return ''
    if slot.kind == ORDER:
        order = _parse_order_value(value, len(slot.items))
        if order is None:
            return value
        return ', '.join(slot.items[i] for i in order)
    if slot.kind == SET and normalize(value).lower() in sets.EMPTY_WORDS:
        return 'нет решений'
    if slot.uses_math_field and not value.startswith('$'):
        # Из math-field приходит голый LaTeX — ученик и учитель должны
        # видеть формулу, а не код
        return f'${value}$'
    return value


def filled_text(spec, values, placeholder='___'):
    """Текст маски с подставленными значениями ученика: так учитель видит
    «Меньшая сторона равна [10] см»."""
    parts = []
    for frag in spec.fragments:
        if isinstance(frag, Slot):
            shown = slot_display(frag, values.get(frag.name, ''))
            parts.append(f'[{shown}]' if shown else placeholder)
        else:
            parts.append(frag)
    return ''.join(parts)


def reference_text(spec):
    """Текст маски с эталонами вместо слотов (для учителя)."""
    parts = []
    for frag in spec.fragments:
        if isinstance(frag, Slot):
            ref = frag.reference
            if frag.uses_math_field and ref and not ref.startswith('$'):
                ref = f'${ref}$'
            parts.append(f'[{ref}]')
        else:
            parts.append(frag)
    return ''.join(parts)


def render_fragments(spec, prefix, values=None, checks=None, seed=''):
    """Данные для шаблона ``assignments/_mask.html``: текст и слоты с именами
    полей формы ``{prefix}_s1``…, текущими значениями и результатами."""
    values = values or {}
    checks = checks or {}
    out = []
    for frag in spec.fragments:
        if not isinstance(frag, Slot):
            out.append({'text': frag})
            continue
        value = values.get(frag.name, '')
        item = {
            'slot': frag,
            'kind': frag.kind,
            'name': f'{prefix}_{frag.name}',
            'value': value,
            'display': slot_display(frag, value),
            'check': checks.get(frag.name, ''),
        }
        if frag.kind == ORDER:
            chosen = _parse_order_positions(value, len(frag.items))
            if chosen is None:
                chosen = [None] * len(frag.items)
            seed_key = seed or prefix
            tokens = frag.order_tokens(seed_key)
            item['order_items'] = [
                (tokens[i], text) for i, text in frag.shuffled(seed_key)]
            item['order_positions'] = [
                {'k': k,
                 'selected': tokens[chosen[k]] if chosen[k] is not None else None}
                for k in range(len(frag.items))]
        out.append(item)
    return out


def collect_values(data, prefix, spec):
    """Значения слотов из POST: ``{prefix}_s1``…; у ``order`` — по одному
    полю на позицию ``{prefix}_s1_0``…, у ``set`` — флажок «решений нет»."""
    values = {}
    for slot in spec.slots:
        key = f'{prefix}_{slot.name}'
        if slot.kind == ORDER:
            pos_keys = [f'{key}_{k}' for k in range(len(slot.items))]
            if any(k in data for k in pos_keys):
                rev = {tok: i for i, tok in slot.order_tokens(prefix).items()}
                parts = []
                for pos_key in pos_keys:
                    raw = (data.get(pos_key) or '').strip()
                    parts.append(str(rev[raw]) if raw in rev else '')
                values[slot.name] = '|'.join(parts) if any(parts) else ''
        elif slot.kind == SET and data.get(f'{key}_none'):
            values[slot.name] = '∅'
        elif key in data:
            values[slot.name] = (data.get(key) or '').strip()
    return values


def _unwrap_set_braces(text):
    """Снять только внешнюю оболочку множества ``{…}`` / ``\\{…\\}``,
    не трогая скобки LaTeX-команд вроде ``\\frac{1}{2}``."""
    text = text.strip()
    if text.startswith('\\{') and text.endswith('\\}'):
        return text[2:-2].strip()
    if text.startswith('{') and text.endswith('}'):
        return text[1:-1].strip()
    return text


def _numeric_math_set(answer, condition=''):
    """Несколько отдельных чисел в формулах превращает в поля.

    Между формулами допускаются только перечислительные связки. Поэтому
    предложение с пояснением не станет коротким проверяемым ответом.
    """
    source = re.sub(
        r'([A-Za-zА-Яа-я.]+)\$\^\{?([23])\}?\$',
        r'\1^\2', answer or '')
    matches = list(_ANSWER_MATH_RE.finditer(source))
    if len(matches) < 2:
        return ''
    values = []
    degrees = []
    for match in matches:
        degrees.append(bool(re.search(r'\^\{?\\circ\}?', match.group(1))))
        value = re.sub(r'\^\{?\\circ\}?', '', match.group(1)).strip()
        if '=' in value or sets.numeric_value(value) is None:
            return ''
        values.append(value)
    if len(set(values)) != len(values):
        return ''
    outside = _ANSWER_MATH_RE.sub(' ', source)
    has_or = bool(re.search(r'\bили\b', outside, re.I))
    outside = re.sub(r'\b(?:и|или)\b', ' ', outside, flags=re.I)
    outside = re.sub(r'(?:°|\\circ|\^\{?\\circ\}?)', ' ', outside)
    units = [re.sub(r'\s+', '', match.group())
             for match in _UNIT_TOKEN_RE.finditer(outside)]
    if len({unit.casefold() for unit in units}) > 1:
        return ''
    outside = _UNIT_TOKEN_RE.sub(' ', outside)
    if re.sub(r'[\s,;./]', '', outside):
        return ''
    if any(degrees) and not all(degrees):
        return ''
    degree = all(degrees)
    suffix = '°' if degree else (f' {units[0]}' if units else '')
    homogeneous = bool(re.search(
        r'\b(?:корн\w*|решени\w*|сторон\w*|угл\w*)\b',
        condition or '', re.I))
    if has_or or homogeneous:
        candidate = f'{{{{{SET}: {"; ".join(values)}}}}}{suffix}'
    else:
        candidate = ', '.join(
            f'{{{{{NUMBER}: {value}}}}}{suffix}' for value in values)
    if not parse_mask(candidate).is_valid:
        return ''
    return candidate


def _single_numeric_math(answer):
    """Число в единственной формуле с короткой единицей измерения."""
    source = re.sub(
        r'([A-Za-zА-Яа-я.]+)\$\^\{?([23])\}?\$',
        r'\1^\2', answer or '')
    matches = list(_ANSWER_MATH_RE.finditer(source))
    if len(matches) != 1:
        return ''
    raw = matches[0].group(1).strip()
    approximate = bool(re.match(r'^\\approx\b', raw))
    raw = re.sub(r'^\\approx\s*', '', raw)
    degree = bool(re.search(r'\^\{?\\circ\}?', raw))
    value = re.sub(r'\^\{?\\circ\}?', '', raw).strip()
    if '=' in value or sets.numeric_value(value) is None:
        return ''
    outside = (source[:matches[0].start()]
               + source[matches[0].end():]).strip().rstrip('.')
    prefix = ''
    if re.match(r'^(?:в|около)\b', outside, re.I):
        word, outside = outside.split(maxsplit=1)
        prefix = word.capitalize() + ' '
    if re.match(r'^(?:≈|\\approx)\s*', outside):
        approximate = True
        outside = re.sub(r'^(?:≈|\\approx)\s*', '', outside)
    if degree:
        outside = re.sub(r'^(?:°|градус(?:а|ов)?)$', '', outside,
                         flags=re.I).strip()
    units = [match.group().strip() for match in _UNIT_TOKEN_RE.finditer(outside)]
    residue = _UNIT_TOKEN_RE.sub(' ', outside)
    if re.sub(r'[\s,;./]', '', residue):
        return ''
    suffix = '°' if degree else (f' {units[0]}' if len(units) == 1 else '')
    if len(units) > 1:
        return ''
    if approximate:
        prefix += '≈ '
    return f'{prefix}{{{{{NUMBER}: {value}}}}}{suffix}'


def _coordinate_pair_mask(answer, condition):
    """Координаты точек: подписи берём из ответа, числа не решаем."""
    if not re.search(r'координат', condition or '', re.I):
        return ''
    plain = (answer or '').replace('$', '')
    matches = list(_COORDINATE_PAIR_RE.finditer(plain))
    if not matches:
        return ''
    residue = _COORDINATE_PAIR_RE.sub(' ', plain)
    residue = re.sub(r'\b(?:и|или)\b', ' ', residue, flags=re.I)
    if re.sub(r'[\s,;.]', '', residue):
        return ''
    pairs = []
    for match in matches:
        pair = f'({match.group("x").strip()}; {match.group("y").strip()})'
        candidate = f'{{{{{PAIR}: {pair}}}}}'
        if not parse_mask(candidate).is_valid:
            return ''
        pairs.append(pair)
    labels = [
        None if str(match.group('label') or '').casefold() in {'и', 'или'}
        else re.sub(
            r'([A-Za-zА-Яа-я])_\{?([0-9]+)\}?', r'\1_\2',
            str(match.group('label') or '').strip())
        for match in matches
    ]
    if len(set(labels)) == 1:
        candidate = f'{{{{{PAIR}: {"; ".join(pairs)}}}}}'
        if not parse_mask(candidate).is_valid:
            return ''
        return (f'${labels[0]} =$ ' if labels[0] else '') + candidate
    if any(not label for label in labels) or len(set(labels)) != len(labels):
        return ''
    return ', '.join(
        f'${label} =$ {{{{{PAIR}: {pair}}}}}'
        for label, pair in zip(labels, pairs))


def _draft_mask(answer, condition="", exam_codes=None, *, source_number="", subitem_label=""):
    """Черновик маски из текстового «Ответа» для тривиальных случаев;
    '' — не угадали, учитель пишет маску сам."""
    from .ege_policy import ege_draft
    ege = ege_draft(answer, condition, exam_codes, source_number=source_number,
                    subitem_label=subitem_label)
    if ege is not None:
        return ege
    kind = formats.oge_kind(exam_codes)
    if kind == '':
        return ''
    if kind:
        text = (answer or '').replace('$', '').strip()
        text = text.replace('{,}', ',')
        candidate = f'{{{{{kind}: {text}}}}}'
        return candidate if parse_mask(candidate).is_valid else ''
    answer = (answer or '').replace('\\displaystyle', '')
    answer = answer.replace('\\operatorname{tg}', '\\tan')
    answer = answer.replace('\\operatorname{ctg}', '\\cot')
    numeric_set = _numeric_math_set(answer, condition)
    if numeric_set:
        return numeric_set
    coordinates = _coordinate_pair_mask(answer, condition)
    if coordinates:
        return coordinates
    ratio_text = answer.replace('$', '').strip()
    if ':' in ratio_text and formats.ratio(ratio_text) is not None:
        return f'{{{{{RATIO}: {ratio_text}}}}}'
    from .drafting import contextual_draft
    contextual = contextual_draft(answer, condition)
    if contextual:
        return contextual if parse_mask(contextual).is_valid else ''
    if contextual == '' and re.search(
            r'реши\w*\s+(?:следующ\w*\s+)?(?:уравнен|систем)|'
            r'найди\w*\s+(?:все\s+)?корни', condition or '', re.I):
        return ''
    single_numeric = _single_numeric_math(answer)
    if single_numeric:
        return single_numeric
    text = answer.replace('$', ' ').strip()
    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text)
    low = normalize(text).lower().rstrip('.')
    if re.fullmatch(r'да(?:\s*\(см\.[^)]*\))?', low):
        return '{{yesno: да}}'
    if re.fullmatch(r'нет(?:\s*\(см\.[^)]*\))?', low):
        return '{{yesno: нет}}'
    if re.search(r'существу(?:ет|ют)\s+ли', condition or '', re.I) \
            and low in {'существует', 'существуют'}:
        return '{{yesno: да}}'
    if re.search(r'могут\s+ли', condition or '', re.I) \
            and low == 'не могут':
        return '{{yesno: нет}}'
    for preset, options in PRESETS.items():
        if low in options or (preset == 'parity' and low in ('четная', 'нечетная')):
            return f'{{{{{preset}: {low}}}}}'
    if sets.numeric_value(text) is not None and '=' not in text:
        return f'{{{{{NUMBER}: {text}}}}}'
    if '(' in text and sets.parse_pairs(text, coordinate_comma=False):
        return f'{{{{{PAIR}: {text}}}}}'
    if re.search(r'[<>≤≥\[\]∪]|\\infty|\\le|\\ge|\\cup', text) \
            and sets.parse_range(text) is not None:
        return f'{{{{{RANGE}: {text}}}}}'
    if (';' in text or '\\pm' in text or low in sets.EMPTY_WORDS) \
            and sets.parse_set(text) is not None:
        payload = '' if low in sets.EMPTY_WORDS else _unwrap_set_braces(text)
        draft = f'{{{{{SET}: {payload}}}}}'
        return draft if parse_mask(draft).is_valid else ''
    expr = expressions.parse_expr(text)
    if expr is None:
        return ''
    from sympy import Eq, Expr
    if isinstance(expr, Eq):
        return f'{{{{{EQUATION}: {text}}}}}'
    if isinstance(expr, Expr):
        return f'{{{{{SIMPLIFY}: {text}}}}}'
    return ''


def _mask_accepts_own_references(source):
    """Не предлагаем маску, которая отвергает свой же эталон."""
    if not source:
        return False
    spec = parse_mask(source)
    if not spec.is_valid or not spec.slots:
        return False
    try:
        # Черновик необязателен: занятый вычислитель не задерживает импорт
        # и не превращает подсказку редактора в ошибку HTTP 500.
        with formulas.without_worker_wait():
            for slot in spec.slots:
                if slot.kind == CHOICE:
                    value = slot.correct
                elif slot.kind == ORDER:
                    value = '|'.join(str(index) for index in range(len(slot.items)))
                else:
                    value = slot.reference
                if check_slot(slot, value) != OK:
                    return False
    except formulas.FormulaUnavailable:
        return False
    return True


def draft_mask(answer, condition="", exam_codes=None, *, source_number="", subitem_label=""):
    """Безопасный черновик маски; ``''`` означает ручную сверку."""
    candidate = _draft_mask(
        answer, condition, exam_codes,
        source_number=source_number, subitem_label=subitem_label)
    return candidate if _mask_accepts_own_references(candidate) else ''

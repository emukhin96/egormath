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
from . import expressions, sets

NUMBER = 'number'
CHOICE = 'choice'
SIMPLIFY = 'simplify'
FACTOR = 'factor'
PAIR = 'pair'
SET = 'set'
EQUATION = 'equation'
RANGE = 'range'
ORDER = 'order'

KINDS = {
    NUMBER: 'число',
    CHOICE: 'выбор из вариантов',
    SIMPLIFY: 'выражение для упрощения',
    FACTOR: 'разложение на множители',
    PAIR: 'упорядоченная пара (пары)',
    SET: 'конечное множество чисел',
    EQUATION: 'уравнение',
    RANGE: 'числовой промежуток',
    ORDER: 'расставить в порядке',
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
    ('{{factor: 2(x-1)(x+1)}}', 'разложение на неприводимые множители, порядок любой'),
    ('{{pair: (2,5; -3); (5; -6)}}', 'упорядоченные пары через ; порядок пар не важен'),
    ('{{set: -2; 1}}', 'множество чисел, порядок не важен; {{set: }} — «нет решений»'),
    ('{{equation: y=x+5}}', 'уравнение в приведённом виде (y-x=5 тоже верно, 2y=2x+10 — нет)'),
    ('{{range: (-\\infty;-5)\\cup(5;+\\infty)}}', 'числовое множество; ученик может писать '
                                               'неравенствами: x<-5, x>5'),
    ('{{order: \\sqrt[6]{5}|\\sqrt[5]{4}|2}}', 'элементы в правильном порядке; '
                                              'ученику показываются перемешанными'),
)

_OPEN_RE = re.compile(r'\{\{\s*([a-z]+)\s*:')
_TOLERANCE_RE = re.compile(r'^(.*?)\s*~\s*([^~]+)$')


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
        return self.kind in (SIMPLIFY, FACTOR, EQUATION)

    @property
    def label(self):
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
        slot.correct = starred[0] if starred else plain[0]
        slot.options = list(PRESETS[slot.preset]) + [
            o for o in plain if o not in PRESETS[slot.preset]]
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
    pairs = sets.parse_pairs(payload)
    if not pairs:
        slot.error = 'эталон: пары вида (a; b), несколько пар через ;'
        return
    slot.data, slot.reference = pairs, payload.strip()


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
        slot.error = 'эталон не разобран как промежуток или неравенство'
        return
    slot.data, slot.reference = value, payload.strip()


def _parse_order(slot, payload):
    items = [o for o in _split_options(payload) if o]
    if len(items) < 2:
        slot.error = 'нужно минимум два элемента через |'
        return
    slot.items, slot.reference = items, ', '.join(items)


_PARSERS = {
    NUMBER: _parse_number, CHOICE: _parse_choice, SIMPLIFY: _parse_expression,
    FACTOR: _parse_expression, EQUATION: _parse_expression, PAIR: _parse_pair,
    SET: _parse_set, RANGE: _parse_range, ORDER: _parse_order,
}


def parse_mask(text):
    """Текст маски → ``MaskSpec`` (фрагменты текста и слоты, ошибки)."""
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

def _parse_order_value(value, count):
    try:
        order = [int(p) for p in value.split('|') if p.strip() != '']
    except ValueError:
        return None
    if sorted(order) != list(range(count)):
        return None
    return order


def check_slot(slot, value):
    """Значение ученика для одного слота → '' / ok / wrong / unknown."""
    value = (value or '').strip()
    if not value or not slot.is_valid:
        return ''
    kind = slot.kind
    if kind == CHOICE:
        if _compact(value) == _compact(slot.correct):
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
        return OK if sets.pairs_equal(student, slot.data) else WRONG
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
    if kind == SIMPLIFY:
        return expressions.check_simplified(value, slot.data)
    if kind == FACTOR:
        return expressions.check_factored(value, slot.data)
    if kind == EQUATION:
        return expressions.check_equation(value, slot.data)
    if kind == ORDER:
        order = _parse_order_value(value, len(slot.items))
        if order is None:
            return UNKNOWN
        return OK if order == list(range(len(slot.items))) else WRONG
    return UNKNOWN


def check_mask(spec, values):
    """Все слоты → (итог по задаче, {имя слота: результат}).
    Итог: ``ok`` — все слоты верны; ``wrong`` — хоть один неверен;
    ``unknown`` — что-то не разобрано или не заполнено; '' — пусто."""
    results = {}
    for slot in spec.slots:
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
            parts.append(f'[{frag.reference}]')
        else:
            parts.append(frag)
    return ''.join(parts)

"""Автосверка ответа ученика с эталоном задачи.

Сравнение идёт от дешёвого к дорогому, и каждый шаг может закончить дело:
нормализация школьной записи → число с допуском → промежуток → множество
→ выражение через sympy (``parse_latex`` с lark-бэкендом, эквивалентность
``a.equals(b)`` — численная, без непредсказуемо долгого ``simplify``).
Что не разобралось — ``unknown``, а не «неверно»: последнее слово всегда за
учителем, автосверка не ставит отметку и не закрывает работу.
"""
import re
from fractions import Fraction

OK = 'ok'
WRONG = 'wrong'
UNKNOWN = 'unknown'
# Строгий формат бланка (digits/decimal/ratio) нарушен: для итога по задаче это
# «неверно», но ученику показывается подсказка о записи, а не о значении.
FORMAT = 'format'

# Слишком длинный ввод в sympy не отдаём: equals может работать долго
MAX_EXPR_LEN = 300

_INF_WORDS = ('\\infty', '∞', 'inf', 'бесконечность', 'беск')

_REPLACEMENTS = (
    ('{,}', ','),
    ('\\displaystyle', ' '),
    ('\\left', ''), ('\\right', ''),
    ('\\dfrac', '\\frac'), ('\\tfrac', '\\frac'),
    ('\\cdot', '*'), ('\\times', '*'), ('·', '*'), ('×', '*'),
    ('\\,', ' '), ('\\;', ' '), ('\\:', ' '), ('\\!', ''), ('\\ ', ' '),
    ('~', ' '), ('\u00a0', ' '),
    ('−', '-'), ('–', '-'), ('—', '-'),
    ('∞', '\\infty'),
    ('≤', '<='), ('≥', '>='), ('≠', '!='),
    ('\\{', '{'), ('\\}', '}'),
    ('\\cup', '∪'), ('\\varnothing', '∅'), ('\\emptyset', '∅'),
)

_DECIMAL_COMMA_RE = re.compile(r'(?<=\d),(?=\d)')
# ``\le5`` без пробела тоже встречается; ``\left`` не трогаем
_RELATION_RE = re.compile(r'\\(leqslant|geqslant|leq|geq|neq|le|ge|ne)(?![a-zA-Z])')
_RELATIONS = {'leqslant': '<=', 'geqslant': '>=', 'leq': '<=', 'le': '<=', 'geq': '>=', 'ge': '>=',
              'neq': '!=', 'ne': '!='}
_VAR_EQ_RE = re.compile(r'^[a-zA-Zа-яА-Я](?:_\{?\d+\}?)?\s*=\s*(.+)$')
_NUMBER_RE = re.compile(r'^[+-]?\d+(?:\.\d+)?$')
_SIMPLE_FRAC_RE = re.compile(r'^([+-])?\s*(\d+)\s*/\s*([+-]?\d+)$')
_TEX_FRAC_RE = re.compile(
    r'^([+-])?\s*\\frac\s*(?:\{([+-]?\d+)\}|([+-]?\d))\s*(?:\{([+-]?\d+)\}|([+-]?\d))$')
_MIXED_FRAC_RE = re.compile(r'^([+-])?(\d+)\s*\\frac\{(\d+)\}\{(\d+)\}$')
_INTERVAL_RE = re.compile(r'^([(\[])\s*([^;]+?)\s*;\s*([^;]+?)\s*([)\]])$')
_PM_RE = re.compile(r'^\\pm\s*(.+)$')

# Школьные имена тригонометрических функций → команды, которые понимает
# Lark-грамматика SymPy. Ученик набирает их буквами (arccos(1/6)), MathLive
# присылает \mathrm{arctg} или \operatorname{ctg}, в книгах встречается \tg.
_FUNCTION_COMMANDS = {
    'sin': 'sin', 'cos': 'cos', 'tg': 'tan', 'tan': 'tan', 'ctg': 'cot', 'cot': 'cot',
    'arcsin': 'arcsin', 'arccos': 'arccos', 'arctg': 'arctan', 'arctan': 'arctan',
    'arcctg': 'arccot', 'arccot': 'arccot',
}
_FUNCTION_NAMES = '|'.join(sorted(_FUNCTION_COMMANDS, key=len, reverse=True))
# Имена SymPy (asin) понимаем только в оболочке: буквами «acos» — это и a·cos.
_SYMPY_COMMANDS = {'asin': 'arcsin', 'acos': 'arccos', 'atan': 'arctan'}
_WRAPPED_NAMES = '|'.join(sorted({**_FUNCTION_COMMANDS, **_SYMPY_COMMANDS},
                                 key=len, reverse=True))
_WRAPPED_FUNCTION_RE = re.compile(
    r'\\(?:operatorname|mathrm|text|textrm)\s*\{\s*'
    rf'(?:\\(?:mathrm|text|textrm)\s*\{{\s*({_WRAPPED_NAMES})\s*\}}|({_WRAPPED_NAMES}))\s*\}}')
# Команда целиком (\tg, но не \tgx) и имя буквами вне более длинного слова
# (arccos, но не xarccos и не arccosx: такие записи не угадываем).
# Буквенное имя считается функцией, только если за ним (и за степенью)
# идёт аргумент: «tg + 1» с параметрами t и g остаётся произведением.
_FUNCTION_COMMAND_RE = re.compile(rf'\\({_FUNCTION_NAMES})(?![A-Za-z])')
_BARE_FUNCTION_RE = re.compile(
    rf'(?<![A-Za-z\\])({_FUNCTION_NAMES})(?![A-Za-z])'
    r'(?=\s*(?:\^\s*(?:\{[^{}]*\}|[+-]?\d+)\s*)?[0-9A-Za-zα-ωπ(\[{\\.])')
# Остаток имени функции после нормализации — слово, где имя склеено с
# другими буквами или набрано иначе: Arccos, sinx, acos. Голое имя (tg, cot,
# arc) осталось без аргумента и сознательно читается произведением t·g.
_LETTER_RUN_RE = re.compile(r'(?<![A-Za-z\\])[A-Za-z]+')
_FUNCTION_PART_RE = re.compile(r'arc|sin|cos|tg|tan|cot', re.I)
_PRODUCT_NAMES = frozenset(_FUNCTION_COMMANDS) | {'arc'}


def _function_commands(text):
    def command(match):
        name = match[match.lastindex]
        result = '\\' + (_FUNCTION_COMMANDS.get(name) or _SYMPY_COMMANDS[name])
        # Пробел нужен только перед буквой: \tan x, а не \tanx.
        following = match.string[match.end():match.end() + 1]
        return result + ' ' if following.isalpha() else result

    for rx in (_WRAPPED_FUNCTION_RE, _FUNCTION_COMMAND_RE, _BARE_FUNCTION_RE):
        text = rx.sub(command, text)
    return text


def unrecognized_function(text):
    """В вводе осталось имя функции, которое нормализация не распознала.

    Такой ввод разбирается как произведение букв (Arccos → A·r·c·c·o·s),
    и «неверно» по нему было бы ложным: решение остаётся за учителем.
    """
    return any(run not in _PRODUCT_NAMES and _FUNCTION_PART_RE.search(run)
               for run in _LETTER_RUN_RE.findall(normalize(text)))


# «arccos 1/6» без скобок по правилам LaTeX — arccos(1)/6, но так ученик
# набирает \frac{1}{6} в аргументе. Простая дробь после функции без скобок
# допускает и второе чтение: f(a/b). Атомы — число, корень, π, буква.
_FRACTION_ATOM = (r'(?:\d+(?:\.\d+)?|\\sqrt(?:\[[^\]]*\])?\s*(?:\{[^{}]*\}|\d)'
                  r'|sqrt\s*\([^()]*\)|\\pi(?![A-Za-z])|pi(?![A-Za-z])|π|[A-Za-z](?![A-Za-z]))')
_FRACTION_TERM = rf'(?:{_FRACTION_ATOM}\s*){{1,3}}'
_FUNCTION_FRACTION_RE = re.compile(
    r'(\\(?:arcsin|arccos|arctan|arccot|sin|cos|tan|cot)(?![A-Za-z])'
    r'(?:\s*\^\s*(?:\{[^{}]*\}|[+-]?\d))?)\s*'
    rf'(?![(\[{{]|\\left)({_FRACTION_TERM})\s*/\s*({_FRACTION_TERM})'
    r'(?=\s*(?:$|[-+;,)\]=<>]))')


def function_fraction_reading(text):
    """Второе чтение «f a/b» как f(a/b): (текст, только числа) или None."""
    text = normalize(text)
    found = False
    numeric = True

    def wrap(match):
        nonlocal found, numeric
        found = True
        letters = re.sub(r'\\[A-Za-z]+|sqrt|pi', '', match[2] + match[3])
        numeric &= not re.search('[A-Za-z]', letters)
        return f'{match[1]}({match[2].strip()}/{match[3].strip()})'

    text = _FUNCTION_FRACTION_RE.sub(wrap, text)
    return (text, numeric) if found else None


def normalize(text):
    """Общая нормализация школьной записи; ``$`` снимаются, запятая в
    десятичной дроби становится точкой, пробелы схлопываются, школьные
    имена функций (arctg, \\mathrm{ctg}, \\tg) становятся командами LaTeX."""
    text = (text or '').replace('$', ' ')
    text = _RELATION_RE.sub(lambda m: f' {_RELATIONS[m.group(1)]} ', text)
    for old, new in _REPLACEMENTS:
        text = text.replace(old, new)
    text = _DECIMAL_COMMA_RE.sub('.', text)
    text = _function_commands(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _compact(text):
    return re.sub(r'\s+', '', text).lower()


def parse_number(text):
    """Число в школьной записи → Fraction; иначе None."""
    text = text.strip().replace(' ', '')
    if _NUMBER_RE.match(text):
        return Fraction(text)
    m = _SIMPLE_FRAC_RE.match(text)
    if m and int(m.group(3)) != 0:
        value = Fraction(int(m.group(2)), int(m.group(3)))
        return -value if m.group(1) == '-' else value
    m = _TEX_FRAC_RE.match(text)
    if m:
        num = int(m.group(2) if m.group(2) is not None else m.group(3))
        den = int(m.group(4) if m.group(4) is not None else m.group(5))
        if den != 0:
            value = Fraction(num, den)
            return -value if m.group(1) == '-' else value
    m = _MIXED_FRAC_RE.match(text)
    if m and int(m.group(4)) != 0:
        value = int(m.group(2)) + Fraction(int(m.group(3)), int(m.group(4)))
        return -value if m.group(1) == '-' else value
    return None


def _endpoint(text):
    """Конец промежутка: Fraction или ±float('inf'); None — не разобрано."""
    text = text.strip()
    low = text.lower()
    if any(word in low for word in _INF_WORDS):
        return float('-inf') if low.startswith('-') else float('inf')
    return parse_number(text)


def parse_interval(text, strict_brackets=True):
    """``(a;b]`` → (lo, hi, скобки); бесконечные концы всегда круглые."""
    m = _INTERVAL_RE.match(text.strip())
    if not m:
        return None
    lo, hi = _endpoint(m.group(2)), _endpoint(m.group(3))
    if lo is None or hi is None:
        return None
    left = m.group(1) if isinstance(lo, Fraction) else '('
    right = m.group(4) if isinstance(hi, Fraction) else ')'
    if not strict_brackets:
        left, right = '(', ')'
    return (lo, hi, left, right)


def parse_interval_union(text, strict_brackets=True):
    parts = [p for p in re.split(r'\s*∪\s*', text.strip()) if p]
    if not parts:
        return None
    parsed = [parse_interval(p, strict_brackets) for p in parts]
    if any(p is None for p in parsed):
        return None
    return frozenset(parsed)


def _set_items(text):
    """Элементы множества ``{a; b}``, ``a; b`` или ``a, b``; None — не список."""
    text = text.strip()
    if text.startswith('{') and text.endswith('}'):
        text = text[1:-1]
    if text in ('∅', ''):
        return []
    if ';' in text:
        items = text.split(';')
    elif ', ' in text:
        items = text.split(',')
    else:
        return None
    items = [i.strip() for i in items if i.strip()]
    return items or None


def _strip_var(item):
    """``x = 2`` → ``2``: у корней уравнения ученик часто пишет переменную."""
    m = _VAR_EQ_RE.match(item.strip())
    return m.group(1).strip() if m else item.strip()


def _expand_pm(items):
    out = []
    for item in items:
        m = _PM_RE.match(item)
        if m:
            out.extend([m.group(1), f'-{m.group(1)}'])
        else:
            out.append(item)
    return out


def _sympy_expr(text):
    """Только lark-парсер LaTeX (см. ``checks.expressions``): это чистая
    грамматика. ``sympy.parse_expr`` / ``sympify`` здесь недопустимы — они
    исполняют ввод через eval."""
    from .checks.expressions import parse_expr
    return parse_expr(text)


def _sympy_equal(a, b):
    """True/False, либо None, если sympy не смог решить."""
    try:
        from sympy import Eq, Expr
        if isinstance(a, Eq) and isinstance(b, Eq):
            da, db = a.lhs - a.rhs, b.lhs - b.rhs
            result = da.equals(db)
            if result is False:
                result = da.equals(-db)
            return result
        if isinstance(a, Eq) != isinstance(b, Eq):
            return None
        if isinstance(a, Expr) and isinstance(b, Expr):
            if a.free_symbols != b.free_symbols:
                return False
            # Без точного доказательства обратных функций (formulas.
            # _inverse_trig_zero): здесь нет ограниченного вычислителя,
            # проверка идёт прямо в веб-процессе — None уходит учителю.
            return a.equals(b)
        return bool(a == b) or None
    except Exception:  # noqa: BLE001
        return None


def _compare_items(student, reference):
    """Один элемент против одного: число, слово или выражение."""
    if _compact(student) == _compact(reference):
        return OK
    ns, nr = parse_number(student), parse_number(reference)
    if ns is not None and nr is not None:
        return OK if ns == nr else WRONG
    if (ns is None) != (nr is None) and (
            _compact(student).isalpha() or _compact(reference).isalpha()):
        return WRONG
    es, er = _sympy_expr(student), _sympy_expr(reference)
    if es is None or er is None:
        return UNKNOWN
    result = _sympy_equal(es, er)
    if result is None:
        return UNKNOWN
    return OK if result else WRONG


def check_answer(student, reference, strict_brackets=True):
    """Сверка строки ученика с эталоном: 'ok' / 'wrong' / 'unknown' /
    '' (сверять нечего: пустой эталон или пустой ответ)."""
    result = _check_answer(student, reference, strict_brackets)
    if result == WRONG:
        reading = function_fraction_reading(student)
        if reading and _check_answer(reading[0], reference, strict_brackets) == OK:
            return OK if reading[1] else UNKNOWN
        if unrecognized_function(student):
            return UNKNOWN
    return result


def _check_answer(student, reference, strict_brackets):
    s, r = normalize(student), normalize(reference)
    if not s or not r:
        return ''
    if _compact(s) == _compact(r):
        return OK

    ns, nr = parse_number(s), parse_number(r)
    if ns is not None and nr is not None:
        return OK if ns == nr else WRONG

    us = parse_interval_union(s, strict_brackets)
    ur = parse_interval_union(r, strict_brackets)
    if us is not None and ur is not None:
        return OK if us == ur else WRONG
    if (us is None) != (ur is None) and (ns is not None or nr is not None):
        return WRONG

    items_s, items_r = _set_items(s), _set_items(r)
    if items_s is not None or items_r is not None \
            or _PM_RE.match(s) or _PM_RE.match(r):
        items_s = _expand_pm([_strip_var(i) for i in (items_s or [s])])
        items_r = _expand_pm([_strip_var(i) for i in (items_r or [r])])
        if len(items_s) != len(items_r):
            return WRONG
        unmatched = list(items_r)
        for item in items_s:
            verdicts = [_compare_items(item, ref) for ref in unmatched]
            if OK in verdicts:
                unmatched.pop(verdicts.index(OK))
            elif UNKNOWN in verdicts:
                return UNKNOWN
            else:
                return WRONG
        return OK

    return _compare_items(_strip_var(s), _strip_var(r))


def check_interval_fields(low, high, reference):
    """Ответ типа «промежуток» из двух полей: скобок у ученика нет, поэтому
    сравниваются только концы."""
    if not (low or '').strip() and not (high or '').strip():
        return ''
    lo = (low or '').strip().lstrip('([').strip() or '-\\infty'
    hi = (high or '').strip().rstrip(')]').strip() or '\\infty'
    return check_answer(f'({lo}; {hi})', reference, strict_brackets=False)

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
    ('\\le ', '<= '), ('\\leq', '<='), ('\\ge ', '>= '), ('\\geq', '>='),
    ('\\ne ', '!= '), ('\\neq', '!='),
    ('≤', '<='), ('≥', '>='), ('≠', '!='),
    ('\\{', '{'), ('\\}', '}'),
    ('\\cup', '∪'), ('\\varnothing', '∅'), ('\\emptyset', '∅'),
)

_DECIMAL_COMMA_RE = re.compile(r'(?<=\d),(?=\d)')
_VAR_EQ_RE = re.compile(r'^[a-zA-Zа-яА-Я](?:_\{?\d+\}?)?\s*=\s*(.+)$')
_NUMBER_RE = re.compile(r'^[+-]?\d+(?:\.\d+)?$')
_SIMPLE_FRAC_RE = re.compile(r'^([+-])?\s*(\d+)\s*/\s*(\d+)$')
_TEX_FRAC_RE = re.compile(
    r'^([+-])?\s*\\frac\s*(?:\{([+-]?\d+)\}|([+-]?\d))\s*(?:\{(\d+)\}|(\d))$')
_MIXED_FRAC_RE = re.compile(r'^([+-])?(\d+)\s*\\frac\{(\d+)\}\{(\d+)\}$')
_INTERVAL_RE = re.compile(r'^([(\[])\s*([^;]+?)\s*;\s*([^;]+?)\s*([)\]])$')
_PM_RE = re.compile(r'^\\pm\s*(.+)$')


def normalize(text):
    """Общая нормализация школьной записи; ``$`` снимаются, запятая в
    десятичной дроби становится точкой, пробелы схлопываются."""
    text = (text or '').replace('$', ' ')
    for old, new in _REPLACEMENTS:
        text = text.replace(old, new)
    text = _DECIMAL_COMMA_RE.sub('.', text)
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
    """Только lark-парсер LaTeX: это чистая грамматика. ``parse_expr`` /
    ``sympify`` здесь недопустимы — они исполняют ввод через eval."""
    text = text.strip()
    if not text or len(text) > MAX_EXPR_LEN:
        return None
    try:
        from sympy.parsing.latex import parse_latex
        return parse_latex(text, backend='lark')
    except Exception:  # noqa: BLE001 — любой сбой парсера = «не разобрано»
        return None


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


def check_fields(answer_type, obj, reference):
    """Сверка ответа Submission/SubmissionPart по типу задачи."""
    from problems.models import Task
    if answer_type == Task.ANSWER_NUMBER:
        return check_answer(obj.answer_number, reference)
    if answer_type == Task.ANSWER_INTERVAL:
        return check_interval_fields(
            obj.interval_low, obj.interval_high, reference)
    return check_answer(obj.answer_text, reference)

"""Свободно эквивалентные формулы и наборы формул без требования упрощения.

Ввод разбирается той же безопасной Lark-грамматикой, что и остальные маски.
Положительные параметры указываются явно: ``... | positive: a,R``.
Исходные знаменатели сохраняются до упрощения: сокращение дроби не должно
скрывать запрещённое значение параметра.
"""
import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from fractions import Fraction
from pathlib import Path

from ..check_answer import MAX_EXPR_LEN, OK, UNKNOWN, WRONG, normalize
from . import expressions
from .formula_fork import FormulaStartupUnavailable


@dataclass
class Formula:
    expression: object
    denominators: tuple
    components: tuple
    tree: object


@dataclass
class Reference:
    items: tuple
    positive: tuple
    symbols: tuple
    input_symbols: tuple = ()
    substitutions: tuple = ()
    angle: tuple = ()
    bounds: tuple = ()


@dataclass(frozen=True)
class FormulaSpec:
    payload: str
    multiple: bool
    mode: str = 'expression'
    numeric: bool = False
    tolerance: str = None


WORKER_TIMEOUT = 3
WORKER_RETRY_DELAY = 10
# Одновременно не больше WORKER_PARALLEL дочерних процессов на процесс
# gunicorn; остальные ждут освобождения до WORKER_WAIT секунд.
WORKER_PARALLEL = 2
WORKER_WAIT = 5
_worker_slots = threading.BoundedSemaphore(WORKER_PARALLEL)
_worker_wait = ContextVar('formula_worker_wait', default=None)
# Пауза после сбоя — по конкретному входу, а не для всех проверок процесса:
# один медленный ввод не должен выключать автопроверку остальным.
_failed_inputs = {}
_failed_lock = threading.Lock()
_FAILED_LIMIT = 256


class FormulaUnavailable(ValueError):
    """Временная недоступность вычислений, а не ошибка эталона или ответа."""


class FormulaBusy(FormulaUnavailable):
    """Вычисление отложено без запуска: повтор не считается новым сбоем."""


@contextmanager
def without_worker_wait():
    """Необязательный черновик пропускается, если вычислитель уже занят.

    Настройка относится только к текущему вызову, а не к соседним запросам.
    """
    token = _worker_wait.set(0)
    try:
        yield
    finally:
        _worker_wait.reset(token)


# Сколько раз один и тот же ввод может «временно» не сверяться, прежде чем
# он уйдёт в ручную проверку как unknown: детерминированно тяжёлое выражение
# иначе перепроверялось бы при каждом показе бесконечно.
UNAVAILABLE_LIMIT = 2
# Ключ счётчика сбоев в словаре результатов по слотам (имена слотов — s1, s2…).
UNAVAILABLE_KEY = '_unavailable'


def unavailable_count(checks, error):
    """Новое значение счётчика сбоев после ``error`` для словаря ``checks``."""
    count = (checks or {}).get(UNAVAILABLE_KEY, 0)
    return count if isinstance(error, FormulaBusy) else count + 1


def _remember_failure(key):
    with _failed_lock:
        if len(_failed_inputs) >= _FAILED_LIMIT:
            _failed_inputs.clear()
        _failed_inputs[key] = time.monotonic() + WORKER_RETRY_DELAY


def _recently_failed(key):
    with _failed_lock:
        until = _failed_inputs.get(key)
        if until is None:
            return False
        if time.monotonic() >= until:
            del _failed_inputs[key]
            return False
        return True


def _spawn(key):
    """Один запуск вычислителя: на Linux — из forkserver, иначе subprocess.

    Единственная точка запуска процесса: тесты подменяют её, и сценарии
    сбоев проверяются одинаково на macOS и на Linux (в CI).
    """
    if sys.platform == 'linux':
        from .formula_fork import run_worker
        return run_worker(key, WORKER_TIMEOUT)
    return subprocess.run(
        [sys.executable, '-m', 'assignments.checks.formula_worker'],
        input=key, capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[2], timeout=WORKER_TIMEOUT,
        check=False)


def _run_worker(payload):
    """Вычисления в отдельном процессе: таймаут убивает и убирает ребёнка.

    Gunicorn использует потоки, поэтому signal.alarm в HTTP-обработчике
    непригоден. Обмен только JSON, ввод не исполняется как Python.
    """
    key = json.dumps(payload, sort_keys=True)
    if _recently_failed(key):
        raise FormulaBusy('проверка этого выражения недавно не удалась; повторите позже')
    if sys.platform == 'linux':
        from .formula_fork import warmup
        try:
            # Прогрев не занимает слот вычислений и не помечает ввод сбойным.
            warmup()
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            raise FormulaBusy('парсер формул пока не готов') from error
    wait = _worker_wait.get()
    if not _worker_slots.acquire(timeout=WORKER_WAIT if wait is None else wait):
        raise FormulaBusy('проверка временно занята')
    try:
        result = _spawn(key)
        if result.returncode:
            raise FormulaUnavailable('не удалось проверить формулу за отведённое время')
        response = json.loads(result.stdout)
        if not isinstance(response, dict) or response.get('unavailable'):
            raise FormulaUnavailable('временная недоступность проверки')
        return response
    except FormulaStartupUnavailable as error:
        # Forkserver мог исчезнуть уже после успешного доверенного прогрева.
        # Такой отказ окружения не расходует попытку ученического ответа.
        raise FormulaBusy('парсер формул пока не готов') from error
    except (subprocess.TimeoutExpired, OSError, ValueError) as error:
        # Сбой запоминается только для этого входа: повторные форки того же
        # выражения под нагрузкой не нужны, остальные проверки продолжаются.
        _remember_failure(key)
        raise FormulaUnavailable('проверка временно недоступна') from error
    finally:
        _worker_slots.release()


@lru_cache(maxsize=256)
def _reference_response(payload, multiple, mode='expression'):
    result = _run_worker({'payload': payload, 'multiple': multiple, 'mode': mode})
    if result.get('unavailable'):
        raise ValueError('временная недоступность проверки')
    return result


def parse_reference(payload, multiple=False, *, validate=False, mode='expression'):
    """Для показа поля достаточно структуры; вычисления — при сохранении.

    Рендер сохранённой маски никогда не запускает subprocess и не зависит
    от временной доступности символьного вычислителя.
    """
    if len(payload) > MAX_EXPR_LEN:
        raise ValueError('слишком длинный эталон')
    if mode not in ('expression', 'simplify', 'factor') or (multiple and mode != 'expression'):
        raise ValueError('неизвестный режим проверки формулы')
    texts, _, domain, angle, bounds = _reference_context(payload, multiple)
    if (domain or angle or bounds) and mode != 'expression':
        raise ValueError('области поддерживаются только для expression/expressions')
    spec = FormulaSpec(payload, multiple, mode)
    if not validate:
        return spec, ';'.join(texts).strip()
    try:
        result = _reference_response(payload, multiple, mode)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        # Новую маску нельзя сохранить с непроверенным эталоном. Уже
        # сохранённые поля продолжают отображаться через ветку выше.
        raise FormulaUnavailable('не удалось проверить эталон; повторите сохранение чуть позже') from None
    if result.get('error'):
        raise ValueError(result['error'])
    return spec, result['display']


@lru_cache(maxsize=1024)
def _checked(value, reference):
    payload = {'payload': reference.payload, 'multiple': reference.multiple,
               'mode': reference.mode, 'value': value}
    if reference.numeric:
        payload['numeric'] = True
    if reference.tolerance is not None:
        payload['tolerance'] = reference.tolerance
    result = _run_worker(payload)
    if result.get('unavailable'):
        raise FormulaUnavailable('временная недоступность проверки')
    status = result.get('status')
    if status not in (OK, WRONG):
        # Таймауты и неопределённые результаты не остаются в кэше.
        raise ValueError('проверка не завершена')
    return status


def check(value, reference, multiple=False):
    """OK/WRONG/UNKNOWN — математический вердикт.

    Временная недоступность вычислителя (занят, таймаут, сбой процесса)
    поднимается как FormulaUnavailable: это не вердикт, сохранять и
    засчитывать его нельзя — проверку нужно повторить позже.
    """
    limit = MAX_EXPR_LEN
    if reference.numeric and reference.mode in ('set', 'pair', 'pair-unordered', 'range'):
        from .sets import MAX_COLLECTION_LEN
        limit = MAX_COLLECTION_LEN
    if len(value) > limit:
        return UNKNOWN
    try:
        return _checked(value, reference)
    except FormulaUnavailable:
        raise
    except (subprocess.TimeoutExpired, OSError) as error:
        raise FormulaUnavailable('проверка временно недоступна') from error
    except ValueError:
        return UNKNOWN


def _prepare(text):
    text = expressions.normalize_roots(text)
    # Степень переменной и следующая функция — отдельные множители.
    # В sin² x степень относится к функции, умножение туда не вставляем.
    functions = r'(?:sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|arccot|arcsec|arccsc|sinh|cosh|tanh|asinh|acosh|atanh)'

    # Lark трактует d перед функцией, корнем или дробью как дифференциал.
    # В школьной формуле одиночная d здесь является множителем.
    text = re.sub(r'(?<![A-Za-z\\])d\s*(?=\\(?:' + functions + r'|sqrt|frac|dfrac|tfrac)\b)',
                  r'd\\cdot ', text)

    def after_power(match):
        if re.search(r'\\' + functions + r'$', text[:match.start()].rstrip()):
            return match.group(1)
        return match.group(1) + r'\cdot '

    # Показатель может содержать один уровень скобок: x^{\frac{2}{3}}y.
    exponent = r'\^\{(?:[^{}]|\{[^{}]*\})+\}'
    text = re.sub(
        r'(' + exponent + r'|\^[+-]?\d+)\s*(?=[A-Za-z]|\\(?:sqrt|frac|pi|' + functions + r')\b)',
        after_power, text)
    text = re.sub(r'(' + exponent + r')\s*(?=\()', after_power, text)
    def after_group(match):
        if match.group(1) == '}' and expressions._closes_script(text, match.start()):
            return match.group(1)
        return match.group(1) + r'\cdot '

    text = re.sub(r'([})])\s*(?=\\(?:sqrt|frac|pi|' + functions + r')\b)',
                  after_group, text)
    # α cos α — произведение; команда самой функции не является множителем.
    greek = r'(?:alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|kappa|lambda|mu|nu|xi|omicron|pi|varpi|rho|varrho|sigma|varsigma|tau|upsilon|phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega)'
    return re.sub(r'(\\' + greek + r')\s*(?=\\' + functions + r'\b)',
                  r'\1\\cdot ', text)



def _components(tree, *, numeric=False, pi_marker=None):
    """Сохраняет области подвыражений до сокращения корней и степеней."""
    if not expressions._is_tree(tree):
        # Символ-лист не должен исчезнуть в 0*z: проверяем исходные имена.
        if expressions._is_symbol_token(tree):
            value = expressions.parse_expr(str(tree))
            return [value] if value is not None and hasattr(value, 'free_symbols') else []
        return []
    tree = expressions.resolve(tree)
    value = expressions.evaluate(tree, numeric=numeric, pi_marker=pi_marker)
    result = [value] if value is not None and hasattr(value, 'free_symbols') else []
    for child in tree.children:
        result.extend(_components(child, numeric=numeric, pi_marker=pi_marker))
    return result


def _denominators(tree, *, numeric=False, pi_marker=None):
    """Знаменатели в сыром дереве, включая полностью сокращённые дроби."""
    if not expressions._is_tree(tree):
        return []
    tree = expressions.resolve(tree)
    result = []
    if tree.data in ('fraction', 'div', 'superscript'):
        operands = [c for c in tree.children if expressions._is_tree(c)
                    or expressions._is_symbol_token(c)
                    or getattr(c, 'type', '') == 'DIGIT']
        if len(operands) == 2:
            child = operands[1]
            if tree.data == 'superscript':
                exponent = (expressions.evaluate(child, numeric=numeric, pi_marker=pi_marker) if expressions._is_tree(child)
                            else expressions.parse_expr(str(child)))
                # В школьной записи нулевая и отрицательная степени
                # требуют ненулевого основания, даже если SymPy уже
                # превратил a^0 в единицу.
                child = operands[0] if getattr(exponent, 'is_nonpositive', None) is True else None
            value = (expressions.evaluate(child, numeric=numeric, pi_marker=pi_marker) if expressions._is_tree(child)
                     else expressions.parse_expr(str(child)) if child is not None else None)
            if value is not None:
                result.append(value)
    for child in tree.children:
        result.extend(_denominators(child, numeric=numeric, pi_marker=pi_marker))
    return result


_DEGREE_MARKER = r'(?:\^\s*(?:\{\s*\\circ\s*\}|\\circ\b)|°|\\degree\b)'


def _numeric_degree_arguments(text):
    """Градусы в числовом аргументе sin/cos/tan/cot/sec/csc: точно в радианы.

    Обрабатывает числа и круглые/квадратные группы внутри аргумента.
    Маркеры за пределами функции и незакрытые группы не исправляются.
    """
    # Явные школьные и SymPy-обозначения функций приводим к LaTeX-командам.
    # Меняем только известные команды целиком; имена переменных не трогаем.
    # MathLive оборачивает имена школьных функций ещё и в \mathrm.
    # Снимаем только эту оболочку у известных имён, сохраняя аргумент
    # и показатель степени функции (\cos^245 — квадрат косинуса 45).
    text = re.sub(
        r'\\operatorname\s*\{\s*\\mathrm\s*\{\s*'
        r'(sin|cos|tan|tg|cot|ctg|sec|csc|asin|acos|atan)\s*\}\s*\}',
        lambda m: r'\operatorname{' + m[1] + '}', text)
    text = re.sub(
        r'\\operatorname\s*\{\s*(sin|cos|tan|tg|cot|ctg|sec|csc|asin|acos|atan)\s*\}'
        r'|\\(tg|ctg)(?![A-Za-z])',
        lambda m: '\\' + {'tg': 'tan', 'ctg': 'cot',
                            'asin': 'arcsin', 'acos': 'arccos', 'atan': 'arctan'}.get(
            m[1] or m[2], m[1] or m[2]), text)
    intervals, replacements = [], {}
    functions = (r'\\(?:sin|cos|tan|cot|sec|csc)(?![A-Za-z])'
                 r'(?:\s*\^\s*(?:\{\s*\d+\s*\}|\d))?\s*')
    for m in re.finditer(functions, text):
        start = m.end()
        if start < len(text) and text[start] in '({[':
            stack = []
            for end in range(start, len(text)):
                c = text[end]
                if c in '({[':
                    stack.append(c)
                elif c in ')}]':
                    if not stack or stack.pop() != {')': '(', ']': '[', '}': '{'}[c]:
                        break
                    if not stack:
                        intervals.append((start + 1, end))
                        break
        else:
            bare = re.match(r'[+-]?\d+(?:\.\d+)?\s*' + _DEGREE_MARKER, text[start:])
            if bare:
                number = re.match(r'[+-]?\d+(?:\.\d+)?', bare[0])[0]
                replacements[(start, start + bare.end())] = '(' + number + r'\cdot\pi/180)'
    for m in re.finditer(_DEGREE_MARKER, text):
        if any(a <= m.start() and m.end() <= b for a, b in replacements):
            continue
        if not any(a <= m.start() and m.end() <= b for a, b in intervals):
            continue
        end = m.start()
        while end and text[end - 1].isspace():
            end -= 1
        if end and text[end - 1] in ')]':
            stack, start = [], None
            for pos in range(end - 1, -1, -1):
                c = text[pos]
                if c in ')}]':
                    stack.append(c)
                elif c in '({[':
                    if not stack or stack.pop() != {'(': ')', '[': ']', '{': '}'}[c]:
                        break
                    if not stack:
                        start = pos
                        break
            if start is None:
                continue
            # В группе допустимы только числовые операции и константы.
            # Даже сокращающиеся параметры (R-R+30) сохраняют исходный
            # символьный контекст: общий маркер градусов не меняет его.
            group = re.sub(
                r'\\(?:pi|frac|dfrac|tfrac|sqrt|cdot|times|div|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|log|ln|exp)\b'
                r'|(?<![A-Za-z])pi(?![A-Za-z])', '', text[start:end])
            if re.search(r'[^0-9.\s+*/^_{}\[\]()π-]', group):
                continue
        else:
            number = re.search(r'(?<![A-Za-z0-9_.^])\d+(?:\.\d+)?$', text[:end])
            if not number:
                continue
            start = number.start()
        # Не переводить в радианы только показатель степени:
        # R^2° и R^(2)° не означают R^(2*pi/180). Пробел,
        # знак и скобки не должны обходить эту границу.
        if re.search(r'\^\s*[+-]?\s*$', text[:start]):
            continue
        if re.search(_DEGREE_MARKER, text[start:end]):
            continue
        if any(a < m.end() and start < b for a, b in replacements):
            continue
        replacements[(start, m.end())] = '(' + text[start:end] + r'\cdot\pi/180)'
    for (a, b), value in sorted(replacements.items(), reverse=True):
        text = text[:a] + value + text[b:]
    return text


# Школьный нечётный корень вычисляется вещественной ветвью:
# real_root(v, n) = |v|^(1/n)·sign(v). Одно значение приходит в разных
# записях: ∛(x²) даёт |x|^(2/3)·sign(x²), (∛x)² — |x|^(2/3)·sign(x)², а
# x^(-2/3) — |x|^(-2/3)·sign(x)^(-2). SymPy не доказывает их равенство и
# местами ошибочно отвечает «не равно». Ниже знаки сводятся к одной форме:
# каждое действительное основание b входит в произведение один раз, как
# |b|^R·sign(b)^K с K ∈ {±1, ±2} или как b^R. Все шаги — тождества при
# b ≠ 0; при b = 0 значение сохраняется, а неопределённость (0 в
# отрицательной степени) не исчезает. Чётные корни (√x, x^(1/2)) сюда не
# попадают: у них нет sign, и их область определения не меняется.

def _real_base(value):
    """Основание без числового множителя и внешнего минуса: 6x+9 → (3, 2x+3)."""
    from sympy import S
    content, base = value.as_content_primitive() if value.is_Add else (S.One, value)
    if base.could_extract_minus_sign():
        content, base = -content, -base
    return content, base


def _split_sign(value):
    """sign(v) → произведение знаков действительных оснований.

    sign(ab)=sign(a)·sign(b), sign(b^n)=sign(b)^n при целом n,
    sign(|b|^r)=sign(|b|)=sign(b)² при r>0."""
    from sympy import Abs, Mul, sign
    if value.is_Mul:
        return Mul(*(_split_sign(factor) for factor in value.args))
    if value.is_Pow:
        base, exponent = value.args
        if base.is_real is True and exponent.is_Integer:
            return _split_sign(base) ** exponent
        if base.is_nonnegative is True and exponent.is_positive is True:
            return _split_sign(base)
    if isinstance(value, Abs) and value.args[0].is_real is True:
        return _split_sign(value.args[0]) ** 2
    if value.is_real is True and not value.is_Number:
        content, base = _real_base(value)
        if content != 1:
            return sign(content) * _split_sign(base)
    return sign(value)


def _merge_signs(value):
    """Множители |b|^r, sign(b)^k и b^m одного основания — в один.

    Сводятся только основания, у которых в произведении есть sign:
    записи без нечётных корней остаются как были."""
    from sympy import Abs, Mul, S, sign
    entries, rest = [], []
    factors = []
    for factor in Mul.make_args(value):
        inner, exponent = factor.as_base_exp()
        if isinstance(inner, Abs) and inner.args[0].is_Mul and exponent.is_Rational:
            # SymPy оставляет |ab| целым, если знаки a и b неизвестны.
            factors.extend(Abs(part) ** exponent for part in inner.args[0].args)
        else:
            factors.append(factor)
    for factor in factors:
        inner, exponent = factor.as_base_exp()
        entry = None
        if isinstance(inner, sign) and exponent.is_Integer:
            content, base = _real_base(inner.args[0])
            entry = (base, sign(content) ** exponent, S.Zero, exponent, True)
        elif isinstance(inner, Abs) and exponent.is_Rational:
            content, base = _real_base(inner.args[0])
            entry = (base, Abs(content) ** exponent, exponent, 0, False)
        elif exponent.is_Integer and inner.is_real is True and not inner.is_Number:
            content, base = _real_base(inner)
            entry = (base, content ** exponent, exponent, exponent, False)
        if entry is None or entry[0].is_real is not True:
            rest.append(factor)
        else:
            entries.append((factor, entry))
    signed = {entry[0] for _, entry in entries if entry[4]}
    powers = {}
    for factor, (base, coefficient, r, k, _) in entries:
        if base not in signed:
            rest.append(factor)
            continue
        rest.append(coefficient)
        total = powers.setdefault(base, [S.Zero, 0])
        total[0] += r
        total[1] += k
    for base, (r, k) in powers.items():
        if k:
            # sign(b)^k зависит только от чётности k; знак k хранит
            # неопределённость при b = 0.
            k = (1 if k % 2 else 2) * (1 if k > 0 else -1)
        if r < 0 and k < 0:
            # |b|^r уже не определён при b = 0.
            k = -k
        if r != 0 and k == 2:
            # sign(b)² = 1 при b ≠ 0, а при b = 0 обе части равны 0
            # или обе не определены.
            k = 0
        if r.is_integer and r != 0 and (k - r) % 2 == 0 and (k > 0 or r < 0):
            rest.append(base ** r)
        else:
            rest.append(Abs(base) ** r * sign(base) ** k)
    return Mul(*rest)


def _real_signs(value):
    """Единая запись вещественных нечётных корней (см. комментарий выше)."""
    from sympy import sign
    if value.is_Atom or not value.free_symbols or not value.has(sign):
        return value
    args = tuple(_real_signs(arg) for arg in value.args)
    if args != value.args:
        value = value.func(*args)
    if isinstance(value, sign):
        value = _split_sign(value.args[0])
    if value.is_Mul or value.is_Pow or isinstance(value, sign):
        value = _merge_signs(value)
    return value


def _parse(text, positive=(), *, numeric=False):
    from sympy import Expr, Symbol, pi
    if not text.strip() or len(text) > MAX_EXPR_LEN:
        return None
    if numeric:
        from ..check_answer import parse_number
        from .sets import _strip_var
        text = _numeric_degree_arguments(normalize(_strip_var(text)))
        text = re.sub(r'\\operatorname\{arctg\}|\\arctg\b', r'\\arctan', text)
        text = re.sub(r'(?<![A-Za-z\\])pi(?![A-Za-z])', r'\\pi ', text)
        literal = parse_number(text)
        if literal is not None:
            # Здесь знаменатель уже проверен как ненулевое целое; можно
            # убрать ведущий плюс и знак знаменателя без потери области.
            text = str(literal)
    else:
        # Числовой угол в градусах допустим и в формуле с параметрами:
        # R*sin(30°) = R/2. Символьные angle/range остаются отдельным
        # контекстом; преобразуются только явные числовые аргументы.
        text = _numeric_degree_arguments(normalize(text))
    text = _prepare(text)
    # Константа π не поддерживается штатной Lark-грамматикой.
    marker = next((c for c in 'QZXVW' if c not in text), None)
    has_pi = bool(re.search(r'\\pi\b|π', text))
    if has_pi:
        if marker is None:
            return None
        text = re.sub(r'\\pi\b|π', marker, text)
    # Выбираем одну ветвь неоднозначной грамматики до анализа областей.
    # Повторный разбор альтернатив в каждом поддереве тратит время и
    # может подставить области от другой интерпретации того же ввода.
    tree = expressions.resolve(expressions.raw_tree(text))
    numeric_pi = marker if numeric and has_pi else None
    value = expressions.evaluate(tree, numeric=numeric, pi_marker=numeric_pi)
    if tree is None or not isinstance(value, Expr):
        return None
    denominators = _denominators(tree, numeric=numeric, pi_marker=numeric_pi)
    components = _components(tree, numeric=numeric, pi_marker=numeric_pi)
    symbols = set(value.free_symbols)
    for component in (*denominators, *components):
        symbols.update(component.free_symbols)
    replacements = {s: (pi if has_pi and str(s) == marker else
                       Symbol(str(s), positive=True) if str(s) in positive else
                       Symbol(str(s), real=True)) for s in symbols}
    def move(component):
        # Знаки нечётных корней сводятся только после выбора вещественных
        # символов: для комплексного основания тождества не верны.
        return _real_signs(component.xreplace(replacements))
    return Formula(move(value), tuple(move(d) for d in denominators),
                   tuple(move(c) for c in components), tree)


def _reference_context(payload, multiple=False):
    """Разделяет именованные опции, сохраняя парные черты модулей.

    Первая версия области — одна строгая связь x<k*y при положительных
    x,y и положительном рациональном k. Рендер не загружает SymPy/Lark.
    """
    parts = re.split(r'\|\s*(?=[A-Za-z]+\s*:)', payload)
    options = {}
    for part in parts[1:]:
        match = re.fullmatch(r'\s*(positive|domain|angle|range)\s*:\s*(.*?)\s*', part)
        if not match or match[1] in options:
            raise ValueError('допустимы однократные опции positive, domain, angle и range')
        options[match[1]] = match[2]
    if sum(name in options for name in ('domain', 'angle', 'range')) > 1:
        raise ValueError('domain, angle и range несовместимы друг с другом')
    positive = ()
    token_re = r'(?:[A-Za-z]|\\[A-Za-z]+)'
    if 'positive' in options:
        names = []
        for token in options['positive'].split(','):
            token = token.strip()
            if not re.fullmatch(token_re, token):
                raise ValueError(r'положительные параметры: positive: a,R,\alpha')
            names.append(token)
        positive = tuple(dict.fromkeys(names))
    domain = None
    if 'domain' in options:
        # Длина коэффициента ограничена до загрузки символьного вычислителя.
        match = re.fullmatch(
            rf'\s*({token_re})\s*<\s*(?:(\d{{1,6}}(?:/\d{{1,6}})?)\s*\*?\s*)?({token_re})\s*',
            options['domain'])
        if not match or multiple:
            raise ValueError('область expression: domain: a<2b')
        left, coefficient, right = match.groups()
        coefficient = coefficient or '1'
        numbers = coefficient.split('/')
        if (any(int(n) == 0 for n in numbers) or left == right
                or left not in positive or right not in positive):
            raise ValueError('domain требует два различных положительных параметра')
        domain = (left, coefficient, right)
    angle = ()
    if 'angle' in options:
        degree = r'\d{1,3}(?:\.\d{1,3}|/\d{1,3})?'
        match = re.fullmatch(
            rf'\s*(?:({degree})\s*<\s*)?({token_re})\s*<\s*({degree})\s*', options['angle'])
        try:
            lower = Fraction(match[1] or '0') if match else None
            upper = Fraction(match[3]) if match else None
        except (ValueError, ZeroDivisionError):
            lower = upper = None
        if (not match or match[2] not in positive or domain or lower is None
                or not 0 <= lower < upper <= 360):
            raise ValueError(r'angle: \alpha<90 или 90<\beta<180; границы 0..360°, positive, без domain')
        angle = (match[2], lower, upper)
    bounds = ()
    if 'range' in options:
        number = r'\d{1,6}(?:\.\d{1,6}|/\d{1,6})?'
        match = re.fullmatch(
            rf'\s*(?:({number})\s*<\s*)?({token_re})\s*<\s*({number})\s*', options['range'])
        try:
            lower = Fraction(match[1] or '0') if match else None
            upper = Fraction(match[3]) if match else None
        except (ValueError, ZeroDivisionError):
            lower = upper = None
        if (not match or match[2] not in positive or lower is None
                or not 0 <= lower < upper):
            raise ValueError(r'range: \alpha<180 или 10<\alpha<45; положительный параметр, открытые рациональные границы')
        bounds = (match[2], lower, upper)
    # LaTeX-пробел \; не разделяет эталонный список. Исходный текст
    # сохраняем для отображения; математический парсер сам его нормализует.
    texts = re.split(r'(?<!\\);', parts[0]) if multiple else [parts[0]]
    if not texts or len(texts) > 20 or any(not t.strip() for t in texts):
        raise ValueError('укажите от 1 до 20 выражений через ;')
    return texts, positive, domain, angle, bounds


def _reference_parts(payload, multiple=False):
    texts, positive, _, _, _ = _reference_context(payload, multiple)
    return texts, positive



def _angular_range(value, substitutions):
    """Точные границы аффинного выражения от atan(u), u>0; обе открыты."""
    from sympy import Dummy, atan, pi
    atoms = set().union(*(v.atoms(atan) for _, v in substitutions))
    for atom in atoms:
        if not value.has(atom):
            continue
        t = Dummy('angle_atom', real=True)
        polynomial = value.xreplace({atom: t}).as_poly(t)
        if polynomial is None or polynomial.degree() != 1:
            continue
        coefficient, constant = polynomial.nth(1), polynomial.nth(0)
        if coefficient.is_positive is True:
            return constant, constant+coefficient*pi/2
        if coefficient.is_negative is True:
            return constant+coefficient*pi/2, constant
    return None


def _angular_sign(value, substitutions):
    """Знак доказывается интервалом и алгеброй, а не пробными значениями."""
    from sympy import Abs, Add, Mul, Pow, Rational, sin, cos, tan, cot, pi, floor, simplify
    if value.is_positive is True:
        return 1
    if value.is_negative is True:
        return -1
    if value.is_zero is True:
        return 0
    bounds = _angular_range(value, substitutions)
    if bounds:
        lower, upper = bounds
        if lower.is_nonnegative is True:
            return 1
        if upper.is_nonpositive is True:
            return -1
    if value.func in (sin, cos):
        bounds = _angular_range(value.args[0], substitutions)
        if bounds:
            lower, upper = (simplify(x/pi) for x in bounds)
            if lower.is_Rational and upper.is_Rational:
                shift = 2*floor(lower/2)
                lower, upper = lower-shift, upper-shift
                if value.func == sin:
                    if 0 <= lower < upper <= 1:
                        return 1
                    if 1 <= lower < upper <= 2:
                        return -1
                else:
                    if (0 <= lower < upper <= Rational(1, 2)
                            or Rational(3, 2) <= lower < upper <= Rational(5, 2)):
                        return 1
                    if Rational(1, 2) <= lower < upper <= Rational(3, 2):
                        return -1
    if value.func in (tan, cot):
        sine = _angular_sign(sin(value.args[0]), substitutions)
        cosine = _angular_sign(cos(value.args[0]), substitutions)
        if sine in (-1, 1) and cosine in (-1, 1):
            return sine*cosine
    if value.func in (Add, Mul):
        signs = [_angular_sign(x, substitutions) for x in value.args]
        if any(x is None for x in signs):
            return None
        if value.func == Mul:
            result = 1
            for sign in signs:
                result *= sign
            return result
        if all(x >= 0 for x in signs) and any(x > 0 for x in signs):
            return 1
        if all(x <= 0 for x in signs) and any(x < 0 for x in signs):
            return -1
    if value.func == Pow:
        base, exponent = value.args
        sign = _angular_sign(base, substitutions)
        if sign in (-1, 1) and exponent.is_Integer:
            return sign if exponent.is_odd else 1
        if sign == 1 and exponent.is_Rational:
            return 1
    if value.func == Abs:
        sign = _angular_sign(value.args[0], substitutions)
        if sign is not None:
            return abs(sign)
    return None


def _angular_everywhere(value, substitutions):
    """Достаточное доказательство вещественности и конечности компонента."""
    from sympy import Add, Mul, Pow, sin, cos, atan, tan, cot
    if value.is_real is True and value.is_finite is True:
        return True
    if value.func in (Add, Mul):
        return all(_angular_everywhere(x, substitutions) for x in value.args)
    if value.func == Pow:
        base, exponent = value.args
        if not exponent.is_Rational or not _angular_everywhere(base, substitutions):
            return False
        sign = _angular_sign(base, substitutions)
        if exponent.is_Integer:
            return exponent >= 0 or sign in (-1, 1)
        return sign == 1
    if value.func in (sin, cos, atan, tan, cot):
        if not _angular_everywhere(value.args[0], substitutions):
            return False
        if value.func in (tan, cot):
            denominator = cos(value.args[0]) if value.func == tan else sin(value.args[0])
            return _angular_sign(denominator, substitutions) in (-1, 1)
        return True
    return False

def _angular_half_angles(value):
    """Точные половинные углы atan(u), u>0, с доказанным знаком корней."""
    from sympy import S, atan, sin, cos, tan, cot, sqrt, expand_trig, factor

    def half_angle(node):
        if node.func not in (sin, cos, tan, cot):
            return False
        doubled = 2*node.args[0]
        return doubled.func == atan and doubled.args[0].is_positive is True

    def replace_half_angle(node):
        u = (2*node.args[0]).args[0]
        length = sqrt(1+u*u)
        # 0<atan(u)/2<π/4: все четыре значения положительны.
        # Эта запись синуса не оставляет неопределённый знак sqrt(length-1).
        if node.func == sin:
            return u/sqrt(2*length*(length+1))
        if node.func == cos:
            return sqrt((length+1)/(2*length))
        if node.func == tan:
            return u/(length+1)
        return (length+1)/u

    value = factor(expand_trig(value.replace(half_angle, replace_half_angle)))

    def positive_radical_difference(node):
        if not node.is_Add or len(node.args) != 2:
            return False
        for radical in node.args:
            if radical.is_Pow and radical.exp == S.Half:
                other = radical-node
                if (other.is_positive is True
                        and (radical.base-other*other).is_positive is True):
                    return True
        return False

    def rationalize_positive_difference(node):
        radical = next(term for term in node.args
                       if term.is_Pow and term.exp == S.Half)
        other = radical-node
        # sqrt(b)-c=(b-c²)/(sqrt(b)+c), c>0, b-c²>0.
        # Новый знаменатель строго положителен; знак не предполагается.
        return (radical.base-other*other)/(radical+other)

    return factor(value.replace(positive_radical_difference,
                                rationalize_positive_difference))


def _in_context(item, substitutions, *, angular=False, algebraic=False):
    """Переносит исходные ограничения, а не только сокращённую формулу."""
    replacements = dict(substitutions)
    def move(value):
        value = value.xreplace(replacements)
        if angular:
            # Формулы двойного угла переводят sin/cos(2*atan(u))
            # в точные рациональные выражения; ограничения каждого
            # исходного подвыражения переносятся отдельно.
            from sympy import Abs, Dummy, S, sign, sin, cos, tan, cot
            value = _angular_half_angles(value)
            value = value.replace(
                lambda node: node.func == Abs and _angular_sign(node.args[0], substitutions) in (-1, 0, 1),
                lambda node: _angular_sign(node.args[0], substitutions)*node.args[0])
            value = value.replace(
                lambda node: node.func == sign and _angular_sign(node.args[0], substitutions) in (-1, 0, 1),
                lambda node: S(_angular_sign(node.args[0], substitutions)))
            # Знак этих функций доказан на всём открытом интервале.
            # Временный положительный символ разрешает сокращать нечётные
            # корни степеней; неизвестные знаки и исходные области не меняем.
            proven, restore = {}, {}
            for node in value.atoms(sin, cos, tan, cot):
                polarity = _angular_sign(node, substitutions)
                if polarity in (-1, 1):
                    magnitude = Dummy('proved_trig_magnitude', positive=True)
                    proven[node] = polarity*magnitude
                    restore[magnitude] = polarity*node
            value = value.xreplace(proven).xreplace(restore)
        elif algebraic:
            # Алгебраическая область x<k*y задаёт положительные u,v.
            # Раскрытый радиканд (u+v)^2-u^2 скрывает положительность;
            # факторизация v*(2*u+v) доказывает её без пробных значений.
            # Каждый исходный компонент и знаменатель переносится отдельно,
            # поэтому сокращённая формула не скрывает добавленный разрыв.
            from sympy import factor
            value = factor(value)
        return value
    return Formula(move(item.expression),
                   tuple(move(d) for d in item.denominators),
                   tuple(move(c) for c in item.components), item.tree)


def _parse_reference(payload, multiple=False, *, numeric=False):
    texts, tokens, domain, angle, bounds = _reference_context(payload, multiple)
    names = []
    for token in tokens:
        parsed = _parse(token)
        if parsed is None or not getattr(parsed.expression, 'is_Symbol', False):
            raise ValueError(r'положительные параметры: positive: a,R,\alpha')
        # Имена вариантов могут совпадать: \varphi разбирается как phi.
        names.append(str(parsed.expression))
    positive = tuple(dict.fromkeys(names))
    items = tuple(_parse(t.strip(), positive, numeric=numeric) for t in texts)
    if any(x is None for x in items):
        raise ValueError('эталон не разобран как выражение')
    symbols = set()
    for item in items:
        symbols.update(item.expression.free_symbols)
        for component in (*item.denominators, *item.components):
            symbols.update(component.free_symbols)
    if set(positive) - {str(s) for s in symbols}:
        raise ValueError('positive содержит параметр, которого нет в эталоне')
    input_symbols = tuple(sorted(symbols, key=str))
    substitutions = ()
    if domain:
        from sympy import Dummy, Rational
        left_token, coefficient, right_token = domain
        left_name = str(_parse(left_token).expression)
        right_name = str(_parse(right_token).expression)
        if left_name == right_name:
            raise ValueError('domain требует различные параметры после разбора имён')
        by_name = {str(symbol): symbol for symbol in symbols}
        left, right = by_name[left_name], by_name[right_name]
        k = Rational(coefficient)
        u, v = Dummy('domain_u', positive=True), Dummy('domain_v', positive=True)
        # x=k*u,y=u+v — биекция: u=x/k>0,v=y-x/k>0.
        # Она точно задаёт x>0,y>0,x<k*y без пробных приближений.
        substitutions = ((left, k*u), (right, u+v))
        items = tuple(_in_context(item, substitutions, algebraic=True) for item in items)
        symbols = set().union(*(component.free_symbols
                              for item in items
                              for component in (item.expression, *item.denominators, *item.components)))
    if angle:
        from sympy import Dummy, Rational, atan, pi
        token, lower, upper = angle
        name = str(_parse(token).expression)
        symbol = next(s for s in input_symbols if str(s) == name)
        u = Dummy('angle_u', positive=True)
        # atan(u) биективно задаёт (0,π/2). Сдвиг и масштаб точно
        # переводят его в заданный открытый интервал угла.
        # Границы — в градусах, внутреннее представление — радианное.
        lower, upper = Rational(str(lower)), Rational(str(upper))
        substitutions = ((symbol, lower*pi/180 + (upper-lower)*atan(u)/90),)
        items = tuple(_in_context(item, substitutions, angular=True) for item in items)
        symbols = set().union(*(component.free_symbols
                              for item in items
                              for component in (item.expression, *item.denominators, *item.components)))
    if bounds:
        from sympy import Dummy, Rational
        token, lower, upper = bounds
        name = str(_parse(token).expression)
        symbol = next(s for s in input_symbols if str(s) == name)
        lower, upper = Rational(str(lower)), Rational(str(upper))
        u = Dummy('range_u', positive=True)
        # x=L+(U-L)u/(1+u) — биекция (0,∞) на (L,U).
        # Числовое значение и его единицы сохраняются, включая градусы.
        substitutions = ((symbol, lower+(upper-lower)*u/(1+u)),)
        items = tuple(_in_context(item, substitutions) for item in items)
        symbols = set().union(*(component.free_symbols
                              for item in items
                              for component in (item.expression, *item.denominators, *item.components)))
    reference = Reference(items, positive, tuple(sorted(symbols, key=str)),
                          input_symbols, substitutions, angle, bounds)
    if any(_defined(item, reference) is False for item in items):
        raise ValueError('эталон не определён на указанной области параметров')
    return reference, ';'.join(texts).strip()


def _sign_root(base):
    """Основание того же знака: 2x³ → x, -(2-x)⁵ → x-2."""
    coefficient, rest = base.as_coeff_Mul()
    if rest.is_Pow and rest.exp.is_Integer and rest.exp.is_odd and rest.exp > 0:
        rest = rest.base
    if coefficient.is_nonzero is not True:
        return base
    return rest if coefficient > 0 else -rest


def _nonneg_bases(values):
    """Основания чётных корней: там, где values вещественны, они ≥ 0.

    Главная ветвь b^(p/q) с чётным q вещественна только при b ≥ 0. Знак
    переходит и к основанию нечётной степени: 2x³ ≥ 0 ⇔ x ≥ 0,
    -(2-x)⁵ ≥ 0 ⇔ x-2 ≥ 0."""
    from sympy import Pow
    found = set()
    for value in values:
        for node in value.atoms(Pow):
            base, exponent = node.args
            if (exponent.is_Rational and exponent.q % 2 == 0
                    and base.is_real is True and not base.is_number):
                found |= {base, _sign_root(base)}
    return found


def _on_domain(nonneg):
    """Сравнение на области эталона с чётными корнями.

    Там основания из nonneg неотрицательны: b^(p/q) = |b|^(p/q), а символ
    x ≥ 0 (x ≤ 0) можно заменить положительным p (−p). Без этого SymPy
    сравнивает главные комплексные ветви x^(5/4) и (x⁵)^(1/4) при x < 0,
    где ни одна из записей не определена."""
    from sympy import Abs, Dummy
    if not nonneg:
        return None
    polarity = {}
    for base in nonneg:
        coefficient, rest = base.as_coeff_Mul()
        if rest.is_Symbol and coefficient in (1, -1):
            # x ≥ 0 и x ≤ 0 вместе оставляют только x = 0: не заменяем.
            polarity[rest] = coefficient if polarity.get(rest, coefficient) == coefficient else 0
    substitution = {symbol: side * Dummy(symbol.name, positive=True)
                    for symbol, side in polarity.items() if side}

    def restrict(value):
        value = value.replace(
            lambda node: (node.is_Pow and node.exp.is_Rational
                          and node.exp.q % 2 == 0 and _sign_root(node.base) in nonneg),
            lambda node: Abs(node.base) ** node.exp)
        return value.xreplace(substitution)
    return restrict


def _zero_bases(value):
    """Основания, обнуляющие произведение c·∏|b|^r·sign(b)^k·b^m с
    положительными показателями: оно равно нулю, только когда одно из
    оснований равно нулю. None — если value так не раскладывается."""
    from sympy import Abs, Mul, sign
    bases = set()
    for factor in Mul.make_args(value):
        if factor.is_number:
            if factor.is_zero is not False or factor.is_finite is not True:
                return None
            continue
        inner, exponent = factor.as_base_exp()
        if exponent.is_positive is not True:
            return None
        if isinstance(inner, (Abs, sign)):
            inner = inner.args[0]
        if inner.is_Mul or inner.is_Pow:
            nested = _zero_bases(inner)
            if nested is None:
                return None
            bases |= nested
        else:
            bases.add(_real_base(inner)[1])
    return bases


def _real_poles(value, nonneg):
    """Основания, в нуле которых value не определено, если value — сумма
    произведений вещественных степеней: |b|^r, sign(b)^k, b^m с целым m и
    b^r для основания из nonneg. None — если вещественность так не доказать."""
    from sympy import Abs, sign
    if value.is_number:
        return set() if value.is_real is True and value.is_finite is True else None
    if value.is_Add or value.is_Mul:
        poles = set()
        for arg in value.args:
            nested = _real_poles(arg, nonneg)
            if nested is None:
                return None
            poles |= nested
        return poles
    if isinstance(value, (Abs, sign)):
        return _real_poles(value.args[0], nonneg)
    if value.is_Pow:
        base, exponent = value.args
        if not exponent.is_Rational:
            return None
        if not (exponent.is_Integer or _sign_root(base) in nonneg
                or isinstance(base, Abs) or base.is_nonnegative is True):
            return None
        poles = _real_poles(base, nonneg)
        if poles is None or exponent > 0:
            return poles
        zeros = _zero_bases(base)
        return None if zeros is None else poles | zeros
    return set() if value.is_real is True and value.is_finite is True else None


def _defined(item, reference):
    """Отсекает лишние разрывы и невещественные значения на области эталона."""
    from sympy import S, Interval, solveset, oo
    from sympy.calculus.util import continuous_domain
    value = item.expression
    if any(c.has(S.NaN, S.ComplexInfinity, S.Infinity, S.NegativeInfinity)
           for c in (value, *item.components)):
        return False
    if any(c.is_real is False for c in (value, *item.components)):
        return False
    if any(d.is_zero is True for d in item.denominators):
        return False
    # Если каждое исходное подвыражение вещественно и конечно при данных
    # предположениях, а исходные знаменатели доказанно ненулевые, формула
    # определена на всей области параметров. Решать те же простые области
    # заново через continuous_domain не требуется. Неизвестные свойства
    # сюда не попадают: сокращённый (a-1)/(a-1) всё ещё проверяется ниже.
    def everywhere(component):
        return ((component.is_real is True and component.is_finite is True)
                or bool(reference.angle) and _angular_everywhere(component, reference.substitutions))

    def nonzero(component):
        return (component.is_nonzero is True
                or bool(reference.angle) and _angular_sign(component, reference.substitutions) in (-1, 1))

    if (all(everywhere(c) for c in (value, *item.components))
            and all(nonzero(d) for d in item.denominators)):
        return True
    # Область эталона уже включает ограничения его исходных компонентов.
    # Если ввод не добавляет ни одного такого ограничения, включение
    # доказано непосредственно, без повторного решения тех же областей.
    originals = {c for original in reference.items
                 for c in (original.expression, *original.components)}
    original_denominators = {d for original in reference.items
                             for d in original.denominators}
    @lru_cache(maxsize=None)
    def real_from_original(component):
        if component in originals or everywhere(component):
            return True
        # Суммы и произведения конечных вещественных выражений сохраняют
        # область. Извлечение положительного числового множителя из корня
        # даёт, например, sqrt(4*f)=2*sqrt(f), уже допустимого в эталоне.
        # Исходные компоненты и знаменатели ниже проверяются все: это
        # доказательство не разрешает сокращать дополнительный разрыв.
        from sympy import factor_terms
        reduced = factor_terms(component)
        if reduced in originals or everywhere(reduced):
            return True
        return ((reduced.is_Add or reduced.is_Mul)
                and all(real_from_original(arg) for arg in reduced.args))

    if (all(real_from_original(c) for c in (value, *item.components))
            and all(d in original_denominators or nonzero(d)
                    for d in item.denominators)):
        return True
    # Степени и корни: x^(-2/3) вместо 1/∛(x²), 1/∛e вместо e^(-1/3).
    # Знаменатель эталона ≠ 0 на его области, значит, ненулевые и все
    # основания, из которых он составлен. Если ввод делит только на эти
    # основания, а чётные корни берёт только из неотрицательных на области
    # эталона оснований, новых разрывов и невещественных значений нет.
    nonneg = _nonneg_bases(originals)
    allowed = set()
    for denominator in original_denominators:
        allowed |= _zero_bases(denominator) or set()

    def covered(bases):
        return bases is not None and all(
            base in allowed or nonzero(base) for base in bases)

    if (all(real_from_original(c) or covered(_real_poles(c, nonneg))
            for c in (value, *item.components))
            and all(d in original_denominators or nonzero(d) or covered(_zero_bases(d))
                    for d in item.denominators)):
        return True
    # Допустимая точная точка с новым разрывом уже опровергает ввод;
    # трудное построение всей области определения после неё не нужно.
    if _domain_counterexample(item, reference):
        return False
    if len(reference.symbols) == 1:
        symbol = reference.symbols[0]
        domain = Interval.open(0, oo) if symbol.is_positive else S.Reals
        try:
            # Допустимая область включает ограничения исходной формулы.
            allowed = domain
            for original in reference.items:
                for component in (original.expression, *original.components):
                    if not everywhere(component):
                        allowed = allowed.intersect(continuous_domain(component, symbol, domain))
                for denominator in original.denominators:
                    if denominator.is_nonzero is not True:
                        allowed = allowed - solveset(denominator, symbol, domain=domain)
            valid = domain if everywhere(value) else continuous_domain(value, symbol, domain)
            for component in item.components:
                if not everywhere(component):
                    valid = valid.intersect(continuous_domain(component, symbol, domain))
            for denominator in item.denominators:
                if denominator.is_nonzero is not True:
                    valid = valid - solveset(denominator, symbol, domain=domain)
            return (allowed - valid).is_empty
        except (NotImplementedError, ValueError, TypeError):
            return None
    # Для нескольких параметров доказываем достаточное включение областей.
    # Рациональные преобразования допустимы, если каждый новый знаменатель
    # делит многочлен, ненулевой на исходной области. Пробные значения не
    # используются как доказательство отсутствия разрывов.
    from sympy import cancel
    originals = tuple(c for original in reference.items
                      for c in (original.expression, *original.components))
    original_denominators = [d for original in reference.items
                             for d in original.denominators]
    original_denominators.extend(c.as_numer_denom()[1] for c in originals
                                 if c.is_rational_function(*reference.symbols))

    def nonzero_on_original(d):
        if nonzero(d) or d in original_denominators:
            return True
        if d.is_polynomial(*reference.symbols):
            for original in original_denominators:
                numerator = original.as_numer_denom()[0]
                if (numerator.is_polynomial(*reference.symbols)
                        and cancel(numerator / d).is_polynomial(*reference.symbols)):
                    return True
        return False

    def real_on_original(c):
        if c.is_real is True or c in originals:
            return True
        if c.is_rational_function(*reference.symbols):
            numerator, denominator = c.as_numer_denom()
            return (numerator.is_real is True and denominator.is_real is True
                    and nonzero_on_original(denominator))
        return False

    if (all(nonzero_on_original(d) for d in item.denominators)
            and all(real_on_original(c) for c in (value, *item.components))):
        return True
    if _domain_counterexample(item, reference):
        return False
    return None


def _domain_counterexample(item, reference):
    """Точная допустимая точка может доказать наличие лишнего разрыва.

    Отсутствие контрпримера ничего не доказывает: вызывающий код возвращает
    UNKNOWN, если включение областей не установлено аналитически.
    """
    from sympy import S, Rational, atan, pi, tan, cancel
    baseline = {symbol: S.One for symbol in reference.symbols}
    values_to_try = [baseline]
    if reference.angle:
        # Точные внутренние точки и корни нужны лишь для опровержения.
        # Принятие ответа по-прежнему требует доказательства всей области.
        for _, replacement in reference.substitutions:
            for atom in replacement.atoms(atan):
                symbol = atom.args[0]
                others = {s: n for s, n in baseline.items() if s != symbol}
                values_to_try.extend({**baseline, symbol: number}
                                     for number in (Rational(1, 2), Rational(1, 3)))
                for denominator in item.denominators:
                    reduced = denominator.subs(others)
                    t = symbol.as_dummy()
                    affine = reduced.xreplace({atom: t}).as_poly(t)
                    if affine is not None and affine.degree() == 1:
                        theta = -affine.nth(0)/affine.nth(1)
                        if (not theta.has(symbol) and theta.is_positive is True
                                and (pi/2-theta).is_positive is True):
                            root = tan(theta)
                            if root.is_positive is True and root.is_finite is True:
                                values_to_try.append({**baseline, symbol: root})
                    polynomial = cancel(reduced).as_numer_denom()[0].as_poly(symbol)
                    if (polynomial is not None and 1 <= polynomial.degree() <= 4
                            and all(c.is_Rational for c in polynomial.all_coeffs())):
                        for root in polynomial.all_roots():
                            if root.is_positive is True:
                                values_to_try.append({**baseline, symbol: root})
    # Проверяем точные корни по каждому параметру при остальных=1.
    # Это только поиск контрпримера; отсутствие корня не доказывает область.
    for symbol in reference.symbols:
        others = {s: n for s, n in baseline.items() if s != symbol}
        candidates = list(item.denominators)
        if reference.bounds:
            # В рациональной карте корни и деления имеют рациональные
            # аргументы. Корень их числителя и соседние точные точки
            # могут опровергнуть скрытый разрыв/невещественный корень.
            candidates.extend(c.args[0] for c in item.components
                              if c.is_Pow and c.exp.is_Rational and not c.exp.is_Integer)
        for candidate in candidates:
            value = candidate.subs(others)
            if reference.bounds:
                value = cancel(value).as_numer_denom()[0]
            polynomial = value.as_poly(symbol)
            if polynomial is None or not 1 <= polynomial.degree() <= 8:
                continue
            # Составная дробь сохраняет произведение исходных знаменателей.
            # Ищем линейные множители небольшого точного полинома: например,
            # (3u+v)(u-3v) имеет допустимый разрыв u=3 при v=1.
            factors = polynomial.factor_list()[1]
            for factor, _ in factors:
                if factor.degree() != 1:
                    continue
                root = -factor.nth(0) / factor.nth(1)
                if root.is_real is True and (not symbol.is_positive or root.is_positive is True):
                    values_to_try.append({**baseline, symbol: root})
                    if reference.bounds and root.is_positive is True:
                        values_to_try.extend(({**baseline, symbol: root/2},
                                              {**baseline, symbol: 2*root}))
    for symbol in reference.symbols:
        for number in (-2, -1, 0, 1, 2):
            if symbol.is_positive and number <= 0:
                continue
            values_to_try.append({**baseline, symbol: S(number)})
    for values in values_to_try:
        allowed = all(
            all((v := component.subs(values)).is_real is True and v.is_finite is True
                for component in (original.expression, *original.components))
            and all(denominator.subs(values).is_zero is False
                    for denominator in original.denominators)
            for original in reference.items)
        if not allowed:
            continue
        if any(denominator.subs(values).is_zero is True for denominator in item.denominators):
            return True
        for component in (item.expression, *item.components):
            value = component.subs(values)
            if value.has(S.NaN, S.ComplexInfinity, S.Infinity, S.NegativeInfinity) or value.is_real is False:
                return True
    return False


def _counterexample(difference, reference):
    """Точная допустимая подстановка может опровергнуть, но не доказать равенство.

    SymPy.equals иногда не решает Abs(a)-a из-за случайных проб. Проверяем
    знаки параметров детерминированно; неизвестные результаты не принимаем.
    """
    from sympy import S

    baseline = {symbol: S.One for symbol in reference.symbols}
    for symbol in reference.symbols:
        for number in (-2, -1, 1, 2):
            if symbol.is_positive and number <= 0:
                continue
            values = {**baseline, symbol: S(number)}
            valid = True
            for original in reference.items:
                for component in (original.expression, *original.components):
                    value = component.subs(values)
                    valid &= value.is_real is True and value.is_finite is True
                for denominator in original.denominators:
                    valid &= denominator.subs(values).is_zero is False
            if valid and difference.subs(values).is_zero is False:
                return True
    return False


def _split_list(value, count):
    """Элементы списка ``expressions``: основной разделитель — «;». Без него
    принимаются «, », «,» и «и», если число частей совпадает с эталоном:
    ``8, 40`` и ``22,5, 67,5, 90`` — списки, а не одно число."""
    if ';' in value or count < 2:
        return value.split(';')
    for separator in (r',\s+', r'\s+(?:и|or|and)\s+', ','):
        parts = re.split(separator, value)
        if len(parts) == count:
            return parts
    return [value]


def _check(value, reference, multiple=False, mode='expression', *, numeric=False):
    from sympy import Pow, expand, factor, sign, simplify
    if len(value) > MAX_EXPR_LEN:
        return UNKNOWN
    # Команды \;, \,, \: и \! — пробелы, а не элементы списка.
    # Та же нормализация применяется при разборе отдельного выражения.
    value = normalize(value)
    # Поле одного выражения не допускает список, даже с верным первым
    # элементом. В режиме expressions разделитель остаётся допустимым.
    if not multiple and ';' in value:
        return WRONG
    texts = _split_list(value, len(reference.items)) if multiple else [value]
    if len(texts) != len(reference.items) or any(not t.strip() for t in texts):
        return WRONG
    student = tuple(_parse(t.strip(), reference.positive, numeric=numeric) for t in texts)
    if any(item is None for item in student):
        return UNKNOWN
    if reference.substitutions and (mode != 'expression' or (multiple and not (reference.angle or reference.bounds))):
        return UNKNOWN
    allowed_symbols = set(reference.input_symbols or reference.symbols)
    for item in student:
        if item.expression.free_symbols - allowed_symbols:
            return WRONG
        for component in (*item.denominators, *item.components):
            if component.free_symbols - allowed_symbols:
                return WRONG
    student = tuple(_in_context(
        item, reference.substitutions, angular=bool(reference.angle),
        algebraic=bool(reference.substitutions) and not (reference.angle or reference.bounds),
    ) for item in student)
    # Доказуемо неверную формулу можно отклонить до трудного анализа
    # области. Для принятия ответа проверка всех исходных ограничений
    # остаётся обязательной, даже после сокращения к эталону.
    uncertain_comparison = False
    # Сохраняем кратность: лишняя или повторная длина не заменяет другую.
    remaining = list(reference.items)
    for item in student:
        # Сначала ищем уже совпавшее выражение: при перестановке диагоналей
        # сравнение с другой диагональю может зря исчерпать бюджет SymPy.
        # Все исходные знаменатели и компоненты проверяются ниже даже
        # после этого совпадения; сокращение не скрывает дырку в области.
        exact = next((index for index, expected in enumerate(remaining)
                      if item.expression == expected.expression), None)
        if exact is not None:
            remaining.pop(exact)
            continue
        uncertain = False
        for index, expected in enumerate(remaining):
            # Полный квадрат под корнем может быть раскрыт: sqrt(x²-2x+1).
            # factor сохраняет реальный модуль, в отличие от принудительного
            # извлечения корня; исходные области уже проверены отдельно.
            difference = simplify(factor(item.expression) - factor(expected.expression))
            same = difference == 0 or difference.equals(0)
            raw = item.expression - expected.expression
            if same is not True and raw.has(sign) and all(
                    not node.base.is_Add or abs(node.exp) <= 12
                    for node in raw.atoms(Pow) if node.exp.is_Integer):
                # Раскрытие скобок снова порождает sign(b)² у нечётных
                # корней: (∛m)·(∛m)² — сводим знаки ещё раз после expand.
                # simplify здесь не помогает: он заменяет sign на Piecewise.
                # Большие степени сумм не раскрываем: это не школьная запись,
                # а лишняя нагрузка на вычислитель.
                if _real_signs(expand(raw)) == 0:
                    same = True
            if same is not True:
                # Чётные корни эталона ограничивают область; вне её SymPy
                # видит разные комплексные ветви и не находит равенства.
                restrict = _on_domain(_nonneg_bases(
                    (expected.expression, *expected.components)))
                if restrict is not None:
                    restricted = simplify(factor(restrict(item.expression))
                                          - factor(restrict(expected.expression)))
                    if restricted == 0 or restricted.equals(0) is True:
                        same = True
            if same is None and _counterexample(difference, reference):
                same = False
            if same is True:
                remaining.pop(index)
                break
            uncertain |= same is None
        else:
            if not uncertain:
                return WRONG
            uncertain_comparison = True
            break
    for item in student:
        defined = _defined(item, reference)
        if defined is not True:
            return WRONG if defined is False else UNKNOWN
    if uncertain_comparison:
        return UNKNOWN
    # Равносильность уже доказана с исходными областями и предположениями.
    # Повторное сравнение без positive/π потеряло бы этот контекст. По сырому
    # дереву отдельно проверяем только требуемый вид записи.
    if mode == 'simplify':
        item = student[0]
        if (expressions.reducible(item.tree)
                or expressions.unsimplified(item.expression, reference.items[0].expression)):
            return WRONG
    elif mode == 'factor':
        if not expressions.fully_factored(expressions.resolve(student[0].tree),
                                          expressions.resolve(reference.items[0].tree)):
            return WRONG
    return OK

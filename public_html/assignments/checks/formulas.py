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
from pathlib import Path

from ..check_answer import MAX_EXPR_LEN, OK, UNKNOWN, WRONG
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


@dataclass(frozen=True)
class FormulaSpec:
    payload: str
    multiple: bool
    mode: str = 'expression'


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
    texts, _ = _reference_parts(payload, multiple)
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
    result = _run_worker({'payload': reference.payload,
                          'multiple': reference.multiple, 'mode': reference.mode,
                          'value': value})
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
    if len(value) > MAX_EXPR_LEN:
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

    def after_power(match):
        if re.search(r'\\' + functions + r'$', text[:match.start()]):
            return match.group(1)
        return match.group(1) + r'\cdot '

    text = re.sub(
        r'(\^(?:\{[^{}]+\}|[+-]?\d+))\s*(?=[A-Za-z]|\\(?:sqrt|frac|pi|' + functions + r')\b)',
        after_power, text)
    text = re.sub(r'(\^\{[^{}]+\})\s*(?=\()', after_power, text)
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



def _components(tree):
    """Сохраняет области подвыражений до сокращения корней и степеней."""
    if not expressions._is_tree(tree):
        return []
    tree = expressions.resolve(tree)
    value = expressions.evaluate(tree)
    result = [value] if value is not None and hasattr(value, 'free_symbols') else []
    for child in tree.children:
        result.extend(_components(child))
    return result


def _denominators(tree):
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
                exponent = (expressions.evaluate(child) if expressions._is_tree(child)
                            else expressions.parse_expr(str(child)))
                # В школьной записи нулевая и отрицательная степени
                # требуют ненулевого основания, даже если SymPy уже
                # превратил a^0 в единицу.
                child = operands[0] if getattr(exponent, 'is_nonpositive', None) is True else None
            value = (expressions.evaluate(child) if expressions._is_tree(child)
                     else expressions.parse_expr(str(child)) if child is not None else None)
            if value is not None:
                result.append(value)
    for child in tree.children:
        result.extend(_denominators(child))
    return result


def _parse(text, positive=()):
    from sympy import Expr, Symbol, pi
    if not text.strip() or len(text) > MAX_EXPR_LEN:
        return None
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
    value = expressions.evaluate(tree)
    if tree is None or not isinstance(value, Expr):
        return None
    denominators = _denominators(tree)
    components = _components(tree)
    symbols = set(value.free_symbols)
    for component in (*denominators, *components):
        symbols.update(component.free_symbols)
    replacements = {s: (pi if has_pi and str(s) == marker else
                       Symbol(str(s), positive=True) if str(s) in positive else
                       Symbol(str(s), real=True)) for s in symbols}
    return Formula(value.xreplace(replacements),
                   tuple(d.xreplace(replacements) for d in denominators),
                   tuple(c.xreplace(replacements) for c in components), tree)


def _reference_parts(payload, multiple=False):
    # Вертикальные черты модулей являются частью выражения. Опцию
    # отделяем только | перед завершающей опцией positive.
    parts = re.split(r'\|\s*(?=positive\s*:)', payload)
    if len(parts) > 2:
        raise ValueError('допустима одна опция positive: a,R')
    positive = ()
    if len(parts) == 2:
        match = re.fullmatch(r'\s*positive\s*:\s*(.*?)\s*', parts[1])
        if not match:
            raise ValueError(r'положительные параметры: positive: a,R,\alpha')
        names = []
        for token in match[1].split(','):
            token = token.strip()
            # Только одна буква или LaTeX-команда символа. Формулы,
            # функции и константы не являются именами параметров.
            if not re.fullmatch(r'(?:[A-Za-z]|\\[A-Za-z]+)', token):
                raise ValueError(r'положительные параметры: positive: a,R,\alpha')
            # Рендер проверяет только структуру: SymPy и Lark загружаются
            # исключительно в ограниченном вычислительном процессе.
            names.append(token)
        positive = tuple(dict.fromkeys(names))
    texts = parts[0].split(';') if multiple else [parts[0]]
    if not texts or len(texts) > 20 or any(not t.strip() for t in texts):
        raise ValueError('укажите от 1 до 20 выражений через ;')
    return texts, positive


def _parse_reference(payload, multiple=False):
    texts, tokens = _reference_parts(payload, multiple)
    names = []
    for token in tokens:
        parsed = _parse(token)
        if parsed is None or not getattr(parsed.expression, 'is_Symbol', False):
            raise ValueError(r'положительные параметры: positive: a,R,\alpha')
        # Имена вариантов могут совпадать: \varphi разбирается как phi.
        names.append(str(parsed.expression))
    positive = tuple(dict.fromkeys(names))
    items = tuple(_parse(t.strip(), positive) for t in texts)
    if any(x is None for x in items):
        raise ValueError('эталон не разобран как выражение')
    symbols = set()
    for item in items:
        symbols.update(item.expression.free_symbols)
        for component in (*item.denominators, *item.components):
            symbols.update(component.free_symbols)
    if set(positive) - {str(s) for s in symbols}:
        raise ValueError('positive содержит параметр, которого нет в эталоне')
    reference = Reference(items, positive, tuple(sorted(symbols, key=str)))
    if any(_defined(item, reference) is False for item in items):
        raise ValueError('эталон не определён на указанной области параметров')
    return reference, ';'.join(texts).strip()


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
        return component.is_real is True and component.is_finite is True

    if (all(everywhere(c) for c in (value, *item.components))
            and all(d.is_nonzero is True for d in item.denominators)):
        return True
    # Область эталона уже включает ограничения его исходных компонентов.
    # Если ввод не добавляет ни одного такого ограничения, включение
    # доказано непосредственно, без повторного решения тех же областей.
    originals = {c for original in reference.items
                 for c in (original.expression, *original.components)}
    original_denominators = {d for original in reference.items
                             for d in original.denominators}
    if (all(c in originals or everywhere(c) for c in (value, *item.components))
            and all(d in original_denominators or d.is_nonzero is True
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
        if d.is_nonzero is True or d in original_denominators:
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
    from sympy import S
    baseline = {symbol: S.One for symbol in reference.symbols}
    values_to_try = [baseline]
    if len(reference.symbols) == 1:
        symbol = reference.symbols[0]
        # Точный ноль исходного линейного знаменателя — кандидат на разрыв.
        # Он используется только для опровержения и проверяется на области
        # эталона ниже; отсутствие такого нуля ничего не доказывает.
        for denominator in item.denominators:
            polynomial = denominator.as_poly(symbol)
            if polynomial is not None and polynomial.degree() == 1:
                root = -polynomial.nth(0) / polynomial.nth(1)
                if root.is_real is True and (not symbol.is_positive or root.is_positive is True):
                    values_to_try.append({symbol: root})
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


def _check(value, reference, multiple=False, mode='expression'):
    from sympy import factor, simplify
    if len(value) > MAX_EXPR_LEN:
        return UNKNOWN
    texts = value.split(';') if multiple else [value]
    if len(texts) != len(reference.items) or any(not t.strip() for t in texts):
        return WRONG
    student = tuple(_parse(t.strip(), reference.positive) for t in texts)
    if any(item is None for item in student):
        return UNKNOWN
    allowed_symbols = set(reference.symbols)
    for item in student:
        if item.expression.free_symbols - allowed_symbols:
            return WRONG
        for component in (*item.denominators, *item.components):
            if component.free_symbols - allowed_symbols:
                return WRONG
        defined = _defined(item, reference)
        if defined is not True:
            return WRONG if defined is False else UNKNOWN
    # Сохраняем кратность: лишняя или повторная длина не заменяет другую.
    remaining = list(reference.items)
    for item in student:
        uncertain = False
        for index, expected in enumerate(remaining):
            # Полный квадрат под корнем может быть раскрыт: sqrt(x²-2x+1).
            # factor сохраняет реальный модуль, в отличие от принудительного
            # извлечения корня; исходные области уже проверены отдельно.
            difference = simplify(factor(item.expression) - factor(expected.expression))
            same = difference == 0 or difference.equals(0)
            if same is None and _counterexample(difference, reference):
                same = False
            if same is True:
                remaining.pop(index)
                break
            uncertain |= same is None
        else:
            return UNKNOWN if uncertain else WRONG
    # Равносильность уже доказана с исходными областями и предположениями.
    # Повторное сравнение без positive/π потеряло бы этот контекст. По сырому
    # дереву отдельно проверяем только требуемый вид записи.
    if mode == 'simplify':
        item = student[0]
        if (expressions.reducible(item.tree)
                or expressions._size(item.expression) > 2 * expressions._size(reference.items[0].expression) + 4):
            return WRONG
    elif mode == 'factor':
        if not expressions.fully_factored(expressions.resolve(student[0].tree)):
            return WRONG
    return OK

"""Проверки выражений для слотов маски: упрощение, разложение на множители,
уравнение.

Эквивалентность считает sympy, а «степень упрощённости» приходится смотреть
по **сырому** дереву разбора LaTeX: sympy при построении выражения сам
сокращает ``10/4`` и раскрывает ``2(x-1)`` в ``2x-2``, после чего уже не
понять, что написал ученик. Поэтому lark-парсер используется в два прохода:
``transform=False`` даёт синтаксическое дерево, а штатный трансформер
превращает любое его поддерево в sympy-выражение.

Как и в ``check_answer``, ``parse_expr``/``sympify`` не используются:
они исполняют ввод через ``eval``.
"""
import re
from fractions import Fraction
from math import gcd as int_gcd

from ..check_answer import MAX_EXPR_LEN, OK, UNKNOWN, WRONG, normalize

_parser = None
_transformer = None
_numeric_transformer = None

# Узлы lark-грамматики sympy (sympy/parsing/latex/lark/grammar/latex.lark)
_PRODUCT_NODES = ('mul', 'adjacent_expressions')
_QUOTIENT_NODES = ('div', 'fraction')
_NUMERIC_OPS = ('add', 'sub', 'mul', 'adjacent_expressions', 'superscript')

# lark-грамматика sympy не понимает соседство скобок ``)(``, ``^2(``,
# ``\sqrt{2}x`` и читает ``x(x+1)`` как вызов функции — ставим явное умножение.
# После ``}`` — кроме первого аргумента frac/binom и индекса/степени функции
# (иначе ``\log_{2}x`` и ``\sin^{2}x`` ломаются).
_IMPLICIT_MUL_RES = (
    # Числовой коэффициент перед корнем — множитель, в том числе перед /.
    re.compile(r'(?<=[0-9])\s*(?=\\sqrt(?:\[|\{))'),
    re.compile(r'(?<=\))\s*(?=\()'),
    re.compile(r'(?<=\))\s*(?=[0-9a-zA-Z])'),
    re.compile(r'(?<=\^\d)\s*(?=\()'),
    re.compile(r'(?<![\\a-zA-Z][a-zA-Z])(?<=[a-zA-Z])\s*(?=\()'),
)


def _closes_script(text, close_idx):
    """``}`` закрывает ``_{…}`` или ``^{…}`` (индекс/степень), а не ``\\sqrt{…}``."""
    depth = 0
    i = close_idx
    while i >= 0:
        char = text[i]
        if char == '}':
            depth += 1
        elif char == '{':
            depth -= 1
            if depth == 0:
                j = i - 1
                while j >= 0 and text[j].isspace():
                    j -= 1
                return j >= 0 and text[j] in '_^'
        i -= 1
    return False


def _closes_first_argument(text, close_idx):
    """Первый аргумент frac/binom: следующий токен — второй аргумент."""
    depth = 0
    for i in range(close_idx, -1, -1):
        if text[i] == '}':
            depth += 1
        elif text[i] == '{':
            depth -= 1
            if depth == 0:
                return re.search(r'\\(?:dfrac|tfrac|frac|binom)\s*$', text[:i]) is not None
    return False


def _insert_cdot_after_group(text, *, allow_script_products=False):
    """Явное умножение после группы, кроме индексов и степеней функций."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] in '})':
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if (j < n and (text[j] == '(' or text[j].isalnum()
                           or text.startswith(r'\sqrt', j))
                    and (text[i] != '}' or not _closes_first_argument(text, i))
                    and (allow_script_products or text[i] != '}'
                         or not _closes_script(text, i))):
                out.append(text[i] + '\\cdot ')
                i = j
                continue
        out.append(text[i])
        i += 1
    return ''.join(out)


def normalize_roots(text):
    """Корни sqrt(...) и односимвольные аргументы LaTeX без смены смысла."""
    if len(text) > MAX_EXPR_LEN:
        return text
    # Вложенные sqrt разбираем изнутри; никакой пользовательский код не исполняется.
    while matches := list(re.finditer(r'(?<![A-Za-z\\])sqrt\s*\(', text)):
        match = matches[-1]
        depth, end = 1, match.end()
        while end < len(text) and depth:
            depth += (text[end] == '(') - (text[end] == ')')
            end += 1
        if depth:
            break
        text = (text[:match.start()] + r'\sqrt{' + text[match.end():end-1]
                + '}' + text[end:])
    # В текстовом sqrt2 однозначен один знак; для sqrt16 нужны скобки.
    text = re.sub(r'(?<![A-Za-z\\])sqrt\s*([0-9])(?![0-9.])',
                  lambda m: r'\sqrt{' + m[1] + '}', text)
    # \sqrt12 означает sqrt(1)*2, а sqrt(12) — корень из двенадцати.
    return re.sub(r'(\\sqrt(?:\[[^\]]+\])?)\s*([0-9])', r'\1{\2}', text)


def prepare(text):
    """Нормализация школьной записи + явное умножение перед скобкой."""
    text = normalize_roots(normalize(text))
    text = _insert_cdot_after_group(text)
    def product(match):
        # Цифра завершает индекс/степень функции, а корень или скобка —
        # её аргумент. Пробелы после _/^ не меняют эту связь.
        script = re.search(
            r'\\([A-Za-z]+)\s*(?:[_^]\s*(?:[+-]?[0-9A-Za-z]|\{[^{}]+\}))+\s*$',
            text[:match.start()])
        if script and script[1] in _TRIG_NODES | {'log', 'ln', 'lg'}:
            return match[0]
        return r'\cdot '

    for rx in _IMPLICIT_MUL_RES:
        text = rx.sub(product, text)
    return text.strip()


def _bounded_odd_root(value, degree, power=1):
    """Ограничивает рост до real_root, включая вложенные степени основания."""
    from sympy import Pow, real_root
    from .numeric import MAX_BITS, MAX_DEPTH, MAX_NODES
    if not 1 <= degree <= 1000 or abs(power) > 1000 * degree:
        raise ValueError('слишком большой показатель корня или степени')
    remaining = MAX_NODES

    def bits(node, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > MAX_DEPTH:
            raise ValueError('слишком сложное основание корня')
        if node.is_Rational:
            size = max(int(node.p).bit_length(), int(node.q).bit_length(), 1)
        elif node.is_Pow:
            exponent = node.exp
            if (not exponent.is_Rational or exponent.q > 1000
                    or abs(exponent.p) > 1000 * exponent.q):
                raise ValueError('неограниченная степень в основании корня')
            size = (bits(node.base, depth + 1) * abs(exponent.p)
                    + exponent.q - 1) // exponent.q + 1
        else:
            children = [bits(child, depth + 1) for child in node.args]
            size = (max(children) + len(children).bit_length()
                    if node.is_Add and children else sum(children) or 1)
        if size > MAX_BITS:
            raise ValueError('слишком большое основание корня')
        return size

    size = bits(value)
    if size * abs(power) > MAX_BITS * degree:
        raise ValueError('слишком большая степень корня')
    root = real_root(value, degree)
    # Большая дробная степень не раскрывается в Integer при построении.
    return root if power == 1 else Pow(root, power, evaluate=False)


def _lark():
    global _parser, _transformer
    if _parser is None:
        from sympy.parsing.latex.lark import latex_parser
        # Импорт SymPy уже создаёт эту грамматику. Повторные экземпляры
        # тратят CPU при каждом запуске ограниченного вычислителя.
        _parser = getattr(latex_parser, '_lark_latex_parser', None)
        if _parser is None:
            _parser = latex_parser.LarkLaTeXParser(transform=False)
        # Десятичные числа в любом режиме точны до выполнения операций.
        # Общий трансформер SymPy не меняем: его могут использовать другие
        # модули, а восстановление дробей после Float уже теряет точность.
        class ExactTransformer(type(_parser.transformer)):
            def number(self, tokens):
                if tokens[0].type == 'CMD_IMAGINARY_UNIT':
                    return super().number(tokens)
                from sympy import Rational
                return Rational(str(tokens[0]))

            def square_root(self, tokens):
                if len(tokens) == 3:
                    degree, value = tokens[1:]
                    if (getattr(degree, 'is_Integer', False) and degree > 0
                            and degree.is_odd):
                        # Для ещё неизвестного символа сохраняется условная
                        # ветвь; вещественные предположения задаёт проверка.
                        return _bounded_odd_root(value, degree)
                return super().square_root(tokens)

            def superscript(self, tokens):
                if len(tokens) in (3, 5):
                    base = tokens[0]
                    exponent = tokens[2 if len(tokens) == 3 else 3]
                    if (getattr(exponent, 'is_Rational', False)
                            and exponent.q > 1 and exponent.q % 2):
                        return _bounded_odd_root(base, exponent.q, exponent.p)
                return super().superscript(tokens)
        _transformer = ExactTransformer()
    return _parser, _transformer


def _is_tree(node):
    return hasattr(node, 'data') and hasattr(node, 'children')


def _subtrees(node):
    return [c for c in node.children if _is_tree(c)]


def _absolute_products(text):
    """Скобки для вложенных модулей и умножение после закрывающей черты.

    Ожидаемый операнд отличает открытие модуля от закрытия. Каждый модуль
    остаётся узлом сырого дерева; соседние модули сохраняются множителями.
    """
    out, depth, operand, i = [], 0, True, 0
    groups = []
    while i < len(text):
        char = text[i]
        if char == '|':
            if operand or not depth:
                out.append('|(')
                groups.append('|')
                depth += 1
                operand = True
            else:
                if not groups or groups[-1] != '|':
                    return None
                groups.pop()
                out.append(')|')
                depth -= 1
                operand = False
                following = i + 1
                while following < len(text) and text[following].isspace():
                    following += 1
                suffix = text[following:]
                if (re.match(r'(?:[0-9a-zA-Z(]|\\(?!cdot\b|times\b|div\b|pm\b|mp\b)[A-Za-z]+)', suffix)
                        or suffix.startswith('|') and not depth):
                    out.append(r'\cdot ')
                    # После явного умножения 2b/2(b+c) разделяем на
                    # множители; существующий знак операции не дублируем.
                    coefficient = re.match(
                        r'\d+(?:\.\d+)?\s*(?=[A-Za-z(|]|\\(?!cdot\b|times\b|div\b|pm\b|mp\b)[A-Za-z]+)',
                        suffix)
                    if coefficient:
                        out.append(coefficient[0].strip() + r'\cdot ')
                        following += coefficient.end()
                    i, operand = following, True
                    continue
        elif char == '\\':
            command = re.match(r'\\([A-Za-z]+)', text[i:])
            if command:
                out.append(command[0])
                operand = command[1] in _TRIG_NODES | {
                    'cdot', 'times', 'div', 'pm', 'mp', 'frac', 'dfrac', 'tfrac',
                    'sqrt', 'log', 'ln', 'lg'}
                i += command.end()
                continue
            out.append(char)
        else:
            # Вставленные скобки не должны исправлять ошибочный ввод:
            # группы нельзя закрывать через границу открытого модуля.
            if char in '({[':
                groups.append(char)
            elif char in ')}]':
                if not groups or groups[-1] != {')': '(', '}': '{', ']': '['}[char]:
                    return None
                groups.pop()
            out.append(char)
            if char in '+-*/^_({[':
                operand = True
            elif char in ')}]' or char.isalnum() or char == '.':
                operand = False
        i += 1
    return None if depth or groups else ''.join(out)


def raw_tree(text):
    """Сырое дерево разбора подготовленной строки; None — не разобралось."""
    text = prepare(text)
    if not text or len(text) > MAX_EXPR_LEN:
        return None
    parser, _ = _lark()
    try:
        # Сырое дерево нужно независимо от transform_expr общего парсера.
        # Его настройки не меняем: им пользуется и parse_latex SymPy.
        try:
            return parser.parser.parse(text)
        except MemoryError:
            raise
        except Exception:
            # Исходные корректные деревья и аргументы функций не меняем.
            # Нормализация добавляет только скобки и знаки умножения.
            grouped = _absolute_products(text) if '|' in text else None
            if grouped is None or grouped == text:
                raise
            return parser.parser.parse(grouped)
    except MemoryError:
        raise
    except Exception as error:  # noqa: BLE001 — синтаксический сбой = «не разобрано»
        if isinstance(getattr(error, 'orig_exc', None), MemoryError):
            raise error.orig_exc from error
        return None


def _has_undefined_functions(expr):
    from sympy.core.function import AppliedUndef
    return hasattr(expr, 'atoms') and bool(expr.atoms(AppliedUndef))


# Скобки функции задают весь её аргумент. Операция за закрывающей
# скобкой и следующая самостоятельная функция относятся к внешнему выражению.
_TRIG_NODES = frozenset((
    'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
    'arcsin', 'arccos', 'arctan', 'arccot', 'arcsec', 'arccsc',
    'sinh', 'cosh', 'tanh', 'asinh', 'acosh', 'atanh',
))
_FUNCTION_GROUPS = ('group_round_parentheses', 'group_curly_parentheses',
                    'group_square_brackets')


def _starts_with_group(node):
    """Явно сгруппированный аргумент нельзя расширить операцией после группы."""
    if not _is_tree(node):
        return False
    if node.data in _FUNCTION_GROUPS:
        return True
    if node.data in ('mul', 'div', 'add', 'sub', 'adjacent_expressions', 'superscript'):
        return bool(node.children) and _starts_with_group(node.children[0])
    return False


def _contains_trig(node):
    return (_is_tree(node) and
            (node.data in _TRIG_NODES or str(node.data).removesuffix('_power') in _TRIG_NODES
             or any(_contains_trig(c) for c in node.children)))


def _valid_function_scopes(node):
    """Отсекает альтернативы Lark, поглотившие внешний множитель или делитель."""
    if not _is_tree(node):
        return True
    kind = str(node.data)
    if kind in _TRIG_NODES or kind.removesuffix('_power') in _TRIG_NODES:
        argument = node.children[-1]
        if _is_tree(argument) and argument.data not in _FUNCTION_GROUPS:
            if _starts_with_group(argument):
                return False
            if argument.data in ('mul', 'div', 'add'):
                return False
            if argument.data == 'sub' and len(argument.children) > 2:
                return False
            if argument.data == 'adjacent_expressions' and _contains_trig(argument):
                return False
    if node.data == 'superscript':
        base = node.children[0]
        # sin x² = sin(x²); для квадрата синуса пишут sin² x или sin(x)².
        if (_is_tree(base) and base.data in _TRIG_NODES
                and not (_is_tree(base.children[-1])
                         and base.children[-1].data in _FUNCTION_GROUPS)):
            return False
    return all(_valid_function_scopes(c) for c in node.children)


def resolve(tree):
    """Выбирает произведение вместо неизвестной функции и сохраняет границы
    аргументов тригонометрических функций. Если допустимого разбора нет,
    возвращает None: неверный смысл нельзя использовать для оценки ответа."""
    if not _is_tree(tree):
        return tree
    if tree.data == '_ambig':
        candidates = [resolve(c) for c in tree.children]
        candidates = [c for c in candidates if c is not None]
        for cand in candidates:
            try:
                if not _has_undefined_functions(evaluate(cand)):
                    return cand
            except MemoryError:
                raise
            except Exception:  # noqa: BLE001
                continue
        return candidates[0] if candidates else None
    children = [resolve(c) for c in tree.children]
    if any(c is None for c in children):
        return None
    result = tree.__class__(tree.data, children)
    return result if _valid_function_scopes(result) else None


def evaluate(tree, *, numeric=False, pi_marker=None):
    """Поддерево → sympy-выражение (или None)."""
    if tree is None:
        return None
    _, transformer = _lark()
    if numeric:
        global _numeric_transformer
        if _numeric_transformer is None:
            # Числовой режим узнаёт константу π до операций;
            # школьные нечётные корни наследуются от точного трансформера.
            class NumericTransformer(type(transformer)):
                def __init__(self, pi_marker=None):
                    super().__init__()
                    self.pi_marker = pi_marker

                def SYMBOL(self, token):
                    from sympy import Symbol, pi
                    # Константа известна до вычисления корней и степеней,
                    # а пользовательские переменные остаются символами.
                    return pi if str(token) == self.pi_marker else Symbol(str(token))

            _numeric_transformer = NumericTransformer()
        transformer = (_numeric_transformer.__class__(pi_marker=pi_marker)
                       if pi_marker else _numeric_transformer)
    try:
        result = transformer.transform(tree)
    except MemoryError:
        raise
    except Exception as error:  # noqa: BLE001
        if isinstance(getattr(error, 'orig_exc', None), MemoryError):
            raise error.orig_exc from error
        return None
    if _is_tree(result):
        return None
    return result


def parse(text):
    """Строка → (сырое дерево со всеми альтернативами, sympy-выражение
    по выбранной альтернативе)."""
    tree = raw_tree(text)
    if tree is None:
        return None, None
    return tree, evaluate(resolve(tree))


def parse_expr(text):
    """Только sympy-выражение (для эталонов и простых проверок)."""
    return parse(text)[1]


def _rational(expr):
    """Float'ы → рациональные: gcd и factor_list работают точно."""
    from sympy import nsimplify
    try:
        return nsimplify(expr, rational=True)
    except Exception:  # noqa: BLE001
        return expr


def equal(a, b):
    """Численная эквивалентность (см. ``check_answer._sympy_equal``)."""
    from ..check_answer import _sympy_equal
    return _sympy_equal(a, b)


# --- анализ сырого дерева ---------------------------------------------------

def _unwrap(node):
    """Снять ``latex_string`` и фигурные скобки ``{…}`` (аргумент \\frac)."""
    while _is_tree(node) and node.data in (
            'latex_string', 'group_curly_parentheses') and len(_subtrees(node)) == 1:
        node = _subtrees(node)[0]
    return node


def _is_unary_minus(node):
    return _is_tree(node) and node.data == 'sub' and len(_subtrees(node)) == 1


def _number_value(node):
    """Литерал числа (или ``-число``, ``(число)``) → Fraction, иначе None."""
    node = _unwrap(node)
    if not _is_tree(node):
        return None
    if node.data == 'number':
        try:
            return Fraction(str(node.children[0]))
        except (ValueError, ArithmeticError):
            return None
    if _is_unary_minus(node):
        value = _number_value(_subtrees(node)[0])
        return None if value is None else -value
    if node.data == 'group_round_parentheses' and len(_subtrees(node)) == 1:
        return _number_value(_subtrees(node)[0])
    return None


def _is_symbol_token(child):
    """Переменная-лист (``x``, ``a_1``, греческая буква) — токен, не дерево."""
    kind = getattr(child, 'type', '')
    return 'SYMBOL' in kind and kind not in ('MUL_SYMBOL', 'DIV_SYMBOL')


def _all_numeric(node):
    """Все листья поддерева — числа (нет символов и функций)."""
    node = _unwrap(node)
    if not _is_tree(node):
        return False
    if node.data == 'number':
        return True
    if node.data == '_ambig':
        return any(_all_numeric(c) for c in node.children)
    if any(_is_symbol_token(c) for c in node.children):
        return False
    if node.data in _NUMERIC_OPS + _QUOTIENT_NODES + (
            'group_round_parentheses', 'square_root', 'group_curly_parentheses'):
        subs = _subtrees(node)
        return bool(subs) and all(_all_numeric(c) for c in subs)
    return False


def _chain_literals(node, nums, dens, inverted=False):
    """Числовые литералы цепочки умножений/делений: в числитель или в
    знаменатель. В суммы, степени и скобки не заходим."""
    node = _unwrap(node)
    if not _is_tree(node):
        return
    if node.data == '_ambig':
        _chain_literals(node.children[0], nums, dens, inverted)
    elif node.data in _PRODUCT_NODES:
        for child in _subtrees(node):
            _chain_literals(child, nums, dens, inverted)
    elif node.data in _QUOTIENT_NODES:
        subs = _subtrees(node)
        if len(subs) == 2:
            _chain_literals(subs[0], nums, dens, inverted)
            _chain_literals(subs[1], nums, dens, not inverted)
    elif _is_unary_minus(node):
        _chain_literals(_subtrees(node)[0], nums, dens, inverted)
    elif node.data == 'number':
        value = _number_value(node)
        if value is not None:
            (dens if inverted else nums).append(value)


def _literals_reducible(nums, dens):
    nums = [n for n in nums if n != 1]
    if len(nums) > 1 or len(dens) > 1:
        return True
    ints = [int(v) for v in nums + dens if v.denominator == 1]
    if nums and dens and len(ints) == len(nums) + len(dens):
        g = 0
        for v in ints:
            g = int_gcd(g, abs(v))
        return g > 1
    return False


def _quotient_reducible(node):
    """У дроби числитель и знаменатель имеют общий множитель
    (числовой или многочленный) либо знаменатель равен ±1."""
    from sympy import gcd
    # Листья a/a и a/1 — токены, а не поддеревья. Их нельзя терять.
    subs = [c for c in node.children if _is_tree(c) or _is_symbol_token(c)
            or getattr(c, 'type', '') == 'DIGIT']
    if len(subs) != 2:
        return False
    def operand(child):
        return evaluate(resolve(child)) if _is_tree(child) else parse_expr(str(child))
    num, den = map(operand, subs)
    if num is None or den is None:
        return False
    try:
        num, den = _rational(num), _rational(den)
        if den in (1, -1):
            return True
        g = gcd(num, den)
        return g not in (1, -1)
    except Exception:  # noqa: BLE001
        return False


def _sum_terms(node, out):
    """Слагаемые цепочки сложений/вычитаний (унарный минус — часть слагаемого)."""
    node = _unwrap(node)
    if _is_tree(node) and node.data in ('add', 'sub') and not _is_unary_minus(node):
        for child in node.children:
            if _is_tree(child) or _is_symbol_token(child):
                _sum_terms(child, out)
    else:
        out.append(node)


def _has_like_terms(node):
    """После вычисления слагаемых стало меньше — были подобные (``x+2x``)."""
    from sympy import Add
    raw = []
    _sum_terms(node, raw)
    if len(raw) < 2:
        return False
    expr = evaluate(resolve(node))
    if expr is None or not hasattr(expr, 'args'):
        return False
    try:
        return len(Add.make_args(expr)) < len(raw)
    except Exception:  # noqa: BLE001
        return False


def _perfect_square_root(node):
    subs = _subtrees(node)
    if len(subs) != 1:
        return False
    value = _number_value(subs[0])
    if value is None or value < 0 or value.denominator != 1:
        return False
    root = int(value.numerator ** 0.5)
    return root * root == value.numerator


def reducible(node):
    """В записи есть невыполненное числовое действие или сокращаемая дробь."""
    if not _is_tree(node):
        return False
    if node.data == '_ambig':
        return any(reducible(c) for c in node.children)
    if node.data in _NUMERIC_OPS and not _is_unary_minus(node) \
            and _all_numeric(node):
        return True
    if node.data == 'square_root' and _perfect_square_root(node):
        return True
    if node.data == 'superscript':
        operands = [c for c in node.children if _is_tree(c) or _is_symbol_token(c)
                    or getattr(c, 'type', '') == 'DIGIT']
        if len(operands) == 2:
            child = operands[1]
            exponent = evaluate(resolve(child)) if _is_tree(child) else parse_expr(str(child))
            if getattr(exponent, 'is_zero', None) is True:
                return True
    if node.data in ('add', 'sub') and not _is_unary_minus(node) \
            and _has_like_terms(node):
        return True
    if node.data in _PRODUCT_NODES + _QUOTIENT_NODES:
        nums, dens = [], []
        _chain_literals(node, nums, dens)
        if _literals_reducible(nums, dens):
            return True
    if node.data in _QUOTIENT_NODES and _quotient_reducible(node):
        return True
    return any(reducible(c) for c in _subtrees(node))


def _product_factors(node, out):
    """Множители верхнего уровня произведения (сквозь унарный минус)."""
    node = _unwrap(node)
    if not _is_tree(node):
        if _is_symbol_token(node):
            out.append(node)
        return
    if node.data in _PRODUCT_NODES:
        for child in node.children:
            if not (_is_tree(child) or _is_symbol_token(child)):
                continue
            _product_factors(child, out)
    elif _is_unary_minus(node):
        _product_factors(_subtrees(node)[0], out)
    else:
        out.append(node)


def _factor_ok(node):
    """Множитель — неприводимый многочлен (в целой степени) с содержанием
    ±1: ``(x-1)``, ``(x+1)^2``, ``x``, ``x^2``; ``(2x-4)`` — нет.
    Основание степени берём из sympy-выражения: у ``x^2`` в сыром дереве
    переменная — токен, и ``_subtrees()`` её отбрасывает."""
    from sympy import Pow, factor_list
    node = _unwrap(node)
    expr = evaluate(resolve(node)) if _is_tree(node) else parse_expr(str(node))
    if expr is None:
        return False
    while isinstance(expr, Pow) and expr.exp.is_integer and expr.exp > 0:
        expr = expr.base
    if not expr.free_symbols:
        return False
    try:
        content, factors = factor_list(_rational(expr))
        return content in (1, -1) and len(factors) == 1 and factors[0][1] == 1
    except Exception:  # noqa: BLE001
        return False


def fully_factored(tree):
    """Произведение не более чем одного числа и неприводимых множителей."""
    factors = []
    _product_factors(tree, factors)
    numbers = 0
    for node in factors:
        if _all_numeric(node):
            numbers += 1
            if numbers > 1 or reducible(node):
                return False
        elif not _factor_ok(node):
            return False
    return bool(factors)


# --- проверки слотов --------------------------------------------------------

def _size(expr):
    from sympy import count_ops
    try:
        return int(count_ops(expr))
    except Exception:  # noqa: BLE001
        return 0


def check_simplified(student, reference):
    """Эквивалентно эталону и не менее упрощено: без невыполненных числовых
    действий, сокращаемых дробей и без лишних множителей."""
    from sympy import Expr
    tree, expr = parse(student)
    if tree is None or not isinstance(expr, Expr):
        return UNKNOWN
    if not isinstance(reference, Expr):
        return UNKNOWN
    same = equal(expr, reference)
    if same is None:
        return UNKNOWN
    if not same:
        return WRONG
    if reducible(tree):
        return WRONG
    if _size(expr) > 2 * _size(reference) + 4:
        return WRONG
    return OK


def check_factored(student, reference):
    """Эквивалентно эталону и записано как произведение неприводимых
    множителей с одним числовым коэффициентом."""
    from sympy import Expr, expand
    tree, expr = parse(student)
    if tree is None or not isinstance(expr, Expr):
        return UNKNOWN
    if not isinstance(reference, Expr):
        return UNKNOWN
    try:
        diff = expand(_rational(expr) - _rational(reference))
    except Exception:  # noqa: BLE001
        return UNKNOWN
    if diff != 0:
        same = equal(expr, reference)
        if same is None:
            return UNKNOWN
        if not same:
            return WRONG
    return OK if fully_factored(resolve(tree)) else WRONG


def _terms(side):
    try:
        return set(side.as_coefficients_dict().keys()) if side != 0 else set()
    except Exception:  # noqa: BLE001
        return set()


def check_equation(student, reference, *, strict=False):
    """Уравнение, равносильное эталону: разности сторон пропорциональны с
    ненулевым числовым множителем (``y=x+5``, ``y-x=5``, ``2y=2x+10``,
    ``x=y-5``, ``y-2=x+3``). В строгом режиме (``| strict``) — приведённый
    вид: буквально ``±`` эталон (``2y=2x+10`` — нет) и ни одно слагаемое не
    повторяется в обеих частях (``y-2=x+3`` — нет)."""
    from sympy import Eq, cancel, expand
    _, expr = parse(student)
    if not isinstance(expr, Eq) or not isinstance(reference, Eq):
        return UNKNOWN
    try:
        lhs, rhs = _rational(expr.lhs), _rational(expr.rhs)
        ds = expand(lhs - rhs)
        dr = expand(_rational(reference.lhs) - _rational(reference.rhs))
        if ds == 0 or dr == 0:
            return UNKNOWN
        if ds != dr and ds != -dr:
            ratio = cancel(ds / dr)
            if ratio.is_number:
                # Пропорциональная запись той же линии/кривой: 2x-6y=4 для x-3y=2.
                return WRONG if strict or ratio == 0 else OK
            same = equal(ds, dr)
            if same is False:
                same = equal(ds, -dr)
            if same is None:
                return UNKNOWN
            if not same:
                return WRONG
        if strict and _terms(expand(lhs)) & _terms(expand(rhs)):
            return WRONG
    except Exception:  # noqa: BLE001
        return UNKNOWN
    return OK

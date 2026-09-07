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

# Узлы lark-грамматики sympy (sympy/parsing/latex/lark/grammar/latex.lark)
_PRODUCT_NODES = ('mul', 'adjacent_expressions')
_QUOTIENT_NODES = ('div', 'fraction')
_NUMERIC_OPS = ('add', 'sub', 'mul', 'adjacent_expressions', 'superscript')

# lark-грамматика sympy не понимает соседство скобок ``)(``, ``^2(``,
# ``\sqrt{2}x`` и читает ``x(x+1)`` как вызов функции — ставим явное умножение.
# После ``}`` — только если это не индекс/степень ``_{…}`` / ``^{…}``
# (иначе ``\log_{2}x`` и ``\sin^{2}x`` ломаются).
_IMPLICIT_MUL_RES = (
    re.compile(r'(?<=\))\s*(?=\()'),
    re.compile(r'(?<=\))\s*(?=\d)'),
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


def _insert_cdot_after_group(text):
    """``}x`` / ``}(`` → ``}\\cdot ``, кроме индексов и степеней."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == '}':
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if (j < n and (text[j] == '(' or text[j].isalpha())
                    and not _closes_script(text, i)):
                out.append('}\\cdot ')
                i = j
                continue
        out.append(text[i])
        i += 1
    return ''.join(out)


def prepare(text):
    """Нормализация школьной записи + явное умножение перед скобкой."""
    text = normalize(text)
    text = _insert_cdot_after_group(text)
    for rx in _IMPLICIT_MUL_RES:
        text = rx.sub(r'\\cdot ', text)
    return text.strip()


def _lark():
    global _parser, _transformer
    if _parser is None:
        from sympy.parsing.latex.lark import LarkLaTeXParser
        _parser = LarkLaTeXParser(transform=False)
        _transformer = LarkLaTeXParser().transformer
    return _parser, _transformer


def _is_tree(node):
    return hasattr(node, 'data') and hasattr(node, 'children')


def _subtrees(node):
    return [c for c in node.children if _is_tree(c)]


def raw_tree(text):
    """Сырое дерево разбора подготовленной строки; None — не разобралось."""
    text = prepare(text)
    if not text or len(text) > MAX_EXPR_LEN:
        return None
    parser, _ = _lark()
    try:
        return parser.doparse(text)
    except Exception:  # noqa: BLE001 — любой сбой парсера = «не разобрано»
        return None


def _has_undefined_functions(expr):
    from sympy.core.function import AppliedUndef
    return hasattr(expr, 'atoms') and bool(expr.atoms(AppliedUndef))


def resolve(tree):
    """Копия дерева без узлов ``_ambig``: из альтернатив предпочитается та,
    где ``x(x+1)`` прочитано как произведение, а не как вызов функции ``x``."""
    if not _is_tree(tree):
        return tree
    if tree.data == '_ambig':
        candidates = [resolve(c) for c in tree.children]
        for cand in candidates:
            try:
                if not _has_undefined_functions(evaluate(cand)):
                    return cand
            except Exception:  # noqa: BLE001
                continue
        return candidates[0]
    return tree.__class__(tree.data, [resolve(c) for c in tree.children])


def evaluate(tree):
    """Поддерево → sympy-выражение (или None)."""
    if tree is None:
        return None
    _, transformer = _lark()
    try:
        result = transformer.transform(tree)
    except Exception:  # noqa: BLE001
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
    subs = _subtrees(node)
    if len(subs) != 2:
        return False
    num = evaluate(resolve(subs[0]))
    den = evaluate(resolve(subs[1]))
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
        return
    if node.data in _PRODUCT_NODES:
        for child in _subtrees(node):
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
    expr = evaluate(resolve(node))
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


def check_equation(student, reference):
    """Уравнение в приведённом виде: ``y=x+5`` и ``y-x=5`` равносильны
    эталону буквально (не пропорционально: ``2y=2x+10`` — нет), и ни одно
    слагаемое не повторяется в обеих частях (``y-2=x+3`` — нет)."""
    from sympy import Eq, expand
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
            ratio = (ds / dr)
            if ratio.is_number:
                return WRONG
            same = equal(ds, dr)
            if same is False:
                same = equal(ds, -dr)
            if same is None:
                return UNKNOWN
            if not same:
                return WRONG
        if _terms(expand(lhs)) & _terms(expand(rhs)):
            return WRONG
    except Exception:  # noqa: BLE001
        return UNKNOWN
    return OK

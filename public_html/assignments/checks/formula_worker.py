"""Ограниченный по времени процесс символьной проверки; протокол JSON."""
import json
import os
import sys

# Процессорное время ребёнка, секунды: мягкий лимит (SIGXCPU) и жёсткий.
CPU_LIMIT = (2, 3)
# Тестовый раннер (core/runner.py) поднимает лимит через окружение: на
# загруженном CI-раннере та же эквивалентность тратит больше процессора.
# На проде переменной нет, и действует CPU_LIMIT.
TEST_CPU_LIMIT_ENV = 'FORMULA_TEST_CPU_LIMIT'
# Деревья разбора эталона (expressions.tree_to_data), символов JSON: у
# формулы в 150 символов — около 3 тысяч. Больше лимита — не отдаём:
# следующий вызов разберёт эталон сам, как раньше.
TREES_LIMIT = 64_000
# Expr.equals, simplify и порядок проверки допущений в SymPy берут случайные
# числа из общего генератора sympy.core.random. Без зерна один и тот же ответ
# получал в разных процессах разные вердикты и разную стоимость (при одном
# из зёрен — больше 25 с на одной формуле). Зерно задаётся заново в каждом
# вызове и выбрано по замеру: на тяжёлых тестах и корпусе оно не попадает
# в медленный путь.
SYMPY_SEED = 4
# Порядок обхода множеств в SymPy зависит от хэшей строк, то есть от
# PYTHONHASHSEED. Вычислитель запускается с этим значением (formulas._spawn,
# formula_fork); сам веб-процесс остаётся со случайным зерном хэшей.
HASH_SEED = '0'


def _cpu_limit():
    soft = os.environ.get(TEST_CPU_LIMIT_ENV, '')
    if soft.isdigit() and int(soft) > CPU_LIMIT[0]:
        return int(soft), int(soft) + 1
    return CPU_LIMIT


def _load_trees(text):
    """Готовые деревья эталона из прошлой проверки этого же эталона.

    Их построил ребёнок, разбиравший только эталон учителя; память
    разборов — по тексту, поэтому совпавший с эталоном ввод ученика
    получает то же дерево, что дал бы разбор. Испорченные данные
    отбрасываются целиком, и эталон разбирается заново.
    """
    from . import expressions
    if not isinstance(text, str):
        return
    try:
        trees = json.loads(text)
        if not isinstance(trees, dict):
            raise ValueError('ожидается словарь деревьев')
        loaded = {key: expressions.tree_from_data(value) for key, value in trees.items()}
    except (ValueError, TypeError, RecursionError):
        return
    expressions._resolved_trees.update(loaded)


def _export_trees():
    """Деревья, разобранные при проверке эталона, для следующих вызовов."""
    from . import expressions
    try:
        text = json.dumps({key: expressions.tree_to_data(tree)
                           for key, tree in expressions._resolved_trees.items()},
                          separators=(',', ':'))
    except (ValueError, TypeError, RecursionError):
        return None
    return text if len(text) <= TREES_LIMIT else None


def main():
    # На Linux дополнительно ограничиваем память и процессорное время.
    # На macOS память виртуального процесса включает системные библиотеки.
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, _cpu_limit())
    from sympy.core.random import seed
    seed(SYMPY_SEED)
    from . import expressions
    # Память разборов — на один вызов; тесты запускают main() в своём
    # процессе, поэтому после вызова она снова выключается.
    expressions._resolved_trees = {}
    try:
        _calculate()
    finally:
        expressions._resolved_trees = None


def _calculate():
    from .formulas import _parse_reference, _check
    from ..check_answer import MAX_EXPR_LEN
    from .sets import MAX_COLLECTION_LEN
    try:
        # JSON экранирует символы как \\uXXXX: запас на два поля и метаданные;
        # деревья эталона внутри строки JSON экранируются ещё раз.
        data = json.loads(sys.stdin.read(16 * MAX_COLLECTION_LEN + 1024 + 2 * TREES_LIMIT))
        _load_trees(data.get('trees'))
        mode = data.get('mode', 'expression')
        numeric = data.get('numeric', False)
        if mode in ('set', 'pair', 'pair-unordered', 'range'):
            if numeric is not True or data['multiple']:
                raise ValueError('числовая коллекция проверяется в отдельном режиме')
            from .numeric_collections import check
            kind = {'set': 'set', 'range': 'range'}.get(mode, 'pair')
            result = {'display': data['payload']}
            if 'value' not in data:
                # Сохранение эталона проверяет весь путь сравнения,
                # включая исходные области и стоимость коллекции.
                if check(data['payload'], data['payload'], kind=kind,
                         unordered=mode == 'pair-unordered') != 'ok':
                    raise ValueError('эталон коллекции не прошёл проверку')
                result['trees'] = _export_trees()
            if 'value' in data:
                result['status'] = check(data['value'], data['payload'], kind=kind,
                                       unordered=mode == 'pair-unordered')
            print(json.dumps(result))
            return
        if mode == 'equation':
            if numeric is not False or data['multiple']:
                raise ValueError('уравнение проверяется в отдельном режиме')
            from sympy import Eq
            from .expressions import check_equation, parse_expr
            reference = parse_expr(data['payload'])
            if not isinstance(reference, Eq):
                raise ValueError('эталон должен быть уравнением с «=»')
            result = {'display': data['payload']}
            if 'value' in data:
                result['status'] = check_equation(data['value'], reference,
                                                  strict=data.get('strict') is True)
            else:
                result['trees'] = _export_trees()
            print(json.dumps(result))
            return
        if not isinstance(numeric, bool) or (numeric and (data['multiple'] or mode != 'expression')):
            raise ValueError('числовая проверка поддерживает одно выражение')
        if mode not in ('expression', 'simplify', 'factor') or (data['multiple'] and mode != 'expression'):
            raise ValueError('неизвестный режим проверки формулы')
        if 'tolerance' in data:
            if numeric is not True or not isinstance(data['tolerance'], str):
                raise ValueError('допуск поддерживается только для числового ответа')
            from .numeric_collections import check_number_with_tolerance
            result = {'display': data['payload']}
            if 'value' in data:
                result['status'] = check_number_with_tolerance(
                    data['value'], data['payload'], data['tolerance'])
            print(json.dumps(result))
            return
        reference, display = _parse_reference(data['payload'], data['multiple'], numeric=numeric)
        if numeric and (reference.input_symbols or reference.positive or reference.substitutions):
            raise ValueError('числовой эталон не должен содержать параметры')
        if reference.substitutions and mode != 'expression':
            raise ValueError('domain поддерживается только для expression')
        result = {'display': display}
        if 'value' in data:
            result['status'] = _check(data['value'], reference, data['multiple'], mode, numeric=numeric)
        else:
            result['trees'] = _export_trees()
    except MemoryError:
        result = {'unavailable': True}
    except Exception as error:
        result = {'error': str(error) or type(error).__name__}
    print(json.dumps(result))


if __name__ == '__main__':
    main()

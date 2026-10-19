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


def _cpu_limit():
    soft = os.environ.get(TEST_CPU_LIMIT_ENV, '')
    if soft.isdigit() and int(soft) > CPU_LIMIT[0]:
        return int(soft), int(soft) + 1
    return CPU_LIMIT


def main():
    # На Linux дополнительно ограничиваем память и процессорное время.
    # На macOS память виртуального процесса включает системные библиотеки.
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, _cpu_limit())
    from .formulas import _parse_reference, _check
    from ..check_answer import MAX_EXPR_LEN
    from .sets import MAX_COLLECTION_LEN
    try:
        # JSON экранирует символы как \\uXXXX: запас на два поля и метаданные.
        data = json.loads(sys.stdin.read(16 * MAX_COLLECTION_LEN + 1024))
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
            if 'value' in data:
                result['status'] = check(data['value'], data['payload'], kind=kind,
                                       unordered=mode == 'pair-unordered')
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
    except MemoryError:
        result = {'unavailable': True}
    except Exception as error:
        result = {'error': str(error) or type(error).__name__}
    print(json.dumps(result))


if __name__ == '__main__':
    main()

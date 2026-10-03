"""Ограниченный по времени процесс символьной проверки; протокол JSON."""
import json
import sys


def main():
    # На Linux дополнительно ограничиваем память и процессорное время.
    # На macOS память виртуального процесса включает системные библиотеки.
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
    from .formulas import _parse_reference, _check
    from ..check_answer import MAX_EXPR_LEN
    try:
        # JSON экранирует символы как \\uXXXX: запас на два поля и метаданные.
        data = json.loads(sys.stdin.read(16 * MAX_EXPR_LEN + 1024))
        mode = data.get('mode', 'expression')
        if mode not in ('expression', 'simplify', 'factor') or (data['multiple'] and mode != 'expression'):
            raise ValueError('неизвестный режим проверки формулы')
        reference, display = _parse_reference(data['payload'], data['multiple'])
        if reference.substitutions and mode != 'expression':
            raise ValueError('domain поддерживается только для expression')
        result = {'display': display}
        if 'value' in data:
            result['status'] = _check(data['value'], reference, data['multiple'], mode)
    except MemoryError:
        result = {'unavailable': True}
    except Exception as error:
        result = {'error': str(error) or type(error).__name__}
    print(json.dumps(result))


if __name__ == '__main__':
    main()

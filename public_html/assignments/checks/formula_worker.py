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
        reference, display = _parse_reference(data['payload'], data['multiple'])
        result = {'display': display}
        if 'value' in data:
            result['status'] = _check(data['value'], reference, data['multiple'])
    except Exception as error:
        result = {'error': str(error)}
    print(json.dumps(result))


if __name__ == '__main__':
    main()

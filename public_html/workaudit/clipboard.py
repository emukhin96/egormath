"""Режимы копирования условий: общий список для заданий и самостоятельных."""

CLIPBOARD_WATCH = 'watch'
CLIPBOARD_SWAP = 'swap'
CLIPBOARD_BLOCK = 'block'
CLIPBOARD_CHOICES = [
    (CLIPBOARD_WATCH, 'Разрешить и записывать в журнал'),
    (CLIPBOARD_SWAP, 'Разрешить, но подменять числа в скопированном'),
    (CLIPBOARD_BLOCK, 'Запретить копирование условий и вставку ответов'),
]

# Доля условия (в процентах), с которой копирование считается «целиком»:
# выделение мышью часто теряет последнюю точку или номер задачи.
WHOLE_SHARE = 90
# Сколько символов скопированного текста хранить в журнале.
TEXT_LIMIT = 2000


def parse_mode(value):
    """Значение из POST → известный режим, по умолчанию — запись в журнал."""
    return value if value in dict(CLIPBOARD_CHOICES) else CLIPBOARD_WATCH

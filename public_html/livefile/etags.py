"""Сравнение ETag с учётом правок Apache.

``mod_deflate`` при сжатии дописывает к ETag ответа суффикс ``-gzip``,
и браузер возвращает его в ``If-None-Match`` уже с суффиксом. Прямое
сравнение строк никогда не совпадает — и все опросы получают полный
ответ вместо 304. Здесь суффикс и слабый префикс ``W/`` отбрасываются.
"""

SUFFIXES = ('-gzip', '-br', '-deflate')


def normalize(value):
    value = value.strip()
    if value.startswith('W/'):
        value = value[2:]
    for suffix in SUFFIXES:
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            break
    return value


def matches(request, etag):
    """True, если ``If-None-Match`` запроса содержит этот ETag."""
    header = request.headers.get('If-None-Match', '')
    if not header:
        return False
    if header.strip() == '*':
        return True
    wanted = normalize(etag)
    return any(normalize(candidate) == wanted for candidate in header.split(','))

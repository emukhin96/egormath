"""Сравнение ETag с учётом правок Apache и Caddy.

``mod_deflate`` при сжатии дописывает к ETag ответа суффикс ``-gzip``,
и браузер возвращает его в ``If-None-Match`` уже с суффиксом. Прямое
сравнение строк никогда не совпадает — и все опросы получают полный
ответ вместо 304. Caddy на VPS (``encode zstd gzip``) делает то же самое
с суффиксами ``-gzip`` и ``-zstd``, но внутри кавычек. Здесь суффикс
и слабый префикс ``W/`` отбрасываются.
"""

SUFFIXES = ('-gzip', '-br', '-deflate', '-zstd')


def normalize(value):
    value = value.strip()
    if value.startswith('W/'):
        value = value[2:]
    for suffix in SUFFIXES:
        if value.endswith(suffix):  # Apache: "abc"-gzip
            value = value[:-len(suffix)]
            break
        if value.endswith(suffix + '"'):  # Caddy: "abc-zstd"
            value = value[:-len(suffix) - 1] + '"'
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

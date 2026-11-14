"""gunicorn для egormath на VPS (контейнер egormath-web).

gthread: ожидание LaTeX API (до 120 с) и Gemini занимает поток, а не
процесс, и не блокирует остальные запросы. Порт наружу не публикуется —
к нему ходит только egormath-front внутри docker-сетей.

Прогрев. Первый запрос к свежему воркеру стоил 1,2–2,2 с на проде
(план аудита, docs/PERF_AUDIT_2026-11.md, раздел 10): Django поднимается,
импортируется sympy, строится грамматика Earley вычислителя масок, с
пустого файлового кэша собираются справочник рубрикатора и дерево
подборок. Поэтому приложение загружается в мастере один раз
(preload_app), тяжёлые модули импортируются там же до fork — воркеры
получают их готовыми, — а то, что требует базы, каждый воркер делает
сразу после старта, до первого запроса. GUNICORN_WARMUP=0 отключает
прогрев (диагностика).
"""
import os

bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8000')
worker_class = 'gthread'
workers = int(os.environ.get('GUNICORN_WORKERS', '2'))
threads = int(os.environ.get('GUNICORN_THREADS', '4'))

# LATEX_API_TIMEOUT = 120 с плюс запас; дольше — значит, что-то зависло.
timeout = 180
graceful_timeout = 30
keepalive = 5

# Перезапуск воркеров время от времени — страховка от утечек памяти.
# Реже, чем раньше (2000): каждый перезапуск — это прогрев и холодные
# lru_cache вычислителя; за день сайт делает порядка 5–10 тысяч запросов.
max_requests = 10000
max_requests_jitter = 1000

# Приложение загружается один раз в мастере, воркеры наследуют его через
# fork: экономит память и время старта. Соединения с MySQL в мастере не
# открываются (прогрев с базой — только в воркере, см. post_worker_init).
preload_app = True

# Заголовкам X-Forwarded-* доверяем: снаружи порт недоступен.
forwarded_allow_ips = '*'

accesslog = '-'
errorlog = '-'
# Адрес посетителя — из X-Forwarded-For: сам запрос приходит от
# egormath-front (172.x). Первый адрес в списке — клиент, дальше прокси.
# %(M)s — время ответа в миллисекундах.
access_log_format = '%({x-forwarded-for}i)s "%(r)s" %(s)s %(b)s %(M)sms'

WARMUP = os.environ.get('GUNICORN_WARMUP', '1') != '0'


def _log(server_or_worker, message):
    log = getattr(server_or_worker, 'log', None)
    if log is not None:
        log.info(message)


def when_ready(server):
    """Мастер, до fork воркеров: всё, что не трогает базу.

    sympy и lark импортируются один раз; грамматика Earley строится один
    раз; первый разбор маски прогревает lru_cache вычислителя — всё это
    воркеры наследуют готовым."""
    if not WARMUP:
        return
    import time
    started = time.perf_counter()
    try:
        from core.warmup import warm_process
        warm_process()
    except Exception as exc:  # noqa: BLE001 — прогрев не должен мешать старту
        _log(server, f'warmup (master) skipped: {exc!r}')
        return
    _log(server, f'warmup (master): {time.perf_counter() - started:.2f}s')


def post_worker_init(worker):
    """Воркер, до первого запроса: справочники из базы в файловый кэш.

    После деплоя кэш пуст (deploy.sh сбрасывает его намеренно), и первый
    посетитель платил за каталог рубрикатора и дерево подборок. Соединение
    с базой закрывается: запросы обслуживают потоки со своими."""
    if not WARMUP:
        return
    import time
    started = time.perf_counter()
    try:
        from core.warmup import warm_worker
        warm_worker()
    except Exception as exc:  # noqa: BLE001
        _log(worker, f'warmup (worker) skipped: {exc!r}')
        return
    _log(worker, f'warmup (worker): {time.perf_counter() - started:.2f}s')

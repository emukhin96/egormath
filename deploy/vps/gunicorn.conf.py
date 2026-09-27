"""gunicorn для egormath на VPS (контейнер egormath-web).

gthread: ожидание LaTeX API (до 120 с) и Gemini занимает поток, а не
процесс, и не блокирует остальные запросы. Порт наружу не публикуется —
к нему ходит только egormath-front внутри docker-сетей.
"""
import os

bind = '0.0.0.0:8000'
worker_class = 'gthread'
workers = int(os.environ.get('GUNICORN_WORKERS', '2'))
threads = int(os.environ.get('GUNICORN_THREADS', '4'))

# LATEX_API_TIMEOUT = 120 с плюс запас; дольше — значит, что-то зависло.
timeout = 180
graceful_timeout = 30
keepalive = 5

# Перезапуск воркеров время от времени — страховка от утечек памяти.
max_requests = 2000
max_requests_jitter = 200

# Заголовкам X-Forwarded-* доверяем: снаружи порт недоступен.
forwarded_allow_ips = '*'

accesslog = '-'
errorlog = '-'
# %(M)s — время ответа в миллисекундах (для сравнения с Timeweb).
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'

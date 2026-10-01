"""
Настройки egormath-web.

Локальная разработка: SQLite, DEBUG=True (по умолчанию).
Продакшен (Timeweb): секреты в <корень сайта>/.secrets/, MySQL.
Переключение: файл .secrets/DJANGO_ENV со значением "production"
или переменная окружения DJANGO_ENV=production.
База в разработке — sqlite; DB_ENGINE=mysql подключает MySQL и без
production (локальный стенд со слепком прода, tools/stage.sh).
"""

import os
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # public_html/
SITE_ROOT = BASE_DIR.parent                        # корень репозитория / сайта
SECRETS_DIR = SITE_ROOT / '.secrets'


def _unwrap_quotes(value):
    """Снять только парную обёртку кавычек, не резать край пароля."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        return value[1:-1]
    return value


def read_secret(name, default=None):
    """Секрет из переменной окружения или файла .secrets/<name>."""
    value = os.environ.get(name)
    if value:
        return _unwrap_quotes(value)
    path = SECRETS_DIR / name
    if path.exists():
        return _unwrap_quotes(path.read_text(encoding='utf-8-sig'))
    return default


DJANGO_ENV = read_secret('DJANGO_ENV', 'development')
IS_PRODUCTION = DJANGO_ENV == 'production'

SECRET_KEY = read_secret(
    'DJANGO_SECRET_KEY',
    'django-insecure-dev-only-key-do-not-use-in-production',
)

DEBUG = not IS_PRODUCTION

ALLOWED_HOSTS = [
    h.strip()
    for h in read_secret('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if h.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'problems',
    'worksheets',
    'assignments',
    'independentworks',
    'workaudit',
    'canvas',
    'livefile',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.shell',
                'canvas.context_processors.canvas',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# На проде всегда MySQL (DB_ENGINE там не читается); в разработке — sqlite,
# либо MySQL при DB_ENGINE=mysql (стенд со слепком прода). Неизвестное
# значение — ошибка конфигурации, а не тихий уход на sqlite. DB_SOCKET —
# unix-сокет локального MySQL: через него caching_sha2_password не требует
# пакета cryptography, как TCP.
DB_ENGINE = 'mysql' if IS_PRODUCTION else read_secret('DB_ENGINE', 'sqlite')
if DB_ENGINE not in ('mysql', 'sqlite'):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        f'DB_ENGINE={DB_ENGINE!r}: допустимы только "mysql" и "sqlite"')
if DB_ENGINE == 'mysql':
    import pymysql

    pymysql.install_as_MySQLdb()
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': read_secret('DB_NAME', ''),
            'USER': read_secret('DB_USER', ''),
            'PASSWORD': read_secret('DB_PASSWORD', ''),
            'HOST': read_secret('DB_HOST', '127.0.0.1'),
            'PORT': read_secret('DB_PORT', '3306'),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
    DB_SOCKET = read_secret('DB_SOCKET', '')
    if DB_SOCKET:
        DATABASES['default']['OPTIONS']['unix_socket'] = DB_SOCKET
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'egormath-default',
    },
    # CGI-процессы не разделяют память. Файловый кэш хранит неизменяемую
    # часть рубрикатора между запросами и не требует отдельного сервиса.
    'taxonomy': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': SITE_ROOT / '.cache' / 'taxonomy',
        'TIMEOUT': 300,
        'OPTIONS': {'MAX_ENTRIES': 10},
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 6}},
]

LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
# На проде статика отдаётся с Cache-Control max-age=7 дней (.htaccess), поэтому
# имена файлов получают хэш содержимого: после деплоя браузеры сразу берут
# новые app.css/canvas.js, ручные ?v=N в шаблонах больше не нужны.
# Нестрогий режим: файл, которого нет в манифесте, отдаётся по обычному пути,
# а не роняет страницу.
if IS_PRODUCTION:
    STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'core.staticfiles.HashedStaticFilesStorage'},
    }

# Медиа (фото решений, кэш PDF) храним ВНЕ public_html: файлы приватные,
# раздаются только через view с проверкой прав.
MEDIA_ROOT = SITE_ROOT / 'media'
MEDIA_URL = '/media/'

# Файлы-версии живых страниц (см. livefile/files.py): лежат ВНУТРИ
# public_html, чтобы на проде их отдавал Apache без запуска Django.
# Содержимое — только метка времени; сами файлы в .gitignore.
LIVE_FILE_DIR = BASE_DIR / 'live'
if len(sys.argv) > 1 and sys.argv[1] == 'test':
    # Тесты создают назначения и проведения пачками — их файлы-версии
    # не должны засорять рабочий каталог.
    LIVE_FILE_DIR = Path(tempfile.mkdtemp(prefix='egormath-live-'))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# На проде раздел открывается только после миграций и приёмки.
INDEPENDENT_WORKS_ENABLED = read_secret('INDEPENDENT_WORKS_ENABLED', '1' if DEBUG else '0') == '1'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Школьников не разлогиниваем месяц
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30

# LaTeX API (тот же сервер, что у chgkmsu)
LATEX_API_URL = read_secret('LATEX_API_URL', 'http://81.200.147.78:8000')
LATEX_API_KEY = read_secret('LATEX_API_KEY', '')
LATEX_API_TIMEOUT = int(read_secret('LATEX_API_TIMEOUT', '120'))
# Повторы, когда общий latex-api занят (503/429 + Retry-After): не больше
# LATEX_API_RETRIES раз, пауза не длиннее LATEX_API_RETRY_MAX_DELAY секунд;
# новая попытка не начинается, если попытки и паузы уже заняли больше
# LATEX_API_RETRY_BUDGET секунд (latex-api сам держит запрос в очереди до 30 с).
LATEX_API_RETRIES = int(read_secret('LATEX_API_RETRIES', '4'))
LATEX_API_RETRY_MAX_DELAY = float(read_secret('LATEX_API_RETRY_MAX_DELAY', '10'))
LATEX_API_RETRY_BUDGET = float(read_secret('LATEX_API_RETRY_BUDGET', '60'))

# Нейрогенерация ответов/решений (Gemini API). Без ключа кнопки на
# импорте вернут понятную ошибку. Более сильная модель — одной
# настройкой GEMINI_MODEL (например gemini-3.5-flash).
GEMINI_API_KEY = (read_secret('GEMINI_API_KEY', '')
                  or read_secret('GOOGLE_API_KEY', ''))
GEMINI_MODEL = read_secret('GEMINI_MODEL', 'gemini-3.5-flash-lite')
GEMINI_API_BASE = read_secret('GEMINI_API_BASE', '')
GEMINI_PROXY_SECRET = read_secret('GEMINI_PROXY_SECRET', '')
GEMINI_TIMEOUT = int(read_secret('GEMINI_TIMEOUT', '60'))
GEMINI_RATE_PER_MINUTE = int(read_secret('GEMINI_RATE_PER_MINUTE', '20'))

# Профили шрифтов, доступные в PDF-редакторе (опция font= пакета egor).
# school и palatino требуют подготовленного LaTeX API: xelatex + mathspec
# + шрифты SchoolBookC/TextBookC/Palatino (сервер настроен, см.
# deploy/patch_latex_api_egormath.py). stix (STIX Two Text + Math через
# unicode-math) — OTF из worksheets/tex/fonts/ и egor.sty ≥ 1.3 из
# worksheets/tex/ уходят вместе со сборкой, поэтому не зависят от версии
# egor.sty на API. Если окружение без шрифтов — сузить, например
# PDF_EDITOR_FONTS=cm
PDF_EDITOR_FONTS = [
    f.strip()
    for f in read_secret('PDF_EDITOR_FONTS', 'cm,school,palatino,stix').split(',')
    if f.strip()]

# Ограничения на фото решений
SUBMISSION_PHOTO_MAX_SIZE_MB = 15       # до сжатия
SUBMISSION_PHOTO_MAX_SIDE = 1600        # px, большая сторона после сжатия
SUBMISSION_PHOTO_MAX_COUNT = 6          # фото на одну задачу

# Холст (мини-доска к задаче). Выключатель на случай перегрузки:
# CANVAS_ENABLED=0 в .secrets/ прячет панель и закрывает эндпоинты (503).
CANVAS_ENABLED = read_secret('CANVAS_ENABLED', '1').strip().lower() not in ('0', 'false', 'no', 'off')

if IS_PRODUCTION:
    # На VPS Django стоит за двумя Caddy (общий сервера → egormath-front),
    # HTTPS снимается снаружи; схему запроса берём из X-Forwarded-Proto.
    # На Timeweb (Apache, CGI) заголовок не приходит — ни на что не влияет.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    # Постоянные процессы gunicorn переиспользуют соединение с MySQL между
    # запросами; в CGI-процессе на Timeweb оно всё равно живёт один запрос.
    DATABASES['default']['CONN_MAX_AGE'] = int(read_secret('DB_CONN_MAX_AGE', '60'))
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True
    CSRF_TRUSTED_ORIGINS = [
        'https://' + h for h in ALLOWED_HOSTS if not h.startswith('.')
    ]
    SECURE_BROWSER_XSS_FILTER = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Локальные переопределения (не в git)
try:
    from .local_settings import *  # noqa: F401,F403
except ImportError:
    pass

"""
Настройки egormath-web.

Локальная разработка: SQLite, DEBUG=True (по умолчанию).
Продакшен (Timeweb): секреты в <корень сайта>/.secrets/, MySQL.
Переключение: файл .secrets/DJANGO_ENV со значением "production"
или переменная окружения DJANGO_ENV=production.
"""

import os
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

if IS_PRODUCTION:
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
# deploy/patch_latex_api_egormath.py). Если окружение без шрифтов —
# сузить, например PDF_EDITOR_FONTS=cm
PDF_EDITOR_FONTS = [
    f.strip()
    for f in read_secret('PDF_EDITOR_FONTS', 'cm,school,palatino').split(',')
    if f.strip()]

# Ограничения на фото решений
SUBMISSION_PHOTO_MAX_SIZE_MB = 15       # до сжатия
SUBMISSION_PHOTO_MAX_SIDE = 1600        # px, большая сторона после сжатия
SUBMISSION_PHOTO_MAX_COUNT = 6          # фото на одну задачу

# Холст (мини-доска к задаче). Выключатель на случай перегрузки:
# CANVAS_ENABLED=0 в .secrets/ прячет панель и закрывает эндпоинты (503).
CANVAS_ENABLED = read_secret('CANVAS_ENABLED', '1').strip().lower() not in ('0', 'false', 'no', 'off')

if IS_PRODUCTION:
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

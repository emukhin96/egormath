"""Настройки только для воспроизводимого прогона тестов на отдельном MySQL."""
import os
import tempfile
from pathlib import Path
import pymysql
from django.core.exceptions import ImproperlyConfigured

# Намеренно не импортируем core.settings: не читаем .secrets и local_settings.
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = 'independentworks-isolated-test-key'
DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'accounts', 'problems', 'worksheets', 'assignments', 'independentworks',
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
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'accounts.context_processors.shell',
    ]},
}]
CACHES = {name: {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                 'LOCATION': 'iw-test-' + name} for name in ('default', 'taxonomy')}
LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Europe/Moscow'
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_ROOT = Path(tempfile.gettempdir()) / 'independentworks-test-media'
MEDIA_URL = '/media/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
INDEPENDENT_WORKS_ENABLED = True
LOGIN_URL = '/accounts/login/'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
LATEX_API_KEY = GEMINI_API_KEY = GOOGLE_API_KEY = ''
LATEX_API_URL = 'http://127.0.0.1:1/disabled'
LATEX_API_TIMEOUT = GEMINI_TIMEOUT = 1
GEMINI_MODEL = 'disabled'
GEMINI_RATE_PER_MINUTE = 1
PDF_EDITOR_FONTS = ['cm']
SUBMISSION_PHOTO_MAX_SIZE_MB = 15
SUBMISSION_PHOTO_MAX_SIDE = 1600
SUBMISSION_PHOTO_MAX_COUNT = 6


def required(name):
    value = os.environ.get(name)
    if value is None:
        raise ImproperlyConfigured('Задайте ' + name + ' для отдельной тестовой MySQL-БД.')
    return value

pymysql.install_as_MySQLdb()

# Рабочие DB_* и секреты production не используются для подключения.
_name = os.environ.get('IW_TEST_MYSQL_DATABASE', 'test_egormath_independentworks')
if not _name.startswith('test_') or not _name.replace('_', '').isalnum():
    raise ValueError('Имя тестовой БД должно начинаться с test_ и содержать только буквы, цифры и _.')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': _name,
        'USER': required('IW_TEST_MYSQL_USER'),
        'PASSWORD': required('IW_TEST_MYSQL_PASSWORD'),
        'HOST': required('IW_TEST_MYSQL_HOST'),
        'PORT': os.environ.get('IW_TEST_MYSQL_PORT', '3306'),
        'OPTIONS': {'charset': 'utf8mb4'},
        'TEST': {'NAME': _name},
    },
}

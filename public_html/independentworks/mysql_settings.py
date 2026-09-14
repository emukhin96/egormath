"""Настройки только для воспроизводимого прогона тестов на отдельном MySQL."""
import os
import pymysql
from core.settings import *  # noqa: F401,F403

pymysql.install_as_MySQLdb()

# Рабочие DB_* и секреты production не используются для подключения.
_name = os.environ.get('IW_TEST_MYSQL_DATABASE', 'test_egormath_independentworks')
if not _name.startswith('test_') or not _name.replace('_', '').isalnum():
    raise ValueError('Имя тестовой БД должно начинаться с test_ и содержать только буквы, цифры и _.')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': _name,
        'USER': os.environ.get('IW_TEST_MYSQL_USER', 'root'),
        'PASSWORD': os.environ.get('IW_TEST_MYSQL_PASSWORD', ''),
        'HOST': os.environ.get('IW_TEST_MYSQL_HOST', '127.0.0.1'),
        'PORT': os.environ.get('IW_TEST_MYSQL_PORT', '3306'),
        'OPTIONS': {'charset': 'utf8mb4'},
        'TEST': {'NAME': _name},
    },
}

"""Entry point для shared-хостинга Timeweb (CGI-подобный mod_wsgi).

Локально не используется (там manage.py runserver / core/wsgi.py).
Пути вычисляются от расположения файла: <сайт>/public_html/wsgi.py,
venv ожидается в <сайт>/venv. Перезапуск приложения: touch wsgi.py.
"""

import os
import sys
import traceback

PUBLIC_HTML = os.path.dirname(os.path.abspath(__file__))
SITE_ROOT = os.path.dirname(PUBLIC_HTML)
ERROR_LOG = os.path.join(SITE_ROOT, 'wsgi_import_error.log')

# 1) venv (если есть activate_this.py — стандарт для virtualenv на Timeweb)
activate_this = os.path.join(SITE_ROOT, 'venv', 'bin', 'activate_this.py')
if os.path.exists(activate_this):
    exec(open(activate_this).read(), {'__file__': activate_this})
else:
    # venv, созданный python -m venv, не содержит activate_this.py —
    # добавляем site-packages вручную
    import glob
    for sp in glob.glob(os.path.join(
            SITE_ROOT, 'venv', 'lib', 'python*', 'site-packages')):
        if sp not in sys.path:
            sys.path.insert(0, sp)

# 2) Путь к проекту
if PUBLIC_HTML not in sys.path:
    sys.path.insert(0, PUBLIC_HTML)

# 3) PyMySQL как MySQLdb (+ обход проверки версии в Django>=4)
try:
    import pymysql
    pymysql.install_as_MySQLdb()
    try:
        pymysql.version_info = (2, 0, 0)
        pymysql.__version__ = '2.0.0'
    except Exception:
        pass
except Exception:
    with open(ERROR_LOG, 'a') as f:
        f.write('--- PyMySQL bootstrap failed ---\n')
        f.write(traceback.format_exc() + '\n')

# 4) Продакшен-режим и настройки
os.environ.setdefault('DJANGO_ENV', 'production')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

from django.core.wsgi import get_wsgi_application  # noqa: E402

try:
    application = get_wsgi_application()
except Exception:
    with open(ERROR_LOG, 'a') as f:
        f.write('--- get_wsgi_application() failed ---\n')
        f.write(traceback.format_exc() + '\n')
    raise

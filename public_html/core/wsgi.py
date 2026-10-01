"""
WSGI config for core project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

application = get_wsgi_application()

# Загружаем доверенную грамматику до приёма запросов. Отказ не мешает
# остальному сайту: проверка формул позже повторит ограниченный прогрев.
import sys
import subprocess
if sys.platform == 'linux':
    from assignments.checks.formula_fork import warmup
    try:
        warmup()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        import logging
        logging.getLogger(__name__).warning('Парсер формул пока не готов')

import os

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache


@never_cache
def healthz(request):
    """Проверка живости для deploy/vps: база отвечает, файлы-версии пишутся.

    Без авторизации и без данных — только статусы. 503, если что-то не так.
    """
    status = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        status['db'] = 'ok'
    except Exception:
        status['db'] = 'error'
    live_dir = settings.LIVE_FILE_DIR
    status['live'] = 'ok' if os.path.isdir(live_dir) and os.access(live_dir, os.W_OK) else 'error'
    healthy = all(value == 'ok' for value in status.values())
    return JsonResponse(status, status=200 if healthy else 503)

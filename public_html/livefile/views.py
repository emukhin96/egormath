"""Отдача файла-версии через Django — для runserver.

На проде до этой view дело не доходит: существующий файл отдаёт Apache
напрямую, а для отсутствующего ``.htaccess`` отвечает 404 без Python.
"""
from django.http import Http404, HttpResponse
from django.views.decorators.cache import never_cache

from . import files


@never_cache
def serve(request, token):
    if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise Http404
    target = files.directory() / f'{token}.txt'
    try:
        content = target.read_text(encoding='ascii')
    except OSError:
        raise Http404
    return HttpResponse(content, content_type='text/plain; charset=utf-8')

"""Файлы-версии живых страниц.

Страницы с живым обновлением (прогресс самостоятельной, обзор листка,
живая проверка, доски, слой учителя на доске ученика) опрашивают сервер
каждые несколько секунд. На хостинге с CGI-запуском Django каждый такой
опрос — новый процесс Python, даже если ответ 304. Поэтому «а изменилось
ли что-нибудь?» браузер спрашивает не у Django, а у статического файла
``<LIVE_FILE_DIR>/<токен>.txt``, который Apache отдаёт сам (правило
«существующие файлы — напрямую» в ``.htaccess``); только когда
содержимое файла изменилось, браузер идёт за настоящим фрагментом.

Сервер перезаписывает файл при каждом изменении данных страницы
(``touch``): сигналы моделей в :mod:`livefile.signals` плюс явные вызовы
там, где запись идёт через ``QuerySet.update()``. Содержимое файла —
наносекундная метка; смысл имеет только факт изменения.

Имя файла — HMAC от ключа страницы и ``SECRET_KEY``: адрес нельзя
перебрать, миграция не нужна. В файле нет данных, только «версия».
"""
import hashlib
import hmac
import logging
import os
import time
from pathlib import Path

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

URL_PREFIX = '/live/'


def key(kind, *ids):
    return kind + ':' + ':'.join(str(i) for i in ids)


def token(kind, *ids):
    """Стабильный непредсказуемый токен страницы (32 hex-символа)."""
    digest = hmac.new(settings.SECRET_KEY.encode(), key(kind, *ids).encode(), hashlib.sha256)
    return digest.hexdigest()[:32]


def directory():
    return Path(settings.LIVE_FILE_DIR)


def path(kind, *ids):
    return directory() / f'{token(kind, *ids)}.txt'


def url(kind, *ids, ensure=True):
    """URL файла-версии для атрибута ``data-live-file``.

    По умолчанию создаёт файл, если его ещё нет: иначе до первой записи
    браузер получал бы 404 и опрашивал Django по-старому.
    """
    if ensure:
        _ensure(path(kind, *ids))
    return f'{URL_PREFIX}{token(kind, *ids)}.txt'


def touch(kind, *ids):
    """Отметить изменение данных страницы — после фиксации транзакции.

    Внутри транзакции запись откладывается до commit: иначе браузер успел
    бы запросить фрагмент до появления данных и больше не перезапрашивал.
    """
    target = path(kind, *ids)
    transaction.on_commit(lambda: _write(target))


def touch_assignment(assignment_id, worksheet_id=None, student_id=None):
    """Все страницы, где виден прогресс назначения."""
    touch('assignment', assignment_id)
    if worksheet_id:
        touch('worksheet', worksheet_id)
    if student_id:
        touch('student', student_id)


def _stamp():
    return f'{time.time_ns()}\n'


def _ensure(target):
    if target.exists():
        return
    _write(target)


def _write(target):
    """Атомарная запись: читатель никогда не видит пустой файл."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f'.{target.name}.{os.getpid()}.{time.time_ns()}.tmp')
        tmp.write_text(_stamp(), encoding='ascii')
        os.replace(tmp, target)
    except OSError:
        # Файл-версия — оптимизация: страница обязана работать и без него.
        logger.warning('Не удалось записать файл-версию %s', target, exc_info=True)

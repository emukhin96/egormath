"""Вход в идущую самостоятельную с другого устройства (Run.lock_device).

Устройство — это браузер: при первом открытии работы он получает cookie
``COOKIE`` со случайным ключом. У попытки одно текущее устройство
(``Attempt.device``): первое, с которого ученик открыл начатую работу.

Настройка включена — с другого устройства работа не открывается: ученик
видит заглушку «Работа открыта на другом устройстве», ответы оттуда не
принимаются, а учитель в таблице прогресса видит попытку входа и кнопкой
переключает доступ (прежнее устройство после этого под той же заглушкой).
Настройка выключена — второе устройство входит молча и становится текущим,
учитель видит это в таблице и в хронологии работы.

До начала работы и после сдачи устройства не различаются: заданий на
странице ещё нет или их уже нельзя менять.
"""
import re
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from livefile import files as livefiles
from workaudit.services import lock_work
from .models import Attempt, AttemptDevice, DeviceEvent
from .services import WorkError, touch_attempt

COOKIE = 'iw_device'
COOKIE_AGE = 365 * 24 * 3600
FOREIGN_MESSAGE = 'Работа открыта на другом устройстве. Попросите учителя переключить доступ.'
# Перезагрузки страницы подряд — одна попытка входа в хронологии
RETRY_WINDOW = timedelta(seconds=30)


def device_key(request):
    """Ключ устройства из cookie; None — cookie нет или она испорчена."""
    try:
        return uuid.UUID(request.COOKIES.get(COOKIE, ''))
    except ValueError:
        return None


def remember(request, response, key):
    """Пометить браузер: cookie на год, скриптам страницы не видна."""
    response.set_cookie(COOKIE, str(key), max_age=COOKIE_AGE, httponly=True,
                        samesite='Lax', secure=request.is_secure())


SYSTEMS = [('iPhone', r'iPhone'), ('iPad', r'iPad'), ('Android', r'Android'),
           ('Windows', r'Windows'), ('ChromeOS', r'CrOS'), ('Mac', r'Macintosh|Mac OS X'),
           ('Linux', r'Linux')]
# Порядок важен: Edge, Opera и Яндекс Браузер называют себя ещё и Chrome,
# а Chrome — ещё и Safari
BROWSERS = [('Яндекс Браузер', r'YaBrowser'), ('Edge', r'Edg(e|A|iOS)?/'), ('Opera', r'OPR/|Opera'),
            ('Firefox', r'Firefox|FxiOS'), ('Chrome', r'Chrome|CriOS'), ('Safari', r'Safari')]


def device_label(user_agent):
    """«iPhone, Safari», «Windows, Chrome» — чтобы учитель узнал устройство."""
    def first(table):
        return next((name for name, pattern in table if re.search(pattern, user_agent or '')), '')
    return ', '.join(part for part in (first(SYSTEMS), first(BROWSERS)) if part) or 'Неизвестное устройство'


def active(attempt):
    return bool(attempt.started_at and not attempt.finished)


def foreign(attempt, key):
    """Не пускать: блокировка включена, работа идёт, а текущее устройство
    попытки — другое. Попытку без устройства (начата до появления настройки)
    привяжет первое открытие страницы."""
    return bool(attempt.run.lock_device and active(attempt) and attempt.device_id
                and attempt.device.key != key)


def guard(request, attempt):
    """Действия ученика в работе (ответ, фото, сдача, файлы условий) — только
    с текущего устройства. 403, а не 423: тот занят заглушкой ухода."""
    if foreign(attempt, device_key(request)):
        raise WorkError(FOREIGN_MESSAGE, 403)


@transaction.atomic
def enter(attempt_id, key, user_agent=''):
    """Ученик открыл страницу работы с устройства ``key``. True — не пущен.

    Первое устройство привязывается без события. Дальше при включённой
    блокировке вход записывается попыткой и ждёт учителя, при выключенной —
    устройство входит и становится текущим."""
    attempt = lock_work(Attempt, attempt_id)
    if not active(attempt):
        return False
    device, _ = AttemptDevice.objects.get_or_create(
        attempt=attempt, key=key, defaults={'label': device_label(user_agent)})
    if attempt.device_id == device.pk:
        return False
    now = timezone.now()
    if attempt.device_id and attempt.run.lock_device:
        if not device.events.filter(kind=DeviceEvent.DENIED, at__gt=now - RETRY_WINDOW).exists():
            DeviceEvent.objects.create(device=device, kind=DeviceEvent.DENIED, at=now)
        device.requested_at = now
        device.save(update_fields=['requested_at'])
        touch_attempt(attempt)
        return True
    if attempt.device_id:
        DeviceEvent.objects.create(device=device, kind=DeviceEvent.ENTER, at=now)
        touch_attempt(attempt)
    Attempt.objects.filter(pk=attempt.pk).update(device=device)
    if device.requested_at:
        device.requested_at = None
        device.save(update_fields=['requested_at'])
    return False


@transaction.atomic
def switch(attempt_id, device_id):
    """Учитель переключил доступ: работа продолжается на этом устройстве,
    остальные открытые страницы узнают об этом опросом файла-версии
    ``attempt:<pk>`` и закрываются заглушкой."""
    attempt = lock_work(Attempt, attempt_id)
    device = AttemptDevice.objects.filter(pk=device_id, attempt=attempt).first()
    if device is None:
        raise WorkError('Устройство не найдено.', 404)
    if attempt.device_id != device.pk:
        Attempt.objects.filter(pk=attempt.pk).update(device=device)
        DeviceEvent.objects.create(device=device, kind=DeviceEvent.SWITCH)
    AttemptDevice.objects.filter(pk=device.pk).update(requested_at=None)
    livefiles.touch('attempt', attempt.pk)
    touch_attempt(attempt)
    return device


def dismiss(attempt, device_id):
    """Учитель не пускает: запрос уходит из таблицы, в хронологии остаётся.
    Заглушка у ученика не меняется; новая попытка входа покажет запрос снова."""
    if AttemptDevice.objects.filter(pk=device_id, attempt=attempt).update(requested_at=None):
        touch_attempt(attempt)


def set_lock(run, on):
    """Настройку можно менять посреди работы: открытые страницы узнают о ней
    опросом файла-версии попытки. Выключили — ждущие входа проходят сами."""
    run.lock_device = on
    run.save(update_fields=['lock_device'])
    if not on:
        AttemptDevice.objects.filter(attempt__run=run).update(requested_at=None)
    for pk in run.attempts.filter(started_at__isnull=False, submitted_at__isnull=True).values_list('pk', flat=True):
        livefiles.touch('attempt', pk)
    livefiles.touch('run', run.pk)


def pending(attempt):
    """Устройства, ждущие решения учителя, по времени запроса."""
    if not (attempt.run.lock_device and active(attempt)):
        return []
    waiting = [d for d in attempt.devices.all() if d.requested_at and d.pk != attempt.device_id]
    return sorted(waiting, key=lambda d: (d.requested_at, d.pk))


def report(attempts):
    """Для таблицы прогресса: {pk попытки: {'pending': устройства, ждущие
    учителя, 'last': последнее событие, 'count': сколько за работу таких
    же событий (входов или попыток входа; переключения не считаются)}}.
    Попытки без событий не попадают."""
    attempts = list(attempts)
    by_attempt, counts = {}, {}
    events = (DeviceEvent.objects.filter(device__attempt__in=attempts)
              .select_related('device').order_by('at', 'pk'))
    for event in events:
        attempt_id = event.device.attempt_id
        counts[attempt_id, event.kind] = counts.get((attempt_id, event.kind), 0) + 1
        row = by_attempt.setdefault(attempt_id, {'pending': [], 'last': None, 'count': 0})
        row['last'] = event
        row['count'] = 0 if event.kind == DeviceEvent.SWITCH else counts[attempt_id, event.kind]
    waiting = (AttemptDevice.objects.filter(attempt__in=attempts, requested_at__isnull=False)
               .order_by('requested_at', 'pk'))
    current = {a.pk: a for a in attempts}
    for device in waiting:
        attempt = current[device.attempt_id]
        if attempt.run.lock_device and active(attempt) and device.pk != attempt.device_id:
            by_attempt.setdefault(attempt.pk, {'pending': [], 'last': None, 'count': 0})['pending'].append(device)
    return by_attempt


EVENT_TEXT = {DeviceEvent.ENTER: 'Вошёл с другого устройства',
              DeviceEvent.DENIED: 'Пытался войти с другого устройства',
              DeviceEvent.SWITCH: 'Учитель переключил доступ'}


def timeline_events(attempt):
    """События для хронологии работы (timeline.py)."""
    rows = []
    for event in DeviceEvent.objects.filter(device__attempt=attempt).select_related('device'):
        label = event.device.label
        detail = {DeviceEvent.DENIED: f'{label}, вход не разрешён',
                  DeviceEvent.SWITCH: f'на {label}'}.get(event.kind, label)
        rows.append({'at': event.at, 'kind': 'device', 'text': EVENT_TEXT[event.kind], 'detail': detail})
    return rows

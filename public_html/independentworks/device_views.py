"""Вход с другого устройства (devices.py): опрос страницы ученика и кнопки
учителя — переключить доступ, не пускать, настройка проведения."""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from . import devices
from . import services as svc
from .views import enabled, own_attempt, teacher_run


@enabled
def device_status(request, pk):
    """Опрос страницы ученика: не закрыта ли работа на этом устройстве.
    Попыткой входа не считается — её записывает открытие страницы работы."""
    attempt = own_attempt(request, pk)
    svc.finish_expired(attempt)
    return JsonResponse({'foreign': devices.foreign(attempt, devices.device_key(request)),
                         'finished': attempt.finished})


def _back(request, attempt, message):
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'ok': True})
    messages.success(request, message)
    if request.POST.get('back') == 'attempt':
        return redirect('independentworks:attempt', pk=attempt.pk)
    return redirect('independentworks:progress', pk=attempt.run_id)


@enabled
@teacher_required
@require_POST
def switch_device(request, pk, device_id):
    attempt = own_attempt(request, pk, teacher=True)
    device = devices.switch(attempt.pk, device_id)
    return _back(request, attempt, f'Доступ переключён: {device.label}')


@enabled
@teacher_required
@require_POST
def dismiss_device(request, pk, device_id):
    attempt = own_attempt(request, pk, teacher=True)
    devices.dismiss(attempt, device_id)
    return _back(request, attempt, 'Вход с другого устройства не разрешён')


@enabled
@teacher_required
@require_POST
def device_settings(request, pk):
    run = teacher_run(request, pk)
    devices.set_lock(run, 'lock_device' in request.POST)
    messages.success(request, 'Настройка входа с другого устройства сохранена')
    return redirect('independentworks:progress', pk=pk)

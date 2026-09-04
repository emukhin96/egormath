"""«Корзина»: сборка личного листка прямо из базы задач.

Черновик — обычный ``Worksheet``; в сессии хранится только его id
(``cart_worksheet``). Новых моделей нет: добавление и удаление идут через
те же helpers, что и конструктор (``append_task`` / ``soft_remove_item``).
Подборочные листки (с ``collection``) в корзину не попадают.
"""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from problems.models import Task

from .models import Worksheet
from .views import append_task, soft_remove_item

SESSION_KEY = 'cart_worksheet'
NEW_TITLE = 'Новый листок'


def personal_worksheets(user):
    """Листки, в которые можно собирать: свои и не подборочные."""
    return Worksheet.objects.filter(owner=user, collection__isnull=True)


def current_worksheet(request):
    """Текущий листок корзины; чужой/удалённый/ставший подборкой — сброс."""
    pk = request.session.get(SESSION_KEY)
    if not pk:
        return None
    worksheet = personal_worksheets(request.user).filter(pk=pk).first()
    if worksheet is None:
        request.session.pop(SESSION_KEY, None)
    return worksheet


def cart_context(request):
    """Данные индикатора в шапке и кнопок каталога (один запрос по элементам)."""
    worksheet = current_worksheet(request)
    task_ids = []
    if worksheet is not None:
        task_ids = list(worksheet.items.filter(
            deleted_at__isnull=True, task__isnull=False)
            .values_list('task_id', flat=True))
    return {
        'worksheet': worksheet,
        'task_ids': set(task_ids),
        'count': len(task_ids),
        'choices': list(personal_worksheets(request.user)
                        .order_by('-updated_at')
                        .values_list('pk', 'title')[:30]),
    }


def _is_xhr(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _back(request, fallback):
    """Redirect на страницу, откуда пришли (поле next), иначе fallback."""
    target = request.POST.get('next') or request.META.get('HTTP_REFERER')
    if target and url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect(fallback)


def _respond(request, worksheet, ok, message, in_cart, fallback='task_list'):
    if _is_xhr(request):
        count = worksheet.items.filter(
            deleted_at__isnull=True, task__isnull=False).count()
        return JsonResponse({
            'ok': ok,
            'message': message,
            'in_cart': in_cart,
            'count': count,
            'worksheet': {
                'id': worksheet.pk,
                'title': worksheet.title,
                'url': reverse('worksheet_detail', args=[worksheet.pk]),
            },
        }, status=200 if ok else 400)
    (messages.success if ok else messages.error)(request, message)
    return _back(request, fallback)


@teacher_required
@require_POST
def cart_add(request):
    """Положить задачу в текущий листок; если его нет — создать новый."""
    task = get_object_or_404(
        Task, pk=request.POST.get('task_id'), variant_of__isnull=True)
    worksheet = current_worksheet(request)
    if worksheet is None:
        worksheet = Worksheet.objects.create(
            title=NEW_TITLE, owner=request.user)
        request.session[SESSION_KEY] = worksheet.pk
    outcome, message = append_task(worksheet, task)
    if outcome == 'restored':
        message = f'Задача #{task.pk} возвращена в «{worksheet.title}».'
    return _respond(request, worksheet, True, message, True)


@teacher_required
@require_POST
def cart_remove(request):
    """Убрать задачу из текущего листка (мягко, как в конструкторе)."""
    worksheet = current_worksheet(request)
    if worksheet is None:
        if _is_xhr(request):
            return JsonResponse(
                {'ok': False, 'message': 'Листок для сборки не выбран.'},
                status=400)
        messages.error(request, 'Листок для сборки не выбран.')
        return _back(request, 'task_list')
    item = worksheet.items.filter(
        task_id=request.POST.get('task_id'), deleted_at__isnull=True).first()
    if item is not None:
        soft_remove_item(worksheet, item)
    return _respond(request, worksheet, True,
                    f'Задача убрана из «{worksheet.title}».', False)


@teacher_required
@require_POST
def cart_select(request):
    """Сменить текущий листок: id своего листка или «new»."""
    choice = request.POST.get('worksheet', '')
    if choice == 'new':
        worksheet = Worksheet.objects.create(
            title=NEW_TITLE, owner=request.user)
    else:
        worksheet = get_object_or_404(
            personal_worksheets(request.user), pk=choice or None)
    request.session[SESSION_KEY] = worksheet.pk
    messages.success(request, f'Собираем «{worksheet.title}».')
    return _back(request, 'task_list')


@teacher_required
@require_POST
def cart_clear(request):
    """«Закончить сборку»: листок остаётся, забывается только выбор."""
    request.session.pop(SESSION_KEY, None)
    messages.success(request, 'Сборка завершена.')
    return _back(request, 'task_list')

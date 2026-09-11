"""«Корзина»: отбор задач из базы, подборок и чужих листков в новый или
существующий личный листок.

Корзина виртуальная — упорядоченный список id задач в сессии
(``cart_tasks``). Листок не создаётся, пока учитель не нажмёт «в новый
листок» или «в существующий»: иначе от каждого клика оставались бы пустые
черновики. Запись в листок идёт через ``append_task`` — тот же helper, что
и у конструктора, поэтому дублей нет, а мягко удалённый элемент
восстанавливается. Подборочные листки (с ``collection``) корзина не
трогает.
"""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from problems.models import Task
from problems.task_blocks import block_members

from .models import Worksheet
from .views import append_task

SESSION_KEY = 'cart_tasks'
NEW_TITLE = 'Новый листок'


def personal_worksheets(user):
    """Листки, в которые учитель вправе собирать задачи."""
    return Worksheet.visible_to(user).filter(collection__isnull=True)


def cart_ids(request):
    """Задачи в корзине в порядке добавления (только целые id)."""
    raw = request.session.get(SESSION_KEY) or []
    return [pk for pk in raw if isinstance(pk, int)]


def _store(request, ids):
    if ids:
        request.session[SESSION_KEY] = ids
    else:
        request.session.pop(SESSION_KEY, None)


def cart_context(request):
    """Данные индикатора в шапке и кнопок «+» у задач."""
    ids = cart_ids(request)
    return {
        'ids': ids,
        'task_ids': set(ids),
        'count': len(ids),
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


def _respond(request, ok, message, in_cart, fallback='task_list'):
    if _is_xhr(request):
        return JsonResponse({
            'ok': ok,
            'message': message,
            'in_cart': in_cart,
            'count': len(cart_ids(request)),
        }, status=200 if ok else 400)
    (messages.success if ok else messages.error)(request, message)
    return _back(request, fallback)


@teacher_required
@require_POST
def cart_add(request):
    """Положить задачу в корзину (повтор — без дубля)."""
    task = get_object_or_404(
        Task, pk=request.POST.get('task_id'), variant_of__isnull=True)
    ids = cart_ids(request)
    if task.block_id:
        try:
            members = [t.pk for t in block_members(task)]
        except ValueError as exc:
            return _respond(request, False, str(exc), False)
        if not all(pk in ids for pk in members):
            ids = [pk for pk in ids if pk not in members] + members
            _store(request, ids)
        return _respond(request, True, f'В корзине весь блок: {len(members)} задач.', True)
    if task.pk in ids:
        message = f'Задача #{task.pk} уже в корзине.'
    else:
        ids.append(task.pk)
        _store(request, ids)
        message = f'Задача #{task.pk} — в корзине.'
    return _respond(request, True, message, True)


@teacher_required
@require_POST
def cart_remove(request):
    """Убрать задачу из корзины."""
    try:
        task_id = int(request.POST.get('task_id', ''))
    except ValueError:
        return _respond(request, False, 'Задача не указана.', False)
    task = Task.objects.filter(pk=task_id).first()
    removed = set(task.block.tasks.values_list('pk', flat=True)) if task and task.block_id else {task_id}
    _store(request, [pk for pk in cart_ids(request) if pk not in removed])
    return _respond(request, True, f'Задача #{task_id} убрана из корзины.',
                    False)


def _pour(request, worksheet):
    """Переложить корзину в листок; возвращает число новых элементов."""
    tasks = Task.objects.in_bulk(cart_ids(request))
    before = worksheet.items.filter(deleted_at=None, task__isnull=False).count()
    for pk in cart_ids(request):
        task = tasks.get(pk)
        if task is None:
            continue
        outcome, _ = append_task(worksheet, task)
    _store(request, [])
    return worksheet.items.filter(deleted_at=None, task__isnull=False).count() - before


@teacher_required
@require_POST
def cart_create(request):
    """Новый личный листок из корзины; корзина очищается."""
    if not cart_ids(request):
        messages.error(request, 'Корзина пуста — нечего собирать.')
        return _back(request, 'task_list')
    worksheet = Worksheet.objects.create(
        title=(request.POST.get('title') or '').strip() or NEW_TITLE,
        owner=request.user)
    added = _pour(request, worksheet)
    messages.success(request, f'Листок создан, задач: {added}.')
    return redirect('worksheet_detail', pk=worksheet.pk)


@teacher_required
@require_POST
def cart_append(request):
    """Добавить корзину в конец существующего личного листка."""
    if not cart_ids(request):
        messages.error(request, 'Корзина пуста — нечего добавлять.')
        return _back(request, 'task_list')
    worksheet = get_object_or_404(
        personal_worksheets(request.user),
        pk=request.POST.get('worksheet') or None)
    added = _pour(request, worksheet)
    messages.success(
        request, f'В «{worksheet.title}» добавлено задач: {added}.')
    return redirect('worksheet_detail', pk=worksheet.pk)


@teacher_required
@require_POST
def cart_clear(request):
    """Очистить корзину, ничего не создавая."""
    _store(request, [])
    messages.success(request, 'Корзина очищена.')
    return _back(request, 'task_list')

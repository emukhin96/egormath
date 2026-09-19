"""JSON-эндпоинты холста к задаче обычного задания.

Сервер только принимает и отдаёт JSON слоёв — ничего не рендерит и не
пересчитывает. Слои одной страницы лежат в разных полях со своими
версиями и сохраняются по отдельности (update_fields), поэтому ученик и
учитель могут писать одновременно, а конфликт возможен лишь между двумя
вкладками одного человека: его ловит версия слоя (409 с актуальными
данными). Чужой слой клиент забирает опросом GET с If-None-Match.
"""
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import get_role
from accounts.models import Profile
from assignments.models import Assignment
from assignments.views import _get_or_create_submission, _visible_task_item
from problems.models import Task

from . import services
from .models import CanvasPage
from .validation import CanvasValidationError, validate_background, validate_elements


def _error(message, status=400, **extra):
    payload = {'ok': False, 'message': message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _resolve(request, pk, task_id, *, lock=False):
    """(назначение, доступ) для текущего пользователя или 404/403."""
    role = get_role(request.user)
    if role == Profile.ROLE_STUDENT:
        assignment = get_object_or_404(
            Assignment.objects.select_related('worksheet'), pk=pk, student=request.user)
    elif role == Profile.ROLE_TEACHER:
        assignment = get_object_or_404(
            Assignment.visible_to(request.user).select_related('worksheet'), pk=pk)
    else:
        raise Http404
    if lock:
        # Общий замок с отправкой/возвратом: права и лимиты проверяем
        # после завершения предыдущего изменения, даже для первой страницы.
        assignment = Assignment.objects.select_for_update().get(pk=assignment.pk)
    access = services.assignment_access(assignment, request.user, role)
    _visible_task_item(assignment, get_object_or_404(Task, pk=task_id))
    return assignment, access


def _pages(assignment, task_id):
    return list(CanvasPage.objects.filter(
        submission__assignment=assignment, submission__task_id=task_id))


def _read_json(request):
    length = request.META.get('CONTENT_LENGTH') or 0
    try:
        length = int(length)
    except (TypeError, ValueError):
        length = 0
    if length > CanvasPage.MAX_BYTES + 64 * 1024:
        return None, _error('Страница слишком большая — упростите рисунок', status=413)
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None, _error('Некорректный JSON')
    if not isinstance(data, dict):
        return None, _error('Некорректный JSON')
    return data, None


def _disabled():
    return _error('Доска для записей временно отключена', status=503)


@login_required
@require_GET
def pages(request, pk, task_id):
    if not services.enabled():
        return _disabled()
    assignment, access = _resolve(request, pk, task_id)
    pages = _pages(assignment, task_id)
    etag = services.pages_etag(pages, access)
    if request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    response = JsonResponse({
        'ok': True,
        'pages': [services.page_payload(page, access) for page in pages],
        'layer': access.layer,
        'can_edit_student': access.can_edit_student,
        'can_edit_teacher': access.can_edit_teacher,
        'show_teacher_layer': access.show_teacher_layer,
        'can_add_pages': access.can_add_pages,
        'limits': {
            'student': CanvasPage.STUDENT_PAGE_LIMIT,
            'teacher': CanvasPage.TEACHER_PAGE_LIMIT,
            'total': CanvasPage.TOTAL_PAGE_LIMIT,
            'elements': CanvasPage.MAX_ELEMENTS,
        },
    })
    response['ETag'] = etag
    response['Cache-Control'] = 'no-cache'
    return response


@login_required
@require_POST
@transaction.atomic
def save_page(request, pk, task_id, number):
    if not services.enabled():
        return _disabled()
    assignment, access = _resolve(request, pk, task_id, lock=True)
    layer = access.layer
    if layer is None:
        return _error('Сейчас доска для записей только для чтения — изменения не сохранены', status=403)
    data, error = _read_json(request)
    if error:
        return error
    if data.get('layer', layer) != layer:
        return _error('Этот слой вам недоступен', status=403)
    try:
        elements = validate_elements(data.get('elements', []))
        background, options = validate_background(
            data.get('background', CanvasPage.BG_GRID), data.get('background_options'))
    except CanvasValidationError as exc:
        return _error(str(exc))
    if len(json.dumps(elements, separators=(',', ':'))) > CanvasPage.MAX_BYTES:
        return _error('Страница слишком большая — упростите рисунок', status=413)
    try:
        version = int(data.get('version', 0))
    except (TypeError, ValueError, OverflowError):
        return _error('Некорректная версия')

    with transaction.atomic():
        submission = _get_or_create_submission(assignment, task_id)
        pages = list(CanvasPage.objects.select_for_update().filter(submission=submission))
        page = next((p for p in pages if p.number == number), None)
        if page is None:
            if number != len(pages) + 1:
                return _error('Страницы добавляются по порядку', status=409)
            reason = services.creation_allowed(pages, access, layer)
            if reason:
                return _error(reason, status=403)
            if version != 0:
                return _error('Страница уже создана в другом окне', status=409)
            page = CanvasPage(submission=submission, number=number, created_by_role=layer,
                              locked_at=timezone.now() if layer == CanvasPage.ROLE_TEACHER else None)
        elif not services.can_edit_page(page, access, layer):
            return _error('Эта страница заморожена — изменения не сохранены', status=403)
        current_elements, current_version = page.layer(layer)
        if page.pk and version != current_version:
            return _error(
                'Страница изменена в другом окне', status=409,
                elements=current_elements, version=current_version)
        now = timezone.now()
        if layer == CanvasPage.ROLE_TEACHER:
            page.teacher_elements = elements
            page.teacher_version = current_version + 1
            page.teacher_updated_at = now
            page.teacher_by = request.user
            new_version, other_version = page.teacher_version, page.student_version
            fields = ['teacher_elements', 'teacher_version', 'teacher_updated_at', 'teacher_by']
        else:
            page.student_elements = elements
            page.student_version = current_version + 1
            page.student_updated_at = now
            new_version, other_version = page.student_version, page.teacher_version
            fields = ['student_elements', 'student_version', 'student_updated_at']
        # Фон — свойство страницы того, кто её создал; чужой слой его не трогает.
        if page.created_by_role == layer:
            page.background = background
            page.background_options = options
            fields += ['background', 'background_options']
        if page.pk:
            page.save(update_fields=fields)
        else:
            page.save()
    return JsonResponse({'ok': True, 'version': new_version, 'other_version': other_version,
                         'message': 'Сохранено ✓'})


@login_required
@require_POST
@transaction.atomic
def delete_page(request, pk, task_id, number):
    if not services.enabled():
        return _disabled()
    assignment, access = _resolve(request, pk, task_id, lock=True)
    layer = access.layer
    if layer is None:
        return _error('Сейчас доска для записей только для чтения', status=403)
    with transaction.atomic():
        pages = list(CanvasPage.objects.select_for_update().filter(
            submission__assignment=assignment, submission__task_id=task_id))
        page = next((p for p in pages if p.number == number), None)
        if page is None:
            return JsonResponse({'ok': True})
        if page.number != len(pages) or not page.is_empty:
            return _error('Удалить можно только пустую последнюю страницу', status=409)
        if not services.can_edit_page(page, access, layer):
            return _error('Эта страница заморожена', status=403)
        page.delete()
    return JsonResponse({'ok': True})

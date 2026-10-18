"""Политика доступа к общей базе задач.

Единственное место, где решается, кто вправе писать в общую базу: все
проверки «редактор базы / приглашённый учитель» в коде и шаблонах идут
через эти функции, а не через ``is_superuser`` напрямую. Подробности и
таблица точек записи — docs/USERS_PLAN.md, разделы 3–4.

Правило одно: приглашённый учитель видит общие задачи и пользуется ими, но
менять общую задачу может только локально — копией для своего листка
(``Task.make_variant``); в саму общую задачу пишут только редакторы базы.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse

from .decorators import teacher_required
from .models import Profile

# Тексты для пользователя: «общая задача» / «моя задача», а не «общая база»
# и «личная» (решение 6 плана пользователей; тест гигиены шаблонов).
BASE_LOCKED_MESSAGE = ('Общая задача: измените её для своего листка '
                       'или предложите исправление.')
EDITORS_ONLY_MESSAGE = 'Доступно только редакторам базы задач.'
NEURO_EDITORS_ONLY_MESSAGE = 'Нейрогенерация доступна только редакторам базы.'


def is_base_editor(user):
    """Суперпользователь или учитель с ``Profile.base_editor``."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser:
        return True
    try:
        return bool(user.profile.base_editor)
    except Profile.DoesNotExist:
        return False


def can_edit_task(user, task):
    """Редактор базы правит всё; остальные — только свои личные задачи
    и свои локальные копии (копия живёт в одном листке автора, флаг общей
    базы для неё ничего не значит)."""
    if is_base_editor(user):
        return True
    if task.created_by_id != user.pk:
        return False
    return not task.is_shared or task.variant_of_id is not None


def visible_tasks(user):
    """Задачи, которые пользователь вправе открыть: редактор — все,
    остальные — общие, свои (включая локальные копии) и те, что стоят в
    их листках: «Взять как листок» копирует подборку вместе с чужими
    локальными копиями и личными задачами автора подборки."""
    from problems.models import Task
    if is_base_editor(user):
        return Task.objects.all()
    return Task.objects.filter(
        Q(is_shared=True) | Q(created_by=user)
        | Q(worksheet_items__worksheet__owner=user)).distinct()


def shows_foreign_tasks(user):
    """Тумблер редактора «Показывать задачи других учителей»
    (``Profile.show_foreign_tasks``): по умолчанию выключен, у
    суперпользователя без профиля — тоже."""
    try:
        return bool(user.profile.show_foreign_tasks)
    except Profile.DoesNotExist:
        return False


def catalog_tasks(user):
    """База каталога, поиска, фасетов и подбора кандидатов: видимые задачи
    без локальных копий. Редактор базы при выключенном тумблере не видит
    здесь чужие личные задачи — только общие, свои и задачи без автора
    (такие не «другого учителя»); по прямой ссылке (``visible_tasks``)
    карточка открывается всегда."""
    tasks = cart_tasks(user)
    if is_base_editor(user) and not shows_foreign_tasks(user):
        tasks = tasks.filter(Q(is_shared=True) | Q(created_by=user)
                             | Q(created_by__isnull=True))
    return tasks


def cart_tasks(user):
    """Задачи, которые можно положить в листок по id (корзина): как прямая
    ссылка на карточку, без локальных копий и независимо от тумблера —
    редактор добавляет и чужую задачу, открытую по ссылке."""
    return visible_tasks(user).filter(variant_of__isnull=True)


def own_personal_tasks(user):
    """«Мои задачи» — свои задачи не из общей базы (без локальных копий)."""
    return cart_tasks(user).filter(created_by=user, is_shared=False)


def shared_catalog():
    """Общие задачи без локальных копий — для общих счётчиков (кэш один
    на всех пользователей, личные задачи в него не попадают)."""
    from problems.models import Task
    return Task.objects.filter(is_shared=True, variant_of__isnull=True)


def dedup_tasks(user=None):
    """База дедупликации при импорте и создании: общие задачи плюс свои —
    и для редактора тоже. Чужая личная задача не должна ни находиться как
    «уже есть #id», ни получать ответы из импорта, ни попадать в общий
    корпусный листок."""
    from problems.models import Task
    catalog = Task.objects.filter(variant_of__isnull=True)
    if user is None or not getattr(user, 'is_authenticated', False):
        return catalog.filter(is_shared=True)
    return catalog.filter(Q(is_shared=True) | Q(created_by=user))


def editable_tasks(user):
    """Задачи, которые пользователь вправе менять напрямую."""
    from problems.models import Task
    if is_base_editor(user):
        return Task.objects.all()
    return Task.objects.filter(created_by=user, is_shared=False)


def base_editor_required(view_func):
    """Только редакторам базы: импорт задачников, сверка корпуса,
    массовые ответы."""
    @wraps(view_func)
    @teacher_required
    def wrapper(request, *args, **kwargs):
        if not is_base_editor(request.user):
            raise PermissionDenied(EDITORS_ONLY_MESSAGE)
        return view_func(request, *args, **kwargs)
    return wrapper


def forbidden_json(message=BASE_LOCKED_MESSAGE):
    """403 для fetch-запросов редактора: ``{ok: false, message}``."""
    return JsonResponse({'ok': False, 'message': message}, status=403)

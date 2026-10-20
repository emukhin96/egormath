"""«Первые шаги» нового учителя (docs/USERS_PLAN.md, раздел 7).

Чеклист считается по данным учителя — имя, ученики, листки, выданные
задания — и ничего отдельно не хранит. Единственное поле —
``Profile.onboarding_done_at``: когда учитель закрыл карточку в кабинете
кнопкой «Скрыть». Карточку видят только учителя без права редактора
(``accounts/permissions.py``): суперпользователь и редакторы сайт знают.
"""
from django.conf import settings
from django.urls import reverse

from .decorators import get_role
from .models import Profile
from .permissions import is_base_editor

# Шаги с галочкой; пятый пункт страницы — пояснение про задачи, без галочки
STEP_KEYS = ('name', 'students', 'worksheet', 'assignment')


def has_students(user):
    return Profile.students_for(user).exists()


def has_worksheet(user):
    from worksheets.models import Worksheet
    return Worksheet.objects.filter(owner=user).exists()


def has_assignment(user):
    """Хоть одно выданное задание: обычное или проведённая самостоятельная."""
    from assignments.models import Assignment
    if Assignment.objects.filter(worksheet__owner=user).exists():
        return True
    if getattr(settings, 'INDEPENDENT_WORKS_ENABLED', False):
        from independentworks.models import Run
        return Run.objects.filter(owner=user, issued_at__isnull=False).exists()
    return False


def has_name(user):
    return bool(user.first_name.strip() and user.last_name.strip())


def shows_onboarding(user):
    """Учитель, которому адресованы «Первые шаги»: не редактор."""
    return get_role(user) == Profile.ROLE_TEACHER and not is_base_editor(user)


def onboarding_progress(request):
    """Состояние чеклиста для страницы «Первые шаги» и карточки в кабинете.

    ``steps`` — по порядку: ключ, выполнен ли шаг; ``done``/``total`` — счёт
    по шагам с галочкой; ``complete`` — ученики, листок и задание есть
    (карточка в кабинете скрывается сама). Ссылка регистрации учеников —
    абсолютная, как на странице «Ученики».
    """
    user = request.user
    profile = Profile.for_teacher(user)
    done = {
        'name': has_name(user),
        'students': has_students(user),
        'worksheet': has_worksheet(user),
        'assignment': has_assignment(user),
    }
    finished = sum(1 for key in STEP_KEYS if done[key])
    return {
        'steps': done,
        'done': finished,
        'total': len(STEP_KEYS),
        'percent': finished * 100 // len(STEP_KEYS),
        'complete': done['students'] and done['worksheet'] and done['assignment'],
        'hidden': profile.onboarding_done_at is not None,
        'registration_url': request.build_absolute_uri(
            f"{reverse('register')}?t={profile.student_code}"),
    }


def dashboard_onboarding(request):
    """Карточка «Первые шаги» в кабинете или ``None``: не редактору, пока
    он не скрыл её и пока не дошёл до выданного задания."""
    if not shows_onboarding(request.user):
        return None
    progress = onboarding_progress(request)
    if progress['hidden'] or progress['complete']:
        return None
    return progress

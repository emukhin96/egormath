from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import Profile


def get_role(user):
    """Роль пользователя; суперпользователь без профиля считается учителем."""
    try:
        return user.profile.role
    except Profile.DoesNotExist:
        if user.is_superuser:
            return Profile.ROLE_TEACHER
        return None


def teacher_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if get_role(request.user) != Profile.ROLE_TEACHER:
            raise PermissionDenied('Доступно только учителям')
        return view_func(request, *args, **kwargs)
    return wrapper


def student_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if get_role(request.user) != Profile.ROLE_STUDENT:
            raise PermissionDenied('Доступно только ученикам')
        return view_func(request, *args, **kwargs)
    return wrapper

"""Контекст оболочки (base.html): роль и корзина листка.

Роль берётся тем же ``get_role``, что и в dashboard, поэтому шаблонам не
нужно трогать ``user.profile`` напрямую. Для учеников и анонимов запросов
к БД нет.
"""
from django.conf import settings

from .decorators import get_role
from .models import Profile


def shell(request):
    # DEBUG, а не context_processors.debug: тот смотрит ещё INTERNAL_IPS.
    favicon_local = bool(settings.DEBUG)
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {
            'is_teacher': False,
            'cart': None,
            'favicon_local': favicon_local,
        }
    is_teacher = get_role(user) == Profile.ROLE_TEACHER
    context = {
        'is_teacher': is_teacher,
        'cart': None,
        'favicon_local': favicon_local,
    }
    if is_teacher:
        from worksheets.cart import cart_context
        context['cart'] = cart_context(request)
    return context

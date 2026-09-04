"""Контекст оболочки (base.html): роль и корзина листка.

Роль берётся тем же ``get_role``, что и в dashboard, поэтому шаблонам не
нужно трогать ``user.profile`` напрямую. Для учеников и анонимов запросов
к БД нет.
"""
from .decorators import get_role
from .models import Profile


def shell(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {'is_teacher': False, 'cart': None}
    is_teacher = get_role(user) == Profile.ROLE_TEACHER
    context = {'is_teacher': is_teacher, 'cart': None}
    if is_teacher:
        from worksheets.cart import cart_context
        context['cart'] = cart_context(request)
    return context

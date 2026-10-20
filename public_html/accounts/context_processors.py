"""Контекст оболочки (base.html): роль и корзина листка.

Роль берётся тем же ``get_role``, что и в dashboard, поэтому шаблонам не
нужно трогать ``user.profile`` напрямую. Для учеников и анонимов запросов
к БД нет.
"""
from django.conf import settings
from django.db.models import Count, Q
from django.utils.functional import SimpleLazyObject

from core.mailing import mail_enabled

from .decorators import get_role
from .models import Profile
from .permissions import is_base_editor


def shell(request):
    # DEBUG, а не context_processors.debug: тот смотрит ещё INTERNAL_IPS.
    favicon_local = bool(settings.DEBUG)
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {
            'is_teacher': False,
            'is_base_editor': False,
            'cart': None,
            'favicon_local': favicon_local,
            # «Забыли пароль?» на странице входа — только при настроенной почте
            'mail_enabled': mail_enabled(),
        }
    is_teacher = get_role(user) == Profile.ROLE_TEACHER
    context = {
        'independentworks_enabled': settings.INDEPENDENT_WORKS_ENABLED,
        'is_teacher': is_teacher,
        # Пункты меню только для редакторов базы: импорт задачников,
        # массовые ответы, сверка корпуса (accounts/permissions.py).
        'is_base_editor': is_teacher and is_base_editor(user),
        'cart': None,
        'favicon_local': favicon_local,
        # Кнопки «Отправить письмом» на странице учителей (accounts/mailing.py)
        'mail_enabled': mail_enabled(),
    }
    if is_teacher:
        from worksheets.cart import cart_context
        context['cart'] = cart_context(request)
        # Очередь предложений исправлений (problems/proposals.py): редактору
        # базы — новые, автору — ответы, которых он ещё не видел. Один запрос
        # на страницу, и только когда шаблон дошёл до счётчиков: частичные
        # рендеры (JSON-ответы редактора карточки) их не трогают.
        counts = SimpleLazyObject(
            lambda: proposal_counts(user, context['is_base_editor']))
        if context['is_base_editor']:
            context['proposals_new'] = SimpleLazyObject(lambda: counts['new'])
        context['proposals_replies'] = SimpleLazyObject(lambda: counts['replies'])
    return context


def proposal_counts(user, editor):
    """``new`` — новые предложения (редактору), ``replies`` — непросмотренные
    ответы автору; WHERE по индексам (status, created_at) и (author, status)."""
    from problems.models import TaskProposal
    mine = (Q(author=user, seen_by_author_at__isnull=True)
            & ~Q(status=TaskProposal.STATUS_NEW))
    if not editor:
        return {'new': 0, 'replies': TaskProposal.objects.filter(mine).count()}
    fresh = Q(status=TaskProposal.STATUS_NEW)
    return TaskProposal.objects.filter(fresh | mine).aggregate(
        new=Count('pk', filter=fresh), replies=Count('pk', filter=mine))

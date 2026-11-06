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
            'shows_onboarding': False,
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
    context['nav_section'] = nav_section(request)
    # Ссылки на «Первые шаги» в пустых состояниях и справку в футере —
    # учителю без права редактора (accounts/onboarding.py)
    context['shows_onboarding'] = is_teacher and not context['is_base_editor']
    if is_teacher:
        context['cart'] = _request_cart(request)
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


def _request_cart(request):
    """Контекст корзины один раз на запрос: живая страница задания,
    хронология и прогресс рендерят частичные шаблоны через
    ``render_to_string`` с request, и контекст-процессор вызывался на
    каждый из них — до 12 одинаковых запросов «последние листки и
    самостоятельные» (аудит быстродействия 06.11.2026). Ключ — состав
    корзины: если представление её изменило, контекст пересчитывается."""
    from worksheets.cart import cart_context, cart_ids
    key = tuple(cart_ids(request))
    cached = getattr(request, '_shell_cart', None)
    if cached is None or cached[0] != key:
        cached = request._shell_cart = (key, cart_context(request))
    return cached[1]


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


def nav_section(request):
    """Раздел верхнего меню, который подсвечивается на странице.

    Решается по приложению (префиксу пути), а не по подстроке имени URL:
    прогресс листка, доски и проверка живут в «Заданиях», хотя в их именах
    есть «worksheet», а сверка импорта (``textbook_import_review``) — в
    «Задачах», хотя в имени есть «review» (ревизия 03.11, G9).
    """
    match = getattr(request, 'resolver_match', None)
    name = getattr(match, 'url_name', '') or ''
    path = request.path
    if name == 'progress_overview':
        return 'students'
    if (path.startswith(('/assignments/', '/independent-works/'))
            or request.GET.get('mode') == 'independent'
            or request.GET.get('kind') == 'independent'):
        return 'assignments'
    if path.startswith('/problems/'):
        return 'tasks'
    if path.startswith('/worksheets/'):
        return 'collections' if 'collection' in name else 'worksheets'
    if 'student' in name or 'group' in name or name == 'teachers':
        return 'students'
    return ''

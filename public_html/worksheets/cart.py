"""«Корзина»: отбор задач из базы, подборок и чужих листков в новый или
существующий личный листок.

Корзина виртуальная — упорядоченный список id задач в сессии
(``cart_tasks``). Листок не создаётся, пока учитель не нажмёт «в новый
листок» или «в существующий»: иначе от каждого клика оставались бы пустые
черновики. Запись в листок идёт через ``append_task`` — тот же helper, что
и у конструктора, поэтому дублей нет, а мягко удалённый элемент
восстанавливается. Подборочные листки (с ``collection``) корзина не
трогает.

Вторая развязка — самостоятельная (``cart_to_independent``): каждая
задача становится номером, похожие (одна семья аналогов) — по желанию
вариантами одного номера; см. ``independentworks.from_cart``.
"""
from django.conf import settings
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from problems.templatetags.task_extras import plural_ru
from problems.web_tex import tex_preview_html

from accounts.decorators import teacher_required
from accounts.permissions import catalog_tasks
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


# Сколько задач показывать списком в меню корзины; остальные — «и ещё N»
MENU_ITEMS = 8
# Цветных точек семей аналогов (классы .cart-fam-1 … в input.css)
FAMILY_COLORS = 6
NEW_WORK_TITLE = 'Новая самостоятельная'


def _source_label(task):
    """«Мерзляк 8, №412» по первой ссылке на задачник, иначе «Задача #id»."""
    refs = sorted(task.source_refs.all(), key=lambda ref: ref.pk)
    for ref in refs:
        number = ref.number.strip().lstrip('№').strip()
        if number:
            return f'{ref.source.title}, №{number}'
    return f'Задача #{task.pk}'


def _menu_items(ids):
    """Первые MENU_ITEMS задач корзины для меню + метки семей аналогов.

    Точка семьи — только если в корзине не меньше двух задач этой семьи
    (те, что галочка «Похожие — в один номер» сложит в один номер).
    """
    shown = Task.objects.filter(pk__in=ids[:MENU_ITEMS]).prefetch_related(
        'source_refs__source').in_bulk()
    groups = {}
    if settings.INDEPENDENT_WORKS_ENABLED:
        from independentworks.analogs import similar_groups
        singles = set(Task.objects.filter(pk__in=ids, block__isnull=True)
                      .values_list('pk', flat=True))
        groups = similar_groups(pk for pk in ids if pk in singles)
    items = []
    for pk in ids[:MENU_ITEMS]:
        task = shown.get(pk)
        if task is None:
            continue
        group = groups.get(pk)
        items.append({
            'pk': pk,
            'label': _source_label(task),
            'preview': tex_preview_html(' '.join(task.text_latex.split()), 90),
            'family': None if group is None else group % FAMILY_COLORS + 1,
        })
    return items


def cart_context(request):
    """Данные индикатора в шапке, меню корзины и кнопок «+» у задач."""
    ids = cart_ids(request)
    works = []
    if settings.INDEPENDENT_WORKS_ENABLED:
        from independentworks.models import Work
        works = list(Work.visible_to(request.user).order_by('-updated_at', '-pk')
                     .values_list('pk', 'title')[:30])
    return {
        'ids': ids,
        'task_ids': set(ids),
        'count': len(ids),
        'items': _menu_items(ids) if ids else [],
        'more': max(len(ids) - MENU_ITEMS, 0),
        'choices': list(personal_worksheets(request.user)
                        .order_by('-updated_at')
                        .values_list('pk', 'title')[:30]),
        'works': works,
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


def _respond(request, ok, message, in_cart, fallback='task_list', task_ids=()):
    """``task_ids`` — все задачи, чьё состояние изменилось (весь блок для
    задачи блока): cart.js переключает «+»/«✓» у каждой."""
    if _is_xhr(request):
        return JsonResponse({
            'ok': ok,
            'message': message,
            'in_cart': in_cart,
            'count': len(cart_ids(request)),
            'task_ids': list(task_ids),
        }, status=200 if ok else 400)
    (messages.success if ok else messages.error)(request, message)
    return _back(request, fallback)


@teacher_required
@require_POST
def cart_add(request):
    """Положить задачу в корзину (повтор — без дубля)."""
    task = get_object_or_404(catalog_tasks(request.user), pk=request.POST.get('task_id'))
    ids = cart_ids(request)
    if task.block_id:
        try:
            members = [t.pk for t in block_members(task)]
        except ValueError as exc:
            return _respond(request, False, str(exc), False)
        if not all(pk in ids for pk in members):
            ids = [pk for pk in ids if pk not in members] + members
            _store(request, ids)
        return _respond(request, True, f'В корзине весь блок: {len(members)} задач.', True,
                        task_ids=members)
    if task.pk in ids:
        message = f'Задача #{task.pk} уже в корзине.'
    else:
        ids.append(task.pk)
        _store(request, ids)
        message = f'Задача #{task.pk} — в корзине.'
    return _respond(request, True, message, True, task_ids=[task.pk])


# Столько же, сколько задач помещается в развёрнутый раздел подборок
# (views.FLAT_ITEMS_LIMIT): кнопка «Всё в корзину» на такой странице
# не должна упираться в лимит.
CART_ADD_MANY_LIMIT = 400


@teacher_required
@require_POST
def cart_add_many(request):
    """Положить в корзину сразу список задач (страница подборки или раздела).

    Локальные копии и несуществующие id пропускаются; блоки добавляются
    целиком. Ограничение — CART_ADD_MANY_LIMIT задач за раз.
    """
    raw = [value for value in request.POST.getlist('task_ids') if value.isdigit()]
    if not raw:
        return _respond(request, False, 'Задачи не указаны.', False)
    if len(raw) > CART_ADD_MANY_LIMIT:
        return _respond(request, False,
                        f'За раз можно положить не больше {CART_ADD_MANY_LIMIT} задач.', False)
    wanted = [int(value) for value in raw]
    tasks = catalog_tasks(request.user).filter(pk__in=wanted).in_bulk()
    ids = cart_ids(request)
    added = 0
    for pk in wanted:
        task = tasks.get(pk)
        if task is None:
            continue
        members = [pk]
        if task.block_id:
            try:
                members = [t.pk for t in block_members(task)]
            except ValueError:
                continue
        for member in members:
            if member not in ids:
                ids.append(member)
                added += 1
    _store(request, ids)
    message = (f'В корзину добавлено задач: {added}.' if added
               else 'Все эти задачи уже в корзине.')
    return _respond(request, True, message, True, fallback='collection_list')


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
                    False, task_ids=sorted(removed))


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


@teacher_required
@require_GET
def cart_panel(request):
    """Содержимое меню корзины — для обновления без перезагрузки (cart.js)."""
    target = request.GET.get('next', '')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = reverse('task_list')
    return render(request, 'includes/cart_panel.html', {'cart_next': target})


@teacher_required
@require_POST
def cart_to_independent(request):
    """Корзина → номера новой или существующей самостоятельной.

    ``work`` — id видимой учителю самостоятельной (``target=existing``),
    пусто или ``target=new`` — новая с названием ``title``.
    ``group_similar=1`` — задачи одной семьи аналогов в один номер.
    """
    if not settings.INDEPENDENT_WORKS_ENABLED:
        raise Http404
    from django.db import transaction

    from independentworks.from_cart import add_tasks
    from independentworks.models import Work
    from independentworks.services import WorkError

    ids = cart_ids(request)
    if not ids:
        messages.error(request, 'Корзина пуста — нечего добавлять.')
        return _back(request, 'task_list')
    work_id = request.POST.get('work', '')
    existing = request.POST.get('target') != 'new' and work_id
    work = (get_object_or_404(Work.visible_to(request.user), pk=work_id)
            if existing and work_id.isdigit() else None)
    if existing and work is None:
        raise Http404
    tasks = Task.objects.in_bulk(ids)
    ordered = [tasks[pk] for pk in ids if pk in tasks]
    try:
        with transaction.atomic():
            if work is None:
                title = (request.POST.get('title') or '').strip()[:190] or NEW_WORK_TITLE
                work = Work.objects.create(owner=request.user, title=title)
            created, skipped = add_tasks(
                work, ordered, group_similar=request.POST.get('group_similar') == '1')
    except WorkError as error:
        messages.error(request, str(error))
        return _back(request, 'task_list')
    _store(request, [])
    parts = []
    if created:
        parts.append(f'Добавлено {len(created)} '
                     f'{plural_ru(len(created), "номер,номера,номеров")} из корзины')
    if skipped:
        parts.append(f'пропущено {skipped}: уже есть в самостоятельной')
    if created:
        messages.success(request, '; '.join(parts) + '.')
    else:
        messages.info(request, 'Новых номеров нет — ' + '; '.join(parts or ['корзина пуста']) + '.')
    if created:
        # Подсветку новых номеров edit покажет один раз (см. views.edit)
        request.session[f'iw_new_positions_{work.pk}'] = created
    return redirect('independentworks:edit', pk=work.pk)

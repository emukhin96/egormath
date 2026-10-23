"""Дашборд «Доски»: доски всех учеников листка на одном экране учителя.

Один экран — один опрос: клиент раз в 5 с спрашивает `boards_live`, сервер
одним индексированным запросом находит страницы, изменившиеся после
`since`, и отдаёт только их; если ничего не менялось — 304 без тела.
Не больше BOARDS_MAX учеников: миниатюры рисует браузер учителя, а сервер
не должен отдавать JSON всех досок класса на каждый тик.
"""
import hashlib
from urllib.parse import urlencode

from django.db.models import Count, Max, Q, Sum
from django.http import Http404, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.decorators import teacher_required
from accounts.models import StudentGroup
from assignments.models import Assignment, Submission
from livefile import etags
from worksheets.models import Worksheet, WorksheetItem

from . import services
from .models import CanvasPage

BOARDS_MAX = 15


ORDERS = [('recent', 'Сначала пишущие'), ('name', 'По фамилии'), ('wrong', 'Сначала с неверным ответом')]


def _order(request, task_id):
    """?order= — порядок карточек (макет E_Boards); «с неверным ответом» —
    только когда выбрана задача."""
    order = request.GET.get('order', '')
    return order if order in ('name', 'wrong') and (order != 'wrong' or task_id) else 'recent'


def _selection(request, worksheet, task_id=None):
    """Назначения листка, которые попадают на экран: не больше BOARDS_MAX,
    по порядку ?order= (по умолчанию сначала те, где недавно писали).
    Возвращает (список, сколько не поместилось, группа)."""
    assignments = Assignment.visible_to(request.user).filter(worksheet=worksheet).select_related('student')
    group_id = request.GET.get('group', '')
    group = None
    if group_id:
        group = get_object_or_404(StudentGroup.visible_to(request.user), pk=group_id if group_id.isdigit() else 0)
        assignments = assignments.filter(student__in=group.students.all())
    by_name = ('student__last_name', 'student__first_name', 'student__username')
    order = _order(request, task_id)
    assignments = list(assignments.annotate(last_canvas=Max('submissions__canvas_pages__student_updated_at'))
                       .order_by(*(by_name if order == 'name' else ('-last_canvas', *by_name))))
    if order == 'wrong':
        wrong = set(Submission.objects.filter(assignment__in=assignments, task_id=task_id,
                                              auto_check=Submission.CHECK_WRONG).values_list('assignment_id', flat=True))
        assignments.sort(key=lambda a: a.pk not in wrong)  # sort устойчив: внутри — по свежести
    return assignments[:BOARDS_MAX], max(0, len(assignments) - BOARDS_MAX), group


def _task_numbers(worksheet):
    items = worksheet.ordered_items().filter(task__isnull=False)
    return {item.task_id: number for number, item in enumerate(items, 1)}


def _task_filter(request, numbers):
    """?task=<id задачи> — показывать доски одной задачи у всех, а не последнюю
    изменённую у каждого; неизвестная задача = без фильтра."""
    raw = request.GET.get('task', '')
    task_id = int(raw) if raw.isdigit() else None
    return task_id if task_id in numbers else None


def _updated(page):
    stamps = [t for t in (page.student_updated_at, page.teacher_updated_at) if t]
    return max(stamps) if stamps else page.created_at


def _marks(assignments, task_id):
    """Отметка ответа на выбранную задачу у каждого: (символ, сколько раз
    проверял) — ✓ / × с числом проверок подстрочно, «…» введено без сверки."""
    if not task_id:
        return {}
    rows = (Submission.objects.filter(assignment__in=assignments, task_id=task_id)
            .annotate(checks=Count('check_history')).values_list('assignment_id', 'auto_check', 'checks', 'answer_json'))
    marks = {}
    for assignment_id, check, checks, answer in rows:
        if check == Submission.CHECK_OK:
            marks[assignment_id] = ('✓', checks if checks > 1 else '')
        elif check == Submission.CHECK_WRONG:
            marks[assignment_id] = ('×', checks or '')
        elif answer:
            marks[assignment_id] = ('…', '')
    return marks


def _states(assignments, task_id=None):
    marks = _marks(assignments, task_id)
    return [{
        'assignment': a.pk,
        'student': a.student.get_full_name() or a.student.username,
        'status': a.status, 'status_label': a.get_status_display(),
        'review_url': reverse('review_assignment', args=[a.pk]),
        'mark': marks.get(a.pk, ('', ''))[0], 'mark_sub': str(marks.get(a.pk, ('', ''))[1]),
    } for a in assignments]


def _copied(assignments, number=None):
    """Кто копировал больше одного слова условия (фиолетовая «•» у имени):
    выбранной задачи (number) или любой."""
    from assignments.windows import task_copies
    from workaudit.models import ActivityEvent
    from workaudit.services import copied_words
    if number:
        return {a.pk for a in assignments if any(c['words'] > 1 for c in task_copies(a, number))}
    events = ActivityEvent.objects.filter(assignment__in=assignments, kind='copy').only('assignment_id', 'text')
    return {e.assignment_id for e in events if copied_words(e) > 1}


def _task_panel(request, worksheet, task_id, numbers):
    """Панель условия выбранной задачи (макет E_Boards): условие, ответ маской
    и текстом, сколько верно / неверно / решают сейчас, ссылки на окно задачи
    и «задачу у класса»."""
    from assignments.windows import class_for_item, reference_for
    item = (WorksheetItem.objects.filter(worksheet=worksheet, task_id=task_id, deleted_at__isnull=True)
            .select_related('task').order_by('order', 'pk').first())
    data = class_for_item(request, worksheet.pk, item.pk)
    ok = sum(s['ok'] for s in data['stats'])
    answered = sum(s['answered'] for s in data['stats'])
    return {
        'item': item, 'task': item.task, 'number': numbers[task_id], 'subitems': item.selected_subitems(),
        'reference': [] if item.selected_subitems() else reference_for(item.task, 'boards_ref'),
        'ok': ok, 'wrong': answered - ok, 'live': data['stats'][0]['live'] if data['stats'] else 0,
        'task_window_url': reverse('worksheet_task_window', args=[worksheet.pk, item.pk]),
        'class_url': reverse('assignment_item_class', args=[worksheet.pk, item.pk]),
    }


@teacher_required
@never_cache
def worksheet_boards(request, worksheet_id):
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    numbers = _task_numbers(worksheet)
    task_id = _task_filter(request, numbers)
    assignments, overflow, group = _selection(request, worksheet, task_id)
    order = _order(request, task_id)
    query = {k: v for k, v in (('group', request.GET.get('group', '')), ('task', task_id),
                               ('order', '' if order == 'recent' else order)) if v}
    # Кнопки задач — только те, где у кого-то из выбранных учеников есть доска
    # (плюс выбранная в адресе, чтобы её кнопка не пропала)
    with_boards = set(CanvasPage.objects.filter(submission__assignment__in=[a.pk for a in assignments])
                      .values_list('submission__task_id', flat=True).distinct())
    if task_id:
        with_boards.add(task_id)
    states = {state['assignment']: state for state in _states(assignments, task_id)}
    copied = _copied(assignments, numbers.get(task_id))
    for a in assignments:
        a.board_state = states[a.pk]
        a.copied = a.pk in copied
    return render(request, 'canvas/boards.html', {
        'worksheet': worksheet, 'assignments': assignments, 'overflow': overflow,
        'order': order, 'orders': [(value, label) for value, label in ORDERS if value != 'wrong' or task_id],
        'strip': [{'id': tid, 'no': no} for tid, no in numbers.items()],
        'panel': _task_panel(request, worksheet, task_id, numbers) if task_id else None,
        'groups': StudentGroup.visible_to(request.user), 'group': group,
        'group_id': request.GET.get('group', ''), 'boards_max': BOARDS_MAX,
        'tasks': [{'id': tid, 'no': no} for tid, no in numbers.items() if tid in with_boards], 'task_id': task_id,
        'task_no': numbers.get(task_id),
        'live_url': reverse('worksheet_boards_live', args=[worksheet.pk]) + ('?' + urlencode(query) if query else ''),
        'peek_url': reverse('worksheet_boards_peek', args=[worksheet.pk, 0, 0]),
        'conditions_url': reverse('worksheet_boards_tasks', args=[worksheet.pk]) + ('?' + urlencode(query) if query else ''),
    })


@teacher_required
@never_cache
@require_GET
def worksheet_boards_live(request, worksheet_id):
    if not services.enabled():
        return JsonResponse({'ok': False, 'message': 'Доска для записей временно отключена'}, status=503)
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    numbers = _task_numbers(worksheet)
    task_id = _task_filter(request, numbers)
    assignments, overflow, _ = _selection(request, worksheet, task_id)
    ids = [a.pk for a in assignments]
    since = parse_datetime(request.GET.get('since') or '')
    if since is not None and timezone.is_naive(since):
        since = None
    now = timezone.now()
    pages = CanvasPage.objects.filter(submission__assignment_id__in=ids).select_related('submission')
    if task_id:
        pages = pages.filter(submission__task_id=task_id)
    states = _states(assignments, task_id)
    # Подпись экрана: статусы учеников + сводка по всем страницам выборки.
    # Не зависит от since, поэтому пустой опрос после первой загрузки — сразу 304.
    # Лёгкий список всех задач со страницами у каждого ученика — для диалога,
    # без фильтра по задаче; при фильтре — плюс пустая запись выбранной задачи у тех,
    # у кого доски по ней нет (диалог открывает её пустой, не соседнюю). Список
    # входит в подпись и приходит при каждом 200, чтобы новая доска другой задачи
    # появилась в диалоге без перезагрузки.
    light = list(CanvasPage.objects.filter(submission__assignment_id__in=ids).values_list(
        'pk', 'submission__assignment_id', 'submission__task_id', 'number',
        'student_updated_at', 'teacher_updated_at', 'created_at'))
    latest, per_task = {}, {}
    for pk, assignment_id, page_task, number, s_at, t_at, c_at in light:
        stamp = max(t for t in (s_at, t_at, c_at) if t)
        if (not task_id or page_task == task_id) and (assignment_id not in latest or stamp > latest[assignment_id][0]):
            latest[assignment_id] = (stamp, pk)
        key = (assignment_id, page_task)
        per_task[key] = max(per_task.get(key, 0), number)
    if task_id:
        for assignment_id in ids:
            per_task.setdefault((assignment_id, task_id), 0)
    tasks = [{'assignment': a, 'task': t, 'task_no': numbers.get(t), 'count': n,
              'canvas_url': reverse('canvas:pages', args=[a, t])}
             for (a, t), n in sorted(per_task.items())]
    answers = _answer_stamps(ids)
    summary = pages.aggregate(n=Count('pk'), s=Max('student_updated_at'), t=Max('teacher_updated_at'),
                              c=Max('created_at'), sv=Sum('student_version'), tv=Sum('teacher_version'))
    signature = hashlib.sha256(repr([
        [(s['assignment'], s['status'], s['mark'], s['mark_sub']) for s in states], overflow, task_id, sorted(summary.items()),
        sorted(per_task.items()), sorted(answers.items()),
    ]).encode()).hexdigest()
    etag = f'"{signature}"'
    if etags.matches(request, etag):
        return HttpResponseNotModified()
    if since is None:
        # Первая загрузка: JSON рисунка только одной последней страницы — для миниатюры
        changed = list(pages.filter(pk__in=[pk for _, pk in latest.values()]))
    else:
        changed = list(pages.filter(Q(student_updated_at__gt=since) | Q(teacher_updated_at__gt=since)
                                    | Q(created_at__gt=since)))
    response = JsonResponse({
        'ok': True, 'since': now.isoformat(), 'overflow': overflow, 'states': states, 'tasks': tasks,
        'task': task_id,
        # Версии ответов ученика (без доски): диалог перезагружает блок
        # «Задание · ответ ученика», только когда версия открытой задачи сменилась
        'answers': [{'assignment': a, 'task': t, 'version': v} for (a, t), v in sorted(answers.items())],
        'pages': [{
            'assignment': p.submission.assignment_id,
            'task': p.submission.task_id, 'task_no': numbers.get(p.submission.task_id),
            'number': p.number, 'locked': p.is_locked,
            'updated': _updated(p).isoformat(),
            'canvas_url': reverse('canvas:pages', args=[p.submission.assignment_id, p.submission.task_id]),
            'background': p.background, 'background_options': p.background_options or {},
            'student': {'elements': p.student_elements, 'version': p.student_version},
            'teacher': {'elements': p.teacher_elements, 'version': p.teacher_version},
        } for p in changed],
    })
    response['ETag'] = etag
    return response


def _answer_stamps(assignment_ids, task_id=None):
    """Версия ответа ученика по (назначение, задача) — одним запросом.

    Учитывает поля ответа, подпункты, сверку и фото, но не доску: доска
    обновляется своим путём, и её штрихи не должны перезагружать блок ответа.
    """
    rows = Submission.objects.filter(assignment_id__in=assignment_ids)
    if task_id is not None:
        rows = rows.filter(task_id=task_id)
    rows = rows.annotate(last_part=Max('parts__updated_at'), photos_n=Count('photos', distinct=True),
                         last_photo=Max('photos__uploaded_at')).values_list(
        'assignment_id', 'task_id', 'updated_at', 'auto_check', 'last_part', 'photos_n', 'last_photo')
    return {(a, t): hashlib.sha256(repr(rest).encode()).hexdigest()[:16] for a, t, *rest in rows}


def _answer_status(row):
    """Короткий итог ответа для заголовка блока: (код, подпись)."""
    targets = [sr['part'] for sr in row['subrows']] if row['subrows'] else [row['submission']]
    answered = [obj for obj in targets if obj is not None and obj.display_answer]
    if not answered:
        if row['submission'] is not None and row['submission'].photos.all():
            return 'photo', 'только фото'
        return 'empty', 'нет ответа'
    if any(getattr(obj, 'check_stale', False) for obj in answered):
        return 'unchecked', 'сверка устарела'
    checks = [obj.auto_check for obj in answered]
    if Submission.CHECK_WRONG in checks:
        return 'wrong', 'неверно'
    if all(check == Submission.CHECK_OK for check in checks):
        return ('ok', 'верно') if len(answered) == len(targets) else ('partial', 'верно частично')
    return 'unchecked', 'не сверено'


@teacher_required
@never_cache
@require_GET
def worksheet_boards_peek(request, worksheet_id, assignment_id, task_id):
    """Фрагмент диалога доски: условие задачи, ответ ученика и эталон.

    Те же строки, что на странице проверки (`_assignment_rows`): выбранные
    в пункте листка подпункты, отметки сверки по слотам, фото решения.
    """
    from assignments.views import _assignment_rows

    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    assignment = get_object_or_404(Assignment.visible_to(request.user).select_related('student', 'worksheet'),
                                   pk=assignment_id, worksheet=worksheet)
    numbers = _task_numbers(worksheet)
    if task_id not in numbers:
        raise Http404
    item = (WorksheetItem.objects.filter(worksheet=worksheet, task_id=task_id, deleted_at__isnull=True)
            .order_by('order', 'pk').first())
    row = next((r for r in _assignment_rows(assignment, with_review=True, item_ids={item.pk}) if r['task']), None)
    context = {'assignment': assignment, 'row': row, 'task_no': numbers[task_id],
               'version': _answer_stamps([assignment.pk], task_id).get((assignment.pk, task_id), '')}
    if row is not None:
        context['status'], context['status_label'] = _answer_status(row)
        context['subitems'] = [sr['subitem'] for sr in row['subrows']]
    return render(request, 'canvas/_boards_peek.html', context)


@teacher_required
@never_cache
@require_GET
def worksheet_boards_tasks(request, worksheet_id):
    """Фрагмент боковой панели «Условия задач»: все задачи листка по порядку.

    Грузится по первому открытию панели, а не со страницей досок: в листке
    бывает 40+ задач, и страница с живым опросом не должна их ждать.
    """
    from worksheets.block_presentation import decorate_block_rows

    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    items = [item for item in worksheet.ordered_items() if item.task_id]
    numbers = _task_numbers(worksheet)
    task_id = _task_filter(request, numbers)
    group_id = request.GET.get('group', '')
    rows = decorate_block_rows([{
        'item': item, 'number': numbers[item.task_id], 'subitems': item.selected_subitems(),
        'current': item.task_id == task_id,
        'boards_url': reverse('worksheet_boards', args=[worksheet.pk]) + '?' + urlencode(
            {k: v for k, v in (('group', group_id if group_id.isdigit() else ''), ('task', item.task_id)) if v}),
    } for item in items])
    return render(request, 'canvas/_boards_tasks.html', {'worksheet': worksheet, 'rows': rows})

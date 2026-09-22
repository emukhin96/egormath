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
from django.http import HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.decorators import teacher_required
from accounts.models import StudentGroup
from assignments.models import Assignment
from worksheets.models import Worksheet

from . import services
from .models import CanvasPage

BOARDS_MAX = 15


def _selection(request, worksheet):
    """Назначения листка, которые попадают на экран: не больше BOARDS_MAX,
    сначала те, где недавно писали. Возвращает (список, сколько не поместилось, группа)."""
    assignments = Assignment.visible_to(request.user).filter(worksheet=worksheet).select_related('student')
    group_id = request.GET.get('group', '')
    group = None
    if group_id:
        group = get_object_or_404(StudentGroup.visible_to(request.user), pk=group_id if group_id.isdigit() else 0)
        assignments = assignments.filter(student__in=group.students.all())
    assignments = list(assignments.annotate(last_canvas=Max('submissions__canvas_pages__student_updated_at'))
                       .order_by('-last_canvas', 'student__last_name', 'student__first_name', 'student__username'))
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


def _states(assignments):
    return [{
        'assignment': a.pk,
        'student': a.student.get_full_name() or a.student.username,
        'status': a.status, 'status_label': a.get_status_display(),
        'review_url': reverse('review_assignment', args=[a.pk]),
    } for a in assignments]


@teacher_required
@never_cache
def worksheet_boards(request, worksheet_id):
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    assignments, overflow, group = _selection(request, worksheet)
    numbers = _task_numbers(worksheet)
    task_id = _task_filter(request, numbers)
    query = {k: v for k, v in (('group', request.GET.get('group', '')), ('task', task_id)) if v}
    return render(request, 'canvas/boards.html', {
        'worksheet': worksheet, 'assignments': assignments, 'overflow': overflow,
        'groups': StudentGroup.visible_to(request.user), 'group': group,
        'group_id': request.GET.get('group', ''), 'boards_max': BOARDS_MAX,
        'tasks': [{'id': tid, 'no': no} for tid, no in numbers.items()], 'task_id': task_id,
        'task_no': numbers.get(task_id),
        'live_url': reverse('worksheet_boards_live', args=[worksheet.pk]) + ('?' + urlencode(query) if query else ''),
    })


@teacher_required
@never_cache
@require_GET
def worksheet_boards_live(request, worksheet_id):
    if not services.enabled():
        return JsonResponse({'ok': False, 'message': 'Доска для записей временно отключена'}, status=503)
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    assignments, overflow, _ = _selection(request, worksheet)
    ids = [a.pk for a in assignments]
    since = parse_datetime(request.GET.get('since') or '')
    if since is not None and timezone.is_naive(since):
        since = None
    now = timezone.now()
    numbers = _task_numbers(worksheet)
    task_id = _task_filter(request, numbers)
    pages = CanvasPage.objects.filter(submission__assignment_id__in=ids).select_related('submission')
    if task_id:
        pages = pages.filter(submission__task_id=task_id)
    states = _states(assignments)
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
    summary = pages.aggregate(n=Count('pk'), s=Max('student_updated_at'), t=Max('teacher_updated_at'),
                              c=Max('created_at'), sv=Sum('student_version'), tv=Sum('teacher_version'))
    signature = hashlib.sha256(repr([
        [(s['assignment'], s['status']) for s in states], overflow, task_id, sorted(summary.items()),
        sorted(per_task.items()),
    ]).encode()).hexdigest()
    etag = f'"{signature}"'
    if request.headers.get('If-None-Match') == etag:
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

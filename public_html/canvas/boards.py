"""Дашборд «Доски»: доски всех учеников листка на одном экране учителя.

Один экран — один опрос: клиент раз в 5 с спрашивает `boards_live`, сервер
одним индексированным запросом находит страницы, изменившиеся после
`since`, и отдаёт только их; если ничего не менялось — 304 без тела.
Не больше BOARDS_MAX учеников: миниатюры рисует браузер учителя, а сервер
не должен отдавать JSON всех досок класса на каждый тик.
"""
import hashlib

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
    return render(request, 'canvas/boards.html', {
        'worksheet': worksheet, 'assignments': assignments, 'overflow': overflow,
        'groups': StudentGroup.visible_to(request.user), 'group': group,
        'group_id': request.GET.get('group', ''), 'boards_max': BOARDS_MAX,
        'live_url': reverse('worksheet_boards_live', args=[worksheet.pk]),
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
    pages = CanvasPage.objects.filter(submission__assignment_id__in=ids).select_related('submission')
    states = _states(assignments)
    # Подпись экрана: статусы учеников + сводка по всем страницам выборки.
    # Не зависит от since, поэтому пустой опрос после первой загрузки — сразу 304.
    summary = pages.aggregate(n=Count('pk'), s=Max('student_updated_at'), t=Max('teacher_updated_at'),
                              c=Max('created_at'), sv=Sum('student_version'), tv=Sum('teacher_version'))
    signature = hashlib.sha256(repr([
        [(s['assignment'], s['status']) for s in states], overflow, sorted(summary.items()),
    ]).encode()).hexdigest()
    etag = f'"{signature}"'
    if request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    if since is None:
        # Первая загрузка: одна последняя страница на ученика, без лишнего JSON
        light = pages.values_list('pk', 'submission__assignment_id', 'student_updated_at', 'teacher_updated_at', 'created_at')
        latest = {}
        for pk, assignment_id, s_at, t_at, c_at in light:
            stamp = max(t for t in (s_at, t_at, c_at) if t)
            if assignment_id not in latest or stamp > latest[assignment_id][0]:
                latest[assignment_id] = (stamp, pk)
        changed = list(pages.filter(pk__in=[pk for _, pk in latest.values()]))
    else:
        changed = list(pages.filter(Q(student_updated_at__gt=since) | Q(teacher_updated_at__gt=since)
                                    | Q(created_at__gt=since)))
    numbers = _task_numbers(worksheet)
    response = JsonResponse({
        'ok': True, 'since': now.isoformat(), 'overflow': overflow, 'states': states,
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

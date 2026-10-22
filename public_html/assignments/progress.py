"""Живой обзор назначенного листка и оценки по отдельным задачам."""
import hashlib
from datetime import timedelta
import json
from django.http import JsonResponse, HttpResponseNotModified
from django.db.models import Prefetch, Max
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.utils import timezone
from accounts.decorators import teacher_required
from livefile import etags
from accounts.models import StudentGroup
from worksheets.models import Worksheet
from .models import Assignment, Review, Submission, SubmissionCheckAttempt
from .views import _assignment_rows, _teacher_assignment
from .point_progress import point_progress
from .windows import grade_caption, reference_for, student_window
from worksheets.latex import subitem_label
from workaudit.models import ActivityEvent
from workaudit.services import copy_label, copy_marks, whole_copies


@teacher_required
@require_POST
def grade_task(request, pk, task_id):
    assignment = _teacher_assignment(request, pk)
    items = assignment.worksheet.items.filter(task_id=task_id, deleted_at__isnull=True).exclude(pk__in=assignment.hidden_items.values('pk'))
    if not items.exists():
        from django.http import Http404
        raise Http404
    # Оценка и/или комментарий: окно «задача у ученика» сохраняет комментарий
    # отдельно от оценки (форма [data-point-review], поле comment)
    grade = request.POST.get('grade')
    comment = request.POST.get('comment')
    if grade is None and comment is None or grade is not None and grade not in dict(Review.GRADE_CHOICES):
        return JsonResponse({'message': 'Неизвестная оценка'}, status=400)
    submission, _ = Submission.objects.get_or_create(assignment=assignment, task_id=task_id)
    defaults = {'reviewer': request.user}
    if grade is not None:
        defaults.update(grade=grade, done=grade in ('+', '.+'))
    if comment is not None:
        defaults['comment'] = comment.strip()
    review, _ = Review.objects.update_or_create(submission=submission, defaults=defaults)
    return JsonResponse({'grade': review.grade, 'result': assignment.result(), 'feedback': review.comment,
                         'caption': grade_caption(review)})


def answer_versions(assignment, item_ids=None):
    """Лёгкие версии строк без загрузки снимков всех попыток."""
    hidden = set(assignment.hidden_items.values_list('pk', flat=True))
    values = assignment.submissions.annotate(last_part=Max('parts__updated_at'),
        last_photo=Max('photos__uploaded_at'), last_attempt=Max('check_history__pk'),
        last_canvas=Max('canvas_pages__student_updated_at')).values(
        'task_id', 'updated_at', 'auto_check', 'check_attempts', 'last_part', 'last_photo', 'last_attempt', 'last_canvas')
    if item_ids is not None:
        values = values.filter(task_id__in=assignment.worksheet.items.filter(pk__in=item_ids).values('task_id'))
    stamps = {v['task_id']: v for v in values}
    versions = {}
    items = assignment.worksheet.ordered_items()
    if item_ids is not None:
        items = items.filter(pk__in=item_ids)
    for item in items:
        if not item.task_id or item.pk in hidden:
            continue
        signature = [stamps.get(item.task_id), item.task.updated_at,
                     [(s.pk, s.answer_mask) for s in item.selected_subitems()]]
        versions[str(item.pk)] = hashlib.sha256(json.dumps(signature, default=str).encode()).hexdigest()
    return versions


@teacher_required
@never_cache
def assignment_live(request, pk):
    assignment = _teacher_assignment(request, pk)
    versions = answer_versions(assignment)
    try:
        previous = json.loads(request.GET.get('versions', '{}'))
        if not isinstance(previous, dict):
            previous = {}
    except (ValueError, TypeError):
        previous = {}
    changed = {int(key) for key, version in versions.items() if previous.get(key) != version}
    rows = _assignment_rows(assignment, with_review=True, item_ids=changed) if changed else []
    return JsonResponse({'versions': versions, 'rows': {str(row['item'].pk): render_to_string(
        'assignments/_live_answer.html', {'row': row}, request=request)
        for row in rows if row['task']}})


@teacher_required
@never_cache
def task_attempts(request, pk, task_id):
    assignment = _teacher_assignment(request, pk)
    items = assignment.worksheet.items.filter(task_id=task_id, deleted_at__isnull=True).exclude(pk__in=assignment.hidden_items.values('pk'))
    if request.GET.get('item'):
        items = items.filter(pk=request.GET['item'] if request.GET['item'].isdigit() else 0)
    item = get_object_or_404(items.order_by('order', 'pk')[:1])
    selected = item.selected_subitems()
    point_id = request.GET.get('subitem')
    selected_point = None
    if point_id is not None:
        selected_point = next((p for p in selected if str(p.pk) == point_id), None)
        if selected_point is None:
            from django.http import Http404
            raise Http404
    version = answer_versions(assignment, {item.pk}).get(str(item.pk), '') + str(point_id) + str(
        ActivityEvent.objects.filter(assignment=assignment, kind='copy').aggregate(last=Max('pk'))['last'])
    grade = list(assignment.submissions.filter(task_id=task_id).values_list('review__grade', 'review__comment'))
    etag = '"' + hashlib.sha256((version + repr(grade)).encode()).hexdigest() + '"'
    if etags.matches(request, etag):
        return HttpResponseNotModified()
    row = next((r for r in _assignment_rows(assignment, with_review=True, item_ids={item.pk}) if r['task']), None)
    if row is None:
        from django.http import Http404
        raise Http404
    detail = None
    if selected_point is not None or not selected:
        detail = point_progress(row['submission'], selected_point or item.task,
                                is_part=selected_point is not None, enabled=not item.task.full_answer_only, with_fragments=True)
        row['attempt_history'] = detail['history']
        row['legacy_attempts'] = 0
    response = render(request, 'assignments/_progress_detail.html', {
        'point': detail, 'selected_point': selected_point,
        'point_number': next(n for n, i in enumerate(assignment.worksheet.ordered_items().filter(task__isnull=False), 1) if i.pk == item.pk),
        'assignment': assignment, 'row': row, 'expand_history': True, 'grade_choices': Review.grade_options(),
        'reference': reference_for(selected_point or item.task) if detail else '',
        'solution': (selected_point or item.task).effective_solution_latex,
        **student_window(assignment, item, row)})
    response['ETag'] = etag
    return response


def progress_groups(items, assignments=None):
    groups_of_points = []
    hidden_sets = [{item.pk for item in assignment.hidden_items.all()} for assignment in assignments] if assignments is not None else []
    hidden = set.intersection(*hidden_sets) if hidden_sets else set()
    for number, item in enumerate(items, 1):
        if item.pk in hidden:
            continue
        parts = item.selected_subitems()
        columns = [{'owner': part, 'is_part': True, 'label': f'{number}{subitem_label(index)}'}
                   for index, part in enumerate(parts)] if parts else [{'owner': item.task, 'is_part': False, 'label': str(number)}]
        groups_of_points.append({'item': item, 'number': number, 'columns': columns})
    return groups_of_points


def progress_people(groups_of_points, assignments):
    people = []
    copied = whole_copies('assignment', assignments)
    for assignment in assignments:
        hidden = {i.pk for i in assignment.hidden_items.all()}
        submissions = {s.task_id: s for s in assignment.submissions.all()}
        cells = []
        for group in groups_of_points:
            item = group['item']
            sub = submissions.get(item.task_id)
            review = getattr(sub, 'review', None)
            for column in group['columns']:
                point = point_progress(sub, column['owner'], is_part=column['is_part'],
                                       enabled=not item.task.full_answer_only)
                cells.append({**point, **column, 'status_label': point['label'], 'item': item, 'task': item.task,
                              'hidden': item.pk in hidden, 'review': review})
        visible = [c for c in cells if not c['hidden']]
        result = {'done': sum(c['status'] == 'ok' for c in visible), 'total': len(visible)}
        people.append({'assignment': assignment, 'cells': cells, 'result': result,
                       'copied_whole': copied.get(assignment.pk, 0)})
    return people


LIVE_MINUTES = 15
ORDERS = {'name': 'По фамилии', 'behind': 'Сначала отстающие', 'result': 'По результату', 'submitted': 'По времени сдачи'}


def live_summary(groups_of_points, people, now=None):
    """Карта ответов «в моменте» (макет D_Live, 22.10.2026): у каждого
    ученика — что он делает сейчас и метка «•», если копировал из условия
    больше одного слова; по колонкам — сколько верно из ответивших и сколько
    решают сейчас; сверху — сводка класса. Дополняет people на месте."""
    from django.utils import timezone
    now = now or timezone.now()
    marks = copy_marks('assignment', [p['assignment'] for p in people])
    numbers = {g['item'].task_id: g['number'] for g in groups_of_points}
    live_since = now - timedelta(minutes=LIVE_MINUTES)
    summary = {'submitted': 0, 'live': 0, 'unopened': 0, 'pending': 0, 'copied': 0}
    for person in people:
        assignment = person['assignment']
        events = marks.get(assignment.pk, [])
        person['copied'] = bool(events)
        person['copy_note'] = '; '.join(copy_label(e) for e in events[-3:])
        stamps = []
        for sub in assignment.submissions.all():
            times = [sub.updated_at] + [part.updated_at for part in sub.parts.all()]
            stamps.append((max(times), sub.task_id))
        last = max(stamps) if stamps else None
        person['live_task'] = None
        if assignment.status in (Assignment.STATUS_SUBMITTED, Assignment.STATUS_REVIEWED):
            when = assignment.submitted_at
            person['now'] = 'сдано ' + timezone.localtime(when).strftime('%d.%m, %H:%M') if when else 'сдано'
            person['now_kind'] = 'done'
            summary['submitted'] += 1
            summary['pending'] += assignment.status == Assignment.STATUS_SUBMITTED
        elif last is None:
            person['now'], person['now_kind'] = 'не открыто', 'never'
            summary['unopened'] += 1
        elif last[0] >= live_since:
            person['live_task'] = last[1]
            # когда статус погаснет: опрос перезапросит фрагмент сам (teacher_progress.js)
            person['live_until'] = last[0] + timedelta(minutes=LIVE_MINUTES)
            person['now'] = f'на №{numbers.get(last[1], "?")}, {timezone.localtime(last[0]).strftime("%H:%M")}'
            person['now_kind'] = 'live'
            summary['live'] += 1
        else:
            person['now'] = 'ответ ' + timezone.localtime(last[0]).strftime('%d.%m')
            person['now_kind'] = 'idle'
        summary['copied'] += person['copied']
    stats = []
    index = 0
    for group in groups_of_points:
        # «решают сейчас» — у первой колонки задачи, подпункты делят одно число
        live = sum(1 for p in people if p['live_task'] == group['item'].task_id)
        for position, _column in enumerate(group['columns']):
            cells = [p['cells'][index] for p in people if not p['cells'][index]['hidden']]
            answered = [c for c in cells if c['status'] in ('ok', 'wrong')]
            ok = sum(c['status'] == 'ok' for c in answered)
            rate = ok / len(answered) if answered else None
            stats.append({'ok': ok, 'answered': len(answered), 'live': live if position == 0 else 0,
                          'tone': '' if rate is None else 'good' if rate >= .7 else 'mid' if rate >= .5 else 'low'})
            index += 1
    return summary, stats


def order_people(people, order):
    if order == 'behind':
        people.sort(key=lambda p: (p['result']['done'], p['assignment'].student.last_name))
    elif order == 'result':
        people.sort(key=lambda p: (-p['result']['done'], p['assignment'].student.last_name))
    elif order == 'submitted':
        people.sort(key=lambda p: (p['assignment'].submitted_at is None, p['assignment'].submitted_at or 0))
    return people


def progress_assignments(assignments):
    return assignments.select_related('student', 'worksheet').prefetch_related(
        'hidden_items', Prefetch('submissions', queryset=Submission.objects.select_related('review').prefetch_related('parts', 'photos', 'check_history')))


@teacher_required
@never_cache
def worksheet_progress(request, worksheet_id):
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    assignments = progress_assignments(Assignment.visible_to(request.user).filter(worksheet=worksheet))
    group_id = request.GET.get('group', '')
    if group_id:
        group = get_object_or_404(StudentGroup.visible_to(request.user), pk=group_id if group_id.isdigit() else 0)
        assignments = assignments.filter(student__in=group.students.all())
    items = list(worksheet.ordered_items().filter(task__isnull=False))
    groups_of_points = progress_groups(items, assignments)
    etag = None
    if request.GET.get('fragment'):
        submissions = list(Submission.objects.filter(assignment__in=assignments).annotate(
            last_part=Max('parts__updated_at'), last_photo=Max('photos__uploaded_at'), last_attempt=Max('check_history__pk')).values(
            'pk', 'updated_at', 'check_attempts', 'last_part', 'last_photo', 'last_attempt', 'review__reviewed_at'))
        # «решает сейчас» гаснет по времени без записей в БД — признак входит в ETag
        live_since = timezone.now() - timedelta(minutes=LIVE_MINUTES)
        state = [list(assignments.values('pk', 'status', 'student__first_name', 'student__last_name', 'student__username')),
                 submissions,
                 [max(filter(None, (s['updated_at'], s['last_part']))) >= live_since for s in submissions],
                 list(Assignment.hidden_items.through.objects.filter(assignment__in=assignments).values_list('assignment_id', 'worksheetitem_id')),
                 [(g['item'].pk, g['item'].task_id, g['item'].order, g['item'].task.updated_at,
                   [(c['owner'].pk, c['owner'].answer_mask, c['label']) for c in g['columns']]) for g in groups_of_points],
                 # метка «•» у ученика появляется от событий копирования
                 ActivityEvent.objects.filter(assignment__in=assignments, kind='copy').aggregate(last=Max('pk'))['last']]
        etag = '"' + hashlib.sha256(json.dumps(state, default=str).encode()).hexdigest() + '"'
        if etags.matches(request, etag):
            return HttpResponseNotModified()
    people = progress_people(groups_of_points, assignments.order_by('student__last_name', 'student__username'))
    summary, column_stats = live_summary(groups_of_points, people)
    order = request.GET.get('order', 'name') if request.GET.get('order') in ORDERS else 'name'
    order_people(people, order)
    deadline = assignments.aggregate(due=Max('due_at'))['due']
    context = {'worksheet': worksheet, 'items': items, 'point_groups': groups_of_points, 'people': people,
               'groups': StudentGroup.visible_to(request.user), 'group_id': group_id,
               'manage_status': request.GET.get('manage') == '1',
               'summary': summary, 'column_stats': column_stats, 'orders': ORDERS, 'order': order,
               'deadline': deadline, 'live_map': True, 'grade_choices': Review.grade_options(),
               'has_parts': any(c['is_part'] for g in groups_of_points for c in g['columns'])}
    template = 'assignments/_progress_table.html' if request.GET.get('fragment') else 'assignments/progress.html'
    response = render(request, template, context)
    if etag:
        response['ETag'] = etag
    return response


@teacher_required
@never_cache
def progress_overview(request):
    """Назначенные листки группы и переходы к живой проверке ученика."""
    from accounts.models import Profile
    from django.db.models import Count
    assignments = Assignment.visible_to(request.user)
    group_id, student_id = request.GET.get('group', ''), request.GET.get('student', '')
    group = student = None
    if group_id:
        group = get_object_or_404(StudentGroup.visible_to(request.user), pk=group_id if group_id.isdigit() else 0)
        assignments = assignments.filter(student__in=group.students.all())
    if student_id:
        profile = get_object_or_404(Profile.students_for(request.user).select_related('user'), user_id=student_id if student_id.isdigit() else 0)
        student = profile.user
        assignments = assignments.filter(student=student)
    from django.core.paginator import Paginator
    sheets = assignments.values('worksheet_id', 'worksheet__title').annotate(students=Count('student', distinct=True)).order_by('worksheet__title', 'worksheet_id')
    page = Paginator(progress_assignments(assignments).order_by('-assigned_at', '-pk') if student else sheets, 10 if student else 30).get_page(request.GET.get('page'))
    mini_tables = []
    if student:
        for assignment in page:
            points = progress_groups(list(assignment.worksheet.ordered_items().filter(task__isnull=False)), [assignment])
            mini_tables.append({'assignment': assignment, 'point_groups': points,
                                'people': progress_people(points, [assignment])})
    context = {
        'page': page, 'mini_tables': mini_tables,
        'groups': StudentGroup.visible_to(request.user), 'group': group, 'student': student,
    }
    if request.GET.get('fragment') and student:
        html = render_to_string('assignments/_student_progress_tables.html', context, request=request)
        etag = '"' + hashlib.sha256(html.encode()).hexdigest() + '"'
        if etags.matches(request, etag):
            return HttpResponseNotModified()
        from django.http import HttpResponse
        response = HttpResponse(html)
        response['ETag'] = etag
        return response
    return render(request, 'assignments/progress_overview.html', context)

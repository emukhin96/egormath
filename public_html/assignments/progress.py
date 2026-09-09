"""Живой обзор назначенного листка и оценки по отдельным задачам."""
from django.http import JsonResponse
from django.db.models import Prefetch, OuterRef, Subquery
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from accounts.decorators import teacher_required
from accounts.models import StudentGroup
from worksheets.models import Worksheet
from .models import Assignment, Review, Submission, SubmissionCheckAttempt
from .views import _assignment_rows, _teacher_assignment


@teacher_required
@require_POST
def grade_task(request, pk, task_id):
    assignment = _teacher_assignment(request, pk)
    items = assignment.worksheet.items.filter(task_id=task_id, deleted_at__isnull=True).exclude(pk__in=assignment.hidden_items.values('pk'))
    if not items.exists():
        from django.http import Http404
        raise Http404
    grade = request.POST.get('grade', '')
    if grade not in dict(Review.GRADE_CHOICES):
        return JsonResponse({'message': 'Неизвестная оценка'}, status=400)
    submission, _ = Submission.objects.get_or_create(assignment=assignment, task_id=task_id)
    Review.objects.update_or_create(submission=submission, defaults={
        'grade': grade, 'done': grade in ('+', '.+'), 'reviewer': request.user})
    return JsonResponse({'grade': grade, 'result': assignment.result()})


@teacher_required
@never_cache
def assignment_live(request, pk):
    assignment = _teacher_assignment(request, pk)
    rows = _assignment_rows(assignment, with_review=True)
    return JsonResponse({'rows': {str(row['task'].pk): render_to_string(
        'assignments/_live_answer.html', {'row': row}, request=request)
        for row in rows if row['task']}})


@teacher_required
@never_cache
def task_attempts(request, pk, task_id):
    assignment = _teacher_assignment(request, pk)
    row = next((r for r in _assignment_rows(assignment, with_review=True)
                if r['task'] and r['task'].pk == task_id), None)
    if row is None:
        from django.http import Http404
        raise Http404
    return render(request, 'assignments/_progress_detail.html', {
        'assignment': assignment, 'row': row, 'expand_history': True, 'grade_choices': Review.grade_options()})


@teacher_required
@never_cache
def worksheet_progress(request, worksheet_id):
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    latest = SubmissionCheckAttempt.objects.filter(submission_id=OuterRef('pk')).order_by('-number')
    submissions_query = Submission.objects.select_related('review').annotate(
        latest_result=Subquery(latest.values('result')[:1]),
        latest_number=Subquery(latest.values('number')[:1])).prefetch_related('parts', 'photos')
    assignments = Assignment.visible_to(request.user).filter(worksheet=worksheet).select_related('student').prefetch_related(
        'hidden_items', Prefetch('submissions', queryset=submissions_query))
    group_id = request.GET.get('group', '')
    if group_id:
        group = get_object_or_404(StudentGroup.visible_to(request.user), pk=group_id if group_id.isdigit() else 0)
        assignments = assignments.filter(student__in=group.students.all())
    items = list(worksheet.ordered_items().filter(task__isnull=False))
    people = []
    for assignment in assignments.order_by('student__last_name', 'student__username'):
        hidden = {i.pk for i in assignment.hidden_items.all()}
        submissions = {s.task_id: s for s in assignment.submissions.all()}
        cells = []
        for item in items:
            sub = submissions.get(item.task_id)
            review = getattr(sub, 'review', None)
            cells.append({'item': item, 'task': item.task, 'hidden': item.pk in hidden,
                          'submission': sub, 'review': review,
                          'attempt_count': max(sub.check_attempts, sub.latest_number or 0) if sub else 0,
                          'latest_result': sub.latest_result if sub else '',
                          'latest_label': dict(SubmissionCheckAttempt.RESULT_CHOICES).get(sub.latest_result, '') if sub else '',
                          'started': bool(sub and (sub.answer_json or sub.legacy_answer or sub.photos.all() or any(p.answer_json or p.legacy_answer for p in sub.parts.all())))})
        visible = [c for c in cells if not c['hidden']]
        result = {'done': sum(c['review'].credit for c in visible if c['review']), 'total': len(visible)}
        people.append({'assignment': assignment, 'cells': cells, 'result': result})
    context = {'worksheet': worksheet, 'items': items, 'people': people,
               'groups': StudentGroup.visible_to(request.user), 'group_id': group_id}
    template = 'assignments/_progress_table.html' if request.GET.get('fragment') else 'assignments/progress.html'
    return render(request, template, context)

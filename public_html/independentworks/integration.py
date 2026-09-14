"""Проекции самостоятельных для существующих каталогов заданий."""
from datetime import timedelta
from types import SimpleNamespace
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from .models import Attempt, Run, Work
from . import services


def attempt_status(attempt):
    if not attempt.finished:
        return 'assigned'
    return 'submitted' if services.result(attempt)['pending'] else 'reviewed'


def student_assignments(user):
    if not settings.INDEPENDENT_WORKS_ENABLED:
        return []
    now = timezone.now()
    rows = []
    attempts = (Attempt.objects.filter(student=user, run__issued_at__isnull=False)
                .select_related('run__owner', 'variant', 'root__variant', 'root__run')
                .prefetch_related('variant__points', 'answers__point', 'corrections__run', 'corrections__answers__point', 'root__variant__points', 'root__answers__point', 'root__corrections__run', 'root__corrections__answers__point'))
    for a in attempts:
        closed = not a.started_at and bool(a.run.deadline and a.run.deadline <= now)
        disclosed = 'checks' in a.disclosure
        status = 'reviewed' if a.finished and disclosed else 'submitted' if a.finished else 'assigned'
        remaining = max(0, int((a.ends_at - now).total_seconds())) if a.ends_at else None
        label = a.state
        if remaining is not None and not a.finished:
            label += f' · осталось {remaining // 60}:{remaining % 60:02}'
        if closed:
            label += ' · срок начала истёк'
        rows.append(SimpleNamespace(
            pk=f'independent-{a.pk}', kind='independent', kind_label=a.run.kind_label,
            worksheet=SimpleNamespace(title=a.run.title, owner=a.run.owner),
            assigned_at=a.run.issued_at, due_at=a.ends_at or a.run.deadline,
            status=status, get_status_display=label, is_overdue=False,
            is_editable_by_student=not a.finished and not closed,
            closed_unstarted=closed, active=bool(a.started_at and not a.finished),
            detail_url=reverse('independentworks:attempt', args=[a.pk]),
            result=services.result(a) if disclosed else None,
            cumulative=services.cumulative(a, student_view=True) if disclosed else None,
        ))
    return rows


def assignment_groups(user, params):
    if not settings.INDEPENDENT_WORKS_ENABLED or params.get('kind') == 'ordinary':
        return []
    runs = Run.objects.filter(work__in=Work.visible_to(user), issued_at__isnull=False).select_related('owner').prefetch_related('attempts__student', 'attempts__answers', 'attempts__variant__points')
    if params.get('owner', '').isdigit() and user.is_superuser:
        runs = runs.filter(owner_id=params['owner'])
    if params.get('worksheet', '').isdigit():
        runs = runs.filter(work__source_worksheet_id=params['worksheet'])
    rows = []
    now = timezone.now()
    for run in runs:
        attempts = list(run.attempts.all())
        if params.get('student', '').isdigit():
            attempts = [a for a in attempts if a.student_id == int(params['student'])]
        q = params.get('q', '').strip().casefold()
        if q and q not in run.title.casefold():
            attempts = [a for a in attempts if q in (a.student.get_full_name() + ' ' + a.student.username).casefold()]
        states = {a.pk: attempt_status(a) for a in attempts}
        if params.get('status'):
            attempts = [a for a in attempts if states[a.pk] == params['status']]
        due = params.get('due')
        def matches_due(a):
            end = a.ends_at or run.deadline
            if due == 'none': return end is None
            if due == 'overdue': return False
            if due == 'today': return end and timezone.localtime(end).date() == timezone.localdate()
            if due == 'week': return end and now <= end <= now + timedelta(days=7)
            return True
        attempts = [a for a in attempts if matches_due(a)]
        if not attempts:
            continue
        deadlines = [a.ends_at or run.deadline for a in attempts if a.ends_at or run.deadline]
        submitted = sum(states[a.pk] == 'submitted' for a in attempts)
        reviewed = sum(states[a.pk] == 'reviewed' for a in attempts)
        rows.append({'kind': 'independent', 'kind_label': run.kind_label, 'key': f'independent-{run.pk}', 'worksheet_id': None,
            'worksheet__title': run.title, 'worksheet__owner__first_name': run.owner.first_name,
            'worksheet__owner__last_name': run.owner.last_name, 'worksheet__owner__username': run.owner.username,
            'students_total': len(attempts), 'last_assigned': run.issued_at,
            'nearest_due': min(deadlines) if deadlines else None,
            'submitted_total': submitted, 'reviewed_total': reviewed,
            'queue_priority': 0 if submitted else 2 if reviewed < len(attempts) else 3,
            'progress_url': reverse('independentworks:progress', args=[run.pk])})
    return rows

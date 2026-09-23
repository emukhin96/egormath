"""Где и кому уже задавалась задача: обычные задания и самостоятельные.

История собирается из двух источников:

- ``Assignment`` → элементы листка (без ``hidden_items``, без мягко
  удалённых) — задача считается выданной каждому ученику назначения;
- ``independentworks.Point`` → попытки варианта — ключ ``source_key``
  имеет вид ``t<task_pk>`` или ``t<task_pk>:s<owner_pk>``.

Локальная копия задачи (``Task.variant_of``) засчитывается оригиналу.
«Аудитория» — ученик или группа, для которых нужна история; она
берётся из GET-параметров ``student``/``group`` и запоминается в
сессии, чтобы каталог, подбор кандидатов и подборки показывали одно
и то же, пока учитель не сменит выбор.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from functools import reduce
from operator import or_

from django.db.models import Q
from django.urls import reverse

from accounts.models import Profile, StudentGroup
from worksheets.models import WorksheetItem

from .models import Assignment

SESSION_KEY = 'task_usage_audience'
_POINT_TASK = re.compile(r'^t(\d+)(?::|$)')


@dataclass
class UsageRow:
    student: object
    date: datetime
    kind: str          # 'assignment' | 'independent'
    title: str
    url: str

    @property
    def student_name(self):
        return self.student.get_full_name() or self.student.username


@dataclass
class Audience:
    """Кому именно смотрим историю: ученик, группа или все ученики учителя."""
    student: object = None
    group: object = None

    @property
    def label(self):
        if self.student:
            return self.student.get_full_name() or self.student.username
        if self.group:
            return self.group.name
        return ''

    _ids = None

    @property
    def student_ids(self):
        if self.student:
            return {self.student.pk}
        if self.group:
            if self._ids is None:
                self._ids = set(self.group.students.values_list('pk', flat=True))
            return self._ids
        return None


def audience_choices(user):
    """Ученики и группы для селекта аудитории."""
    students = (Profile.students_for(user).select_related('user')
                .order_by('user__last_name', 'user__first_name', 'user__username'))
    groups = StudentGroup.visible_to(user).order_by('name')
    return [p.user for p in students], list(groups)


def resolve_audience(request):
    """Аудитория из GET ``who=student:<id>`` / ``who=group:<id>`` с памятью в сессии.

    Пустое ``who`` сбрасывает выбор. Без параметра берётся запомненное.
    """
    if 'who' in request.GET:
        kind, _, value = request.GET.get('who', '').strip().partition(':')
        chosen = {kind: int(value)} if kind in ('student', 'group') and value.isdigit() else {}
        if chosen:
            request.session[SESSION_KEY] = chosen
        else:
            request.session.pop(SESSION_KEY, None)
    stored = request.session.get(SESSION_KEY) or {}
    audience = Audience()
    if stored.get('student'):
        audience.student = (Profile.student_users_for(request.user)
                            .filter(pk=stored['student']).first())
    elif stored.get('group'):
        audience.group = StudentGroup.visible_to(request.user).filter(
            pk=stored['group']).first()
    if stored and not (audience.student or audience.group):
        request.session.pop(SESSION_KEY, None)
    return audience


def audience_context(request, audience=None):
    """Контекст селекта аудитории для фильтров каталога и подборок."""
    if audience is None:
        audience = resolve_audience(request)
    students, groups = audience_choices(request.user)
    for student in students:
        student.who_value = f'student:{student.pk}'
    for group in groups:
        group.who_value = f'group:{group.pk}'
    return {
        'audience': audience,
        'audience_value': (f'student:{audience.student.pk}' if audience.student
                           else f'group:{audience.group.pk}' if audience.group else ''),
        'audience_students': students,
        'audience_groups': groups,
    }


def _root_ids(tasks):
    """id оригиналов: локальная копия считается за исходную задачу."""
    return {task.variant_of_id or task.pk for task in tasks}


def task_usage(teacher, tasks, *, student_ids=None):
    """История выдачи по задачам: {id оригинала: [UsageRow, …]}.

    ``student_ids`` — ограничение аудитории (None — все ученики учителя).
    Строки отсортированы по убыванию даты.
    """
    root_ids = _root_ids(tasks)
    usage = {pk: [] for pk in root_ids}
    if not root_ids:
        return usage
    if student_ids is not None and not student_ids:
        return usage

    # Обычные задания: листок → задачи → назначения.
    items = list(WorksheetItem.objects.filter(
        deleted_at__isnull=True).filter(
        Q(task_id__in=root_ids) | Q(task__variant_of_id__in=root_ids)
    ).values_list('pk', 'worksheet_id', 'task_id', 'task__variant_of_id'))
    tasks_by_worksheet = {}
    for item_pk, worksheet_id, task_id, variant_of_id in items:
        root = variant_of_id if variant_of_id in root_ids else task_id
        tasks_by_worksheet.setdefault(worksheet_id, []).append((item_pk, root))
    if tasks_by_worksheet:
        assignments = (Assignment.visible_to(teacher)
                       .filter(worksheet_id__in=tasks_by_worksheet)
                       .select_related('student', 'worksheet')
                       .prefetch_related('hidden_items'))
        if student_ids is not None:
            assignments = assignments.filter(student_id__in=student_ids)
        for assignment in assignments:
            hidden = {item.pk for item in assignment.hidden_items.all()}
            seen = set()
            for item_pk, root in tasks_by_worksheet[assignment.worksheet_id]:
                if item_pk in hidden or root in seen:
                    continue
                seen.add(root)
                usage[root].append(UsageRow(
                    student=assignment.student, date=assignment.assigned_at,
                    kind='assignment', title=assignment.worksheet.title,
                    url=reverse('worksheet_progress',
                                args=[assignment.worksheet_id])))

    # Самостоятельные: пункты варианта → попытки учеников.
    from independentworks.models import Attempt, Point, Work
    key_filter = reduce(or_, (
        Q(source_key=f't{pk}') | Q(source_key__startswith=f't{pk}:')
        for pk in root_ids))
    points = list(Point.objects.filter(
        variant__run__work__in=Work.visible_to(teacher),
        variant__run__issued_at__isnull=False,
    ).filter(key_filter).values_list('variant_id', 'source_key').distinct())
    if points:
        variant_tasks = {}
        for variant_id, source_key in points:
            match = _POINT_TASK.match(source_key)
            if match and int(match.group(1)) in root_ids:
                variant_tasks.setdefault(variant_id, set()).add(int(match.group(1)))
        attempts = (Attempt.objects.filter(variant_id__in=variant_tasks)
                    .select_related('student', 'run'))
        if student_ids is not None:
            attempts = attempts.filter(student_id__in=student_ids)
        for attempt in attempts:
            for root in variant_tasks[attempt.variant_id]:
                usage[root].append(UsageRow(
                    student=attempt.student,
                    date=attempt.run.issued_at or attempt.run.created_at,
                    kind='independent', title=attempt.run.title,
                    url=reverse('independentworks:progress',
                                args=[attempt.run_id])))

    for rows in usage.values():
        rows.sort(key=lambda row: row.date, reverse=True)
    return usage


def attach_usage(request, tasks, *, audience=None):
    """Навешивает ``task.usage`` на каждую задачу списка одним проходом.

    ``task.usage`` — словарь для ``includes/task_usage_badge.html``:
    строки истории, аудитория и число разных учеников.
    """
    tasks = [task for task in tasks if task is not None]
    if not tasks:
        return audience
    if audience is None:
        audience = resolve_audience(request)
    usage = task_usage(request.user, tasks, student_ids=audience.student_ids)
    for task in tasks:
        rows = usage.get(task.variant_of_id or task.pk, [])
        task.usage = {
            'rows': rows,
            'audience': audience,
            'students_total': len({row.student.pk for row in rows}),
            'audience_total': (len(audience.student_ids)
                               if audience.student_ids is not None else None),
        }
    return audience

"""Быстрый фильтр «Кому» в «Листках» и «Заданиях»: группа и ученик.

Строка под фильтрами (includes/recipient_quick_filter.html): группы —
сегментами, как классы, а при большом числе групп — выпадающим списком;
ученик — всегда выпадающий список (их десятки), при выбранной группе —
только её ученики. В списках только группы и ученики, у которых есть
выданные работы, — пустые варианты не занимают место.

Группа отбирает работы, выданные её ученикам (вместе или по одному):
учитель ищет «что получал 7А», и личная выдача ученику группы тоже сюда.
"""
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef

from accounts.models import StudentGroup

from .models import Assignment

# Больше групп — выпадающий список вместо сегментов (как _group_filter.html)
SEG_GROUPS_MAX = 6


def recipient_filter(user, params, student_ids=None):
    """Варианты и выбранные значения фильтра.

    ``student_ids`` — подзапрос id учеников, у которых есть работы (по
    умолчанию — получатели видимых учителю выдач листков). Возвращает
    словарь для шаблона и ``apply_to_assignments`` / ``member_ids``.
    """
    if student_ids is None:
        student_ids = Assignment.visible_to(user).values('student_id')
    students = get_user_model().objects.filter(pk__in=student_ids)
    groups = list(StudentGroup.visible_to(user).filter(Exists(
        students.filter(member_groups=OuterRef('pk')))).order_by('name'))
    raw_group = params.get('group', '').strip()
    group = next((g for g in groups if str(g.pk) == raw_group), None)
    if group is not None:
        students = students.filter(member_groups=group)
    students = list(students.order_by('last_name', 'first_name', 'username'))
    raw_student = params.get('student', '').strip()
    student = next((s for s in students if str(s.pk) == raw_student), None)
    return {
        'groups': groups,
        'group': group,
        'group_value': str(group.pk) if group else '',
        'students': students,
        'student': student,
        'student_value': str(student.pk) if student else '',
        'seg': len(groups) <= SEG_GROUPS_MAX,
        'active': bool(group or student),
    }


def apply_to_assignments(assignments, selected):
    """Выдачи под фильтром «Кому»."""
    if selected['group'] is not None:
        assignments = assignments.filter(student__member_groups=selected['group']).distinct()
    if selected['student'] is not None:
        assignments = assignments.filter(student=selected['student'])
    return assignments


def member_ids(selected):
    """id учеников под фильтром (для самостоятельных, где отбор в Python);
    None — фильтра нет."""
    if selected['student'] is not None:
        return {selected['student'].pk}
    if selected['group'] is not None:
        return set(selected['group'].students.values_list('pk', flat=True))
    return None

"""Общая логика холста: права, страницы, заморозка."""
from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone

from .models import CanvasPage


def enabled():
    return bool(getattr(settings, 'CANVAS_ENABLED', True))


def lock_assignment_pages(assignment, now=None):
    """Замораживает страницы ученика при отправке работы на проверку."""
    CanvasPage.objects.filter(
        submission__assignment=assignment, locked_at__isnull=True,
    ).update(locked_at=now or timezone.now())


def assignment_page_stats(assignment):
    """Число страниц, последнее изменение и непустые слои ученика по задачам."""
    rows = (CanvasPage.objects
            .filter(submission__assignment=assignment)
            .values('submission__task_id')
            .annotate(n=Count('pk'), updated=Max('student_updated_at'),
                      answered=Count('pk', filter=~Q(student_elements=[]))))
    return {row['submission__task_id']: (row['n'], row['updated'], row['answered']) for row in rows}


class Access:
    """Что текущий пользователь может делать с холстом одной задачи."""

    def __init__(self, *, role, can_edit_student, can_edit_teacher, show_teacher_layer):
        self.role = role
        self.can_edit_student = can_edit_student
        self.can_edit_teacher = can_edit_teacher
        self.show_teacher_layer = show_teacher_layer

    @property
    def layer(self):
        """Слой, который пользователь может править сейчас, или None."""
        if self.role == CanvasPage.ROLE_STUDENT and self.can_edit_student:
            return CanvasPage.ROLE_STUDENT
        if self.role == CanvasPage.ROLE_TEACHER and self.can_edit_teacher:
            return CanvasPage.ROLE_TEACHER
        return None


def assignment_access(assignment, user, role):
    """Правило одной строкой: слой учителя открыт ровно тогда, когда
    слой ученика закрыт; ученик видит пометки после возврата или проверки."""
    editable = assignment.is_editable_by_student
    if role == CanvasPage.ROLE_STUDENT:
        return Access(
            role=role, can_edit_student=editable, can_edit_teacher=False,
            show_teacher_layer=assignment.status in (
                assignment.STATUS_RETURNED, assignment.STATUS_REVIEWED))
    return Access(
        role=role, can_edit_student=False, can_edit_teacher=not editable,
        show_teacher_layer=True)


def page_payload(page, access):
    data = {
        'number': page.number,
        'background': page.background,
        'background_options': page.background_options or {},
        'locked': page.is_locked,
        'created_by_role': page.created_by_role,
        'student': {'elements': page.student_elements, 'version': page.student_version},
    }
    if access.show_teacher_layer:
        data['teacher'] = {'elements': page.teacher_elements, 'version': page.teacher_version}
    return data


def can_edit_page(page, access, layer):
    """Можно ли писать в этот слой этой страницы."""
    if layer != access.layer:
        return False
    if layer == CanvasPage.ROLE_STUDENT and page.is_locked:
        return False
    return True


def creation_allowed(pages, access, layer):
    """Проверка лимитов перед созданием новой страницы; текст ошибки или None."""
    if len(pages) >= CanvasPage.TOTAL_PAGE_LIMIT:
        return f'Не больше {CanvasPage.TOTAL_PAGE_LIMIT} страниц на задачу'
    if layer == CanvasPage.ROLE_STUDENT:
        active = sum(1 for p in pages if not p.is_locked and p.created_by_role == CanvasPage.ROLE_STUDENT)
        if active >= CanvasPage.STUDENT_PAGE_LIMIT:
            return f'Не больше {CanvasPage.STUDENT_PAGE_LIMIT} страниц'
    else:
        own = sum(1 for p in pages if p.created_by_role == CanvasPage.ROLE_TEACHER)
        if own >= CanvasPage.TEACHER_PAGE_LIMIT:
            return f'Учитель может добавить не больше {CanvasPage.TEACHER_PAGE_LIMIT} страниц'
    return None

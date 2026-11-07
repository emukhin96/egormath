"""Общая логика холста: права, страницы, заморозка."""
from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone

from problems.models import Task
from problems.task_images import classify_task_images

from .models import CanvasPage


def enabled():
    return bool(getattr(settings, 'CANVAS_ENABLED', True))


def lock_assignment_pages(assignment, now=None):
    """Замораживает страницы ученика при отправке работы на проверку."""
    CanvasPage.objects.filter(
        submission__assignment=assignment, locked_at__isnull=True,
    ).update(locked_at=now or timezone.now())
    # update() не даёт сигналов: доска ученика узнаёт о заморозке через файл-версию.
    from livefile import files as livefiles
    for task_id in CanvasPage.objects.filter(submission__assignment=assignment).values_list(
            'submission__task_id', flat=True).distinct():
        livefiles.touch('board', assignment.pk, task_id)


def assignment_page_stats(assignment):
    """Число страниц, последнее изменение и непустые слои ученика по задачам."""
    rows = (CanvasPage.objects
            .filter(submission__assignment=assignment)
            .values('submission__task_id')
            .annotate(n=Count('pk'), updated=Max('student_updated_at'),
                      answered=Count('pk', filter=~Q(student_elements=[]))))
    return {row['submission__task_id']: (row['n'], row['updated'], row['answered']) for row in rows}


def board_tasks(assignments):
    """Задачи, по которым у ученика есть доска: {id назначения: {id задачи}} —
    одним запросом на всю карту ответов (значок «есть доска» в ячейке)."""
    pairs = (CanvasPage.objects.filter(submission__assignment__in=assignments)
             .values_list('submission__assignment_id', 'submission__task_id').distinct())
    boards = {}
    for assignment_id, task_id in pairs:
        boards.setdefault(assignment_id, set()).add(task_id)
    return boards


class Access:
    """Что текущий пользователь может делать с холстом одной задачи."""

    def __init__(self, *, role, can_edit_student, can_edit_teacher, show_teacher_layer,
                 teacher_pages=False):
        self.role = role
        self.can_edit_student = can_edit_student
        self.can_edit_teacher = can_edit_teacher
        self.show_teacher_layer = show_teacher_layer
        self.teacher_pages = teacher_pages   # учитель может добавлять свои страницы

    @property
    def can_add_pages(self):
        if self.role == CanvasPage.ROLE_TEACHER:
            return self.can_edit_teacher and self.teacher_pages
        return self.can_edit_student

    @property
    def layer(self):
        """Слой, который пользователь может править сейчас, или None."""
        if self.role == CanvasPage.ROLE_STUDENT and self.can_edit_student:
            return CanvasPage.ROLE_STUDENT
        if self.role == CanvasPage.ROLE_TEACHER and self.can_edit_teacher:
            return CanvasPage.ROLE_TEACHER
        return None


def assignment_access(assignment, user, role):
    """Слой учителя открыт всегда — учитель пишет на доске и во время работы
    ученика; слой ученика открыт, пока работа редактируема. Ученик видит
    пометки в любом статусе (может скрыть тумблером). Свои страницы учитель
    добавляет только после отправки: иначе нумерация у двоих разъедется."""
    editable = assignment.is_editable_by_student
    if role == CanvasPage.ROLE_STUDENT:
        return Access(
            role=role, can_edit_student=editable, can_edit_teacher=False,
            show_teacher_layer=True)
    return Access(
        role=role, can_edit_student=False, can_edit_teacher=True,
        show_teacher_layer=True, teacher_pages=not editable)


def pages_etag(pages, access, images=()):
    """Подпись ответа для If-None-Match: версии слоёв, права и набор
    доступных иллюстраций задачи; сами элементы не хэшируем."""
    parts = [access.layer or '-', 'a' if access.can_add_pages else '-',
             'i' + ','.join(str(image['id']) for image in images)]
    for page in pages:
        parts.append(f'{page.number}:{page.student_version}:{page.teacher_version}:{int(page.is_locked)}')
    return '"' + '|'.join(parts) + '"'


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
    if not access.can_add_pages:
        return ('Свои страницы учитель добавляет после отправки работы'
                if layer == CanvasPage.ROLE_TEACHER else 'Сейчас страницы добавлять нельзя')
    if layer == CanvasPage.ROLE_STUDENT:
        active = sum(1 for p in pages if not p.is_locked and p.created_by_role == CanvasPage.ROLE_STUDENT)
        if active >= CanvasPage.STUDENT_PAGE_LIMIT:
            return f'Не больше {CanvasPage.STUDENT_PAGE_LIMIT} страниц'
    else:
        own = sum(1 for p in pages if p.created_by_role == CanvasPage.ROLE_TEACHER)
        if own >= CanvasPage.TEACHER_PAGE_LIMIT:
            return f'Учитель может добавить не больше {CanvasPage.TEACHER_PAGE_LIMIT} страниц'
    return None


def statement_images(task_id):
    """Растровые иллюстрации условия задачи — только их можно положить на доску.

    Рисунки, на которые ссылаются лишь ответ или решение (``\\taskpic`` в
    полях материала), сюда не входят: кнопка «Вставить рисунок из условия»
    иначе подкладывала ученику рисунок из решения. Деление — то же, что в
    ученическом листке (``problems.task_images.classify_task_images``).
    PDF Canvas не рисует.
    """
    task = Task.objects.filter(pk=task_id).prefetch_related('images', 'subitems').first()
    if task is None:
        return []
    statement, _ = classify_task_images(task)
    return [image for image in statement if not image.is_pdf]


def task_images(task_id):
    """Иллюстрации условия для кнопки доски. Размер клиент узнаёт сам при загрузке."""
    from django.urls import reverse
    return [{'id': image.pk, 'url': reverse('task_image_file', args=[image.pk]), 'name': image.filename}
            for image in statement_images(task_id)]


def foreign_images(elements, task_id, kept=()):
    """id картинок из элементов, которых нельзя класть на доску этой задачи.

    Разрешены рисунки условия и те, что уже лежат в сохранённом слое
    (``kept``): рисунок решения, вставленный до исправления кнопки, не
    должен навсегда запирать страницу — его можно удалить или оставить.
    """
    wanted = {e['s'] for e in elements if e.get('t') == 'img'}
    if not wanted:
        return set()
    allowed = {image.pk for image in statement_images(task_id)}
    allowed.update(e.get('s') for e in kept if e.get('t') == 'img')
    return wanted - allowed


def attach_image_urls(elements):
    """Адрес файла хранится прямо в элементе (`u`): так рисунок рисует любой
    потребитель JSON — виджет, живой обзор, миниатюра дашборда — без справочника."""
    from django.urls import reverse
    for element in elements:
        if element.get('t') == 'img':
            element['u'] = reverse('task_image_file', args=[element['s']])

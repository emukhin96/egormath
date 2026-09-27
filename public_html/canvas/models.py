"""Холст — векторная мини-доска ученика к задаче.

Одна строка = одна страница. Слой ученика и слой учителя лежат в разных
JSON-полях и никогда не сливаются: каждый редактирует только свой слой,
чужой рисуется подложкой. Формат элементов — canvas/validation.py.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


class CanvasPage(models.Model):
    ROLE_STUDENT = 'student'
    ROLE_TEACHER = 'teacher'
    ROLE_CHOICES = [(ROLE_STUDENT, 'Ученик'), (ROLE_TEACHER, 'Учитель')]

    BG_BLANK = 'blank'
    BG_GRID = 'grid'
    BG_GRID_LARGE = 'grid_large'
    BG_PLANE = 'plane'
    BG_CHOICES = [
        (BG_BLANK, 'Белый'),
        (BG_GRID, 'Клетка'),
        (BG_GRID_LARGE, 'Крупная клетка'),
        (BG_PLANE, 'Координатная плоскость'),
    ]

    # Лимиты — предохранители, а не продуктовые настройки: холст —
    # вспомогательная функция и не должен нагружать сайт.
    STUDENT_PAGE_LIMIT = 5      # незамороженных страниц ученика на задачу
    TEACHER_PAGE_LIMIT = 2      # страниц, созданных учителем
    TOTAL_PAGE_LIMIT = 10       # всего страниц на задачу
    MAX_ELEMENTS = 2000         # элементов в слое
    MAX_POINTS = 4000           # точек в одном штрихе
    MAX_BYTES = 512 * 1024      # JSON одного сохранения

    submission = models.ForeignKey(
        'assignments.Submission', on_delete=models.CASCADE, null=True, blank=True,
        related_name='canvas_pages', verbose_name='Ответ на задачу')
    answer = models.ForeignKey(
        'independentworks.Answer', on_delete=models.CASCADE, null=True, blank=True,
        related_name='canvas_pages', verbose_name='Ответ в самостоятельной')
    number = models.PositiveSmallIntegerField('Номер страницы')
    created_by_role = models.CharField(
        'Кто создал', max_length=8, choices=ROLE_CHOICES, default=ROLE_STUDENT)
    # Проставляется при отправке работы: ученик страницу больше не правит,
    # после возврата продолжает на новой. Учитель пишет пометки поверх.
    locked_at = models.DateTimeField('Заморожена', null=True, blank=True)
    background = models.CharField(
        'Фон', max_length=12, choices=BG_CHOICES, default=BG_GRID)
    background_options = models.JSONField('Параметры фона', default=dict, blank=True)

    student_elements = models.JSONField('Слой ученика', default=list, blank=True)
    student_version = models.PositiveIntegerField('Версия слоя ученика', default=0)
    student_updated_at = models.DateTimeField(
        'Слой ученика изменён', null=True, blank=True, db_index=True)

    teacher_elements = models.JSONField('Слой учителя', default=list, blank=True)
    teacher_version = models.PositiveIntegerField('Версия слоя учителя', default=0)
    teacher_updated_at = models.DateTimeField(
        'Слой учителя изменён', null=True, blank=True)
    teacher_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Пометки оставил')
    created_at = models.DateTimeField('Создана', auto_now_add=True)

    class Meta:
        verbose_name = 'Страница холста'
        verbose_name_plural = 'Страницы холста'
        ordering = ['number', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['submission', 'number'], name='canvas_unique_submission_number'),
            models.UniqueConstraint(
                fields=['answer', 'number'], name='canvas_unique_answer_number'),
            models.CheckConstraint(
                condition=(Q(submission__isnull=False, answer__isnull=True)
                       | Q(submission__isnull=True, answer__isnull=False)),
                name='canvas_exactly_one_owner'),
        ]

    def __str__(self):
        owner = self.submission or self.answer
        return f'Холст {owner} / стр. {self.number}'

    @property
    def is_locked(self):
        return self.locked_at is not None

    @property
    def is_empty(self):
        return not self.student_elements and not self.teacher_elements

    def layer(self, role):
        """(элементы, версия) слоя роли."""
        if role == self.ROLE_TEACHER:
            return self.teacher_elements, self.teacher_version
        return self.student_elements, self.student_version

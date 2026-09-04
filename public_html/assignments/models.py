import io
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from PIL import Image

from problems.models import Task, TaskSubitem
from worksheets.models import Worksheet


class Assignment(models.Model):
    STATUS_ASSIGNED = 'assigned'
    STATUS_SUBMITTED = 'submitted'
    STATUS_RETURNED = 'returned'
    STATUS_REVIEWED = 'reviewed'
    STATUS_CHOICES = [
        (STATUS_ASSIGNED, 'Выдано'),
        (STATUS_SUBMITTED, 'Отправлено на проверку'),
        (STATUS_RETURNED, 'Возвращено на доработку'),
        (STATUS_REVIEWED, 'Проверено'),
    ]

    SCALE_WORDS = 'words'
    SCALE_POINTS = 'points'
    SCALE_CHOICES = [
        (SCALE_WORDS, 'Отметки: отлично/хорошо/средне/плохо'),
        (SCALE_POINTS, 'Числовая шкала (баллы)'),
    ]

    worksheet = models.ForeignKey(
        Worksheet, on_delete=models.CASCADE, related_name='assignments',
        verbose_name='Листок')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='assignments', verbose_name='Ученик')
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='given_assignments', verbose_name='Назначил')
    status = models.CharField(
        'Статус', max_length=10, choices=STATUS_CHOICES,
        default=STATUS_ASSIGNED)
    grade_scale = models.CharField(
        'Шкала оценивания', max_length=10, choices=SCALE_CHOICES,
        default=SCALE_WORDS)
    assigned_at = models.DateTimeField('Выдано', auto_now_add=True)
    due_at = models.DateTimeField('Срок сдачи', null=True, blank=True)
    submitted_at = models.DateTimeField('Отправлено', null=True, blank=True)
    reviewed_at = models.DateTimeField('Проверено', null=True, blank=True)
    hidden_items = models.ManyToManyField(
        'worksheets.WorksheetItem', blank=True,
        related_name='hidden_in_assignments',
        verbose_name='Скрытые задачи',
        help_text='Эти элементы листка не показываются данному ученику '
                  '(страница задания и PDF)')

    class Meta:
        verbose_name = 'Назначение'
        verbose_name_plural = 'Назначения'
        ordering = ['-assigned_at']
        constraints = [
            models.UniqueConstraint(
                fields=['worksheet', 'student'],
                name='unique_assignment_worksheet_student'),
        ]

    def __str__(self):
        return f'{self.worksheet} → {self.student.get_full_name() or self.student.username}'

    @property
    def is_editable_by_student(self):
        """Ученик может менять ответы, пока работа не отправлена на проверку."""
        return self.status in (self.STATUS_ASSIGNED, self.STATUS_RETURNED)

    @property
    def is_overdue(self):
        """Срок прошёл, а работа ещё не сдана. Только подсказка: сдачу не блокирует."""
        return bool(self.due_at) and self.is_editable_by_student \
            and self.due_at < timezone.now()


class Submission(models.Model):
    """Ответ ученика на одну задачу назначения."""

    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name='submissions',
        verbose_name='Назначение')
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name='submissions',
        verbose_name='Задача')
    answer_text = models.TextField('Ответ (текст)', blank=True)
    answer_number = models.CharField(
        'Ответ (число)', max_length=64, blank=True)
    interval_low = models.CharField(
        'Промежуток: от', max_length=64, blank=True)
    interval_high = models.CharField(
        'Промежуток: до', max_length=64, blank=True)
    updated_at = models.DateTimeField('Изменён', auto_now=True)

    class Meta:
        verbose_name = 'Ответ ученика'
        verbose_name_plural = 'Ответы учеников'
        constraints = [
            models.UniqueConstraint(
                fields=['assignment', 'task'],
                name='unique_submission_assignment_task'),
        ]

    def __str__(self):
        return f'{self.assignment} / задача #{self.task_id}'

    @property
    def display_answer(self):
        t = self.task.answer_type
        if t == Task.ANSWER_NUMBER:
            return self.answer_number
        if t == Task.ANSWER_INTERVAL:
            if self.interval_low or self.interval_high:
                return f'от {self.interval_low or "−∞"} до {self.interval_high or "+∞"}'
            return ''
        return self.answer_text

    @property
    def is_empty(self):
        return not (self.display_answer or self.photos.exists()
                    or any(not p.is_empty for p in self.parts.all()))


class SubmissionPart(models.Model):
    """Ответ ученика на один подпункт задачи. Тип ответа — как у задачи."""

    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name='parts',
        verbose_name='Ответ на задачу')
    subitem = models.ForeignKey(
        TaskSubitem, on_delete=models.CASCADE, related_name='submission_parts',
        verbose_name='Подпункт')
    answer_text = models.TextField('Ответ (текст)', blank=True)
    answer_number = models.CharField(
        'Ответ (число)', max_length=64, blank=True)
    interval_low = models.CharField(
        'Промежуток: от', max_length=64, blank=True)
    interval_high = models.CharField(
        'Промежуток: до', max_length=64, blank=True)
    updated_at = models.DateTimeField('Изменён', auto_now=True)

    class Meta:
        verbose_name = 'Ответ на подпункт'
        verbose_name_plural = 'Ответы на подпункты'
        ordering = ['subitem__order', 'subitem_id']
        constraints = [
            models.UniqueConstraint(
                fields=['submission', 'subitem'],
                name='unique_submissionpart_submission_subitem'),
        ]

    def __str__(self):
        return f'{self.submission} / подпункт #{self.subitem_id}'

    @property
    def display_answer(self):
        t = self.submission.task.answer_type
        if t == Task.ANSWER_NUMBER:
            return self.answer_number
        if t == Task.ANSWER_INTERVAL:
            if self.interval_low or self.interval_high:
                return f'от {self.interval_low or "−∞"} до {self.interval_high or "+∞"}'
            return ''
        return self.answer_text

    @property
    def is_empty(self):
        return not self.display_answer


def _photo_upload_to(instance, filename):
    base, _ = os.path.splitext(filename)
    return (f'submission_photos/a{instance.submission.assignment_id}/'
            f't{instance.submission.task_id}/{base[:40]}.jpg')


class SubmissionPhoto(models.Model):
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name='photos',
        verbose_name='Ответ')
    image = models.ImageField('Фото решения', upload_to=_photo_upload_to)
    uploaded_at = models.DateTimeField('Загружено', auto_now_add=True)

    class Meta:
        verbose_name = 'Фото решения'
        verbose_name_plural = 'Фото решений'
        ordering = ['uploaded_at']

    def __str__(self):
        return f'Фото к {self.submission}'

    def save(self, *args, **kwargs):
        if self.image and not self.pk:
            self.image = self._compress(self.image)
        super().save(*args, **kwargs)

    @staticmethod
    def _compress(uploaded):
        """Сжимает фото: max сторона и JPEG q=80, чтобы не забить квоту хостинга."""
        img = Image.open(uploaded)
        img = img.convert('RGB')
        max_side = settings.SUBMISSION_PHOTO_MAX_SIDE
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=80, optimize=True)
        name = os.path.splitext(uploaded.name)[0][:40] + '.jpg'
        return ContentFile(buf.getvalue(), name=name)


class Review(models.Model):
    GRADE_EXCELLENT = 'excellent'
    GRADE_GOOD = 'good'
    GRADE_MEDIUM = 'medium'
    GRADE_POOR = 'poor'
    GRADE_CHOICES = [
        (GRADE_EXCELLENT, 'Отлично'),
        (GRADE_GOOD, 'Хорошо'),
        (GRADE_MEDIUM, 'Средне'),
        (GRADE_POOR, 'Плохо'),
    ]

    submission = models.OneToOneField(
        Submission, on_delete=models.CASCADE, related_name='review',
        verbose_name='Ответ')
    grade_word = models.CharField(
        'Отметка', max_length=10, choices=GRADE_CHOICES, blank=True)
    grade_points = models.DecimalField(
        'Баллы', max_digits=6, decimal_places=2, null=True, blank=True)
    comment = models.TextField('Комментарий', blank=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='reviews', verbose_name='Проверил')
    reviewed_at = models.DateTimeField('Проверено', auto_now=True)

    class Meta:
        verbose_name = 'Проверка ответа'
        verbose_name_plural = 'Проверки ответов'

    def __str__(self):
        return f'Проверка: {self.submission}'

    @property
    def display_grade(self):
        if self.submission.assignment.grade_scale == Assignment.SCALE_POINTS:
            if self.grade_points is not None:
                # без хвостовых нулей
                return f'{self.grade_points.normalize():f}'.rstrip('.') or '0'
            return ''
        return self.get_grade_word_display() if self.grade_word else ''

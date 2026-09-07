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

    CHECK_TEACHER = 'teacher'
    CHECK_AFTER_SUBMIT = 'after_submit'
    CHECK_LIVE = 'live'
    CHECK_CHOICES = [
        (CHECK_TEACHER, 'Только учителю'),
        (CHECK_AFTER_SUBMIT, 'Ученику — после отправки работы'),
        (CHECK_LIVE, 'Ученику — по кнопке «Проверить» (самопроверка)'),
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
    check_visibility = models.CharField(
        'Кому видна автосверка', max_length=12, choices=CHECK_CHOICES,
        default=CHECK_TEACHER,
        help_text='Учитель видит результат всегда; эталон ученику не '
                  'показывается ни в одном режиме. После выдачи не меняется')
    allow_photos = models.BooleanField(
        'Принимать фото решений', default=True,
        help_text='Кнопка загрузки фото у каждой задачи на странице ученика')
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

    @property
    def student_sees_checks(self):
        """Показывать ли ученику результат автосверки в текущем состоянии."""
        if self.check_visibility == self.CHECK_LIVE:
            return True
        if self.check_visibility == self.CHECK_AFTER_SUBMIT:
            return self.status != self.STATUS_ASSIGNED
        return False

    def visible_task_count(self):
        """Сколько задач листка видит этот ученик (без скрытых и удалённых)."""
        return (self.worksheet.items
                .filter(task__isnull=False, deleted_at__isnull=True)
                .exclude(pk__in=self.hidden_items.values('pk'))
                .count())

    def result(self):
        """Итог проверки: (выполнено, всего, процент). Шкалы нет —
        учитель отмечает каждую задачу «выполнено» или нет.

        Числитель и знаменатель — одни и те же видимые элементы листка:
        скрытая или удалённая выполненная задача в кабинет не попадает,
        а повтор одной задачи в листке считается столько раз, сколько
        элементов видит ученик (один Submission на задачу).
        """
        hidden = self.hidden_items.values('pk')
        task_ids = list(
            self.worksheet.items
            .filter(task__isnull=False, deleted_at__isnull=True)
            .exclude(pk__in=hidden)
            .values_list('task_id', flat=True))
        total = len(task_ids)
        done_tasks = set(
            self.submissions.filter(review__done=True)
            .values_list('task_id', flat=True))
        done = sum(1 for task_id in task_ids if task_id in done_tasks)
        percent = round(100 * done / total) if total else 0
        return {'done': done, 'total': total, 'percent': percent}


def locked_check_visibility(worksheet):
    """Режим сверки листка, если он уже кому-то выдан, иначе None.

    Все назначения одного листка живут в одном режиме: иначе ученики
    одного класса оказались бы в неравных условиях, а учитель терял бы
    из виду, кто что видит. После первой выдачи режим не меняется.
    """
    first = worksheet.assignments.order_by('assigned_at').first()
    return first.check_visibility if first else None


def strip_math_delimiters(text):
    """``$…$`` → ``…``: тело формулы для редактора без обрамления."""
    text = (text or '').strip()
    if len(text) >= 2 and text.startswith('$') and text.endswith('$'):
        return text[1:-1].strip()
    return text


def wrap_math(text):
    """Голый LaTeX из редактора формул → ``$…$`` в конвенции answer_latex."""
    text = (text or '').strip()
    if not text or (text.startswith('$') and text.endswith('$')):
        return text
    return f'${text}$'


class AnswerFields(models.Model):
    """Общие поля и представление ответа для задачи и подпункта.

    Поля — TextField: LaTeX из редактора формул (``\\left(-\\infty;\\ 3\\right]``)
    в 64 символа не влезал. Формула (тип ``formula``) хранится в
    ``answer_text`` как ``$…$`` — та же конвенция, что ``Task.answer_latex``.
    """

    CHECK_OK = 'ok'
    CHECK_WRONG = 'wrong'
    CHECK_UNKNOWN = 'unknown'
    CHECK_CHOICES = [
        ('', 'не сверялось'),
        (CHECK_OK, 'верно'),
        (CHECK_WRONG, 'неверно'),
        (CHECK_UNKNOWN, 'не разобрано'),
    ]

    answer_text = models.TextField('Ответ (текст)', blank=True)
    answer_number = models.TextField('Ответ (число)', blank=True)
    interval_low = models.TextField('Промежуток: от', blank=True)
    interval_high = models.TextField('Промежуток: до', blank=True)
    auto_check = models.CharField(
        'Автосверка', max_length=8, blank=True, default='',
        choices=CHECK_CHOICES,
        help_text='Результат сравнения с эталоном; отметку ставит учитель')
    checked_at = models.DateTimeField('Сверено', null=True, blank=True)
    check_revealed = models.BooleanField(
        'Результат показан ученику', default=False,
        help_text='Ученик нажал «Проверить» для этого ответа; '
                  'сбрасывается при смене ответа')
    updated_at = models.DateTimeField('Изменён', auto_now=True)

    class Meta:
        abstract = True

    def run_check(self, reference):
        """Пересчитать auto_check по эталону; возвращает True, если изменился."""
        from django.utils import timezone

        from .check_answer import check_fields
        result = check_fields(self.answer_type, self, reference or '')
        changed = result != self.auto_check
        self.auto_check = result
        self.checked_at = timezone.now()
        return changed

    def check_is_stale(self, task):
        """Эталон могли поправить после сверки — тогда пересчёт."""
        return self.checked_at is None or task.updated_at > self.checked_at

    @property
    def assignment_of(self):
        raise NotImplementedError

    def _student_check_visible(self):
        """Можно ли отдать ученику auto_check (режим назначения — отдельно).

        В live, пока работа редактируется, — только после «Проверить».
        В after_submit результат уже был показан после сдачи: при возврате
        на доработку check_revealed не ставился, и прятать сверку нельзя.
        """
        assignment = self.assignment_of
        if assignment.check_visibility == Assignment.CHECK_LIVE:
            return self.check_revealed or not assignment.is_editable_by_student
        return True

    @property
    def student_check(self):
        """Результат сверки, который можно показать ученику.

        Кому вообще показывать, решает Assignment.student_sees_checks.
        """
        if self._student_check_visible():
            return self.auto_check
        return ''

    @property
    def answer_type(self):
        raise NotImplementedError

    @property
    def display_answer(self):
        t = self.answer_type
        if t == Task.ANSWER_NUMBER:
            return self.answer_number
        if t == Task.ANSWER_INTERVAL:
            if self.interval_low or self.interval_high:
                return f'от {self.interval_low or "−∞"} до {self.interval_high or "+∞"}'
            return ''
        return self.answer_text

    @property
    def formula_latex(self):
        """Начальное значение для <math-field>: формула без ``$``."""
        return strip_math_delimiters(self.answer_text)


class Submission(AnswerFields):
    """Ответ ученика на одну задачу назначения."""

    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name='submissions',
        verbose_name='Назначение')
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name='submissions',
        verbose_name='Задача')
    check_attempts = models.PositiveIntegerField(
        'Проверок', default=0,
        help_text='Сколько раз ученик нажимал «Проверить» (самопроверка)')

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
    def assignment_of(self):
        return self.assignment

    @property
    def answer_type(self):
        return self.task.answer_type

    @property
    def is_empty(self):
        return not (self.display_answer or self.photos.exists()
                    or any(not p.is_empty for p in self.parts.all()))


class SubmissionPart(AnswerFields):
    """Ответ ученика на один подпункт задачи. Тип ответа — как у задачи."""

    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name='parts',
        verbose_name='Ответ на задачу')
    subitem = models.ForeignKey(
        TaskSubitem, on_delete=models.CASCADE, related_name='submission_parts',
        verbose_name='Подпункт')

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
    def assignment_of(self):
        return self.submission.assignment

    @property
    def answer_type(self):
        return self.submission.task.answer_type

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
    """Отметка учителя по одной задаче: выполнена или нет, плюс комментарий.

    Шкал (баллы, «отлично/хорошо») нет: итог работы — число выполненных
    задач и процент (Assignment.result).
    """

    submission = models.OneToOneField(
        Submission, on_delete=models.CASCADE, related_name='review',
        verbose_name='Ответ')
    done = models.BooleanField('Выполнено', default=False)
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

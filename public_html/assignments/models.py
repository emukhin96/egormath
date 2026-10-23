import io
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from PIL import Image

from problems.models import Task, TaskSubitem
from worksheets.models import Worksheet
from workaudit.clipboard import RESTRICT_LABEL, SWAP_LABEL


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
    source_groups = models.ManyToManyField(
        'accounts.StudentGroup', blank=True, related_name='worksheet_assignments',
        verbose_name='Группы при выдаче')
    recipient_origin_known = models.BooleanField(
        'Способ выдачи сохранён', default=False)
    status = models.CharField(
        'Статус', max_length=10, choices=STATUS_CHOICES,
        default=STATUS_ASSIGNED)
    check_visibility = models.CharField(
        'Кому видна автосверка', max_length=12, choices=CHECK_CHOICES,
        default=CHECK_LIVE,
        help_text='Учитель видит результат всегда; правильный ответ ученику не '
                  'показывается ни в одном режиме. После выдачи не меняется')
    restrict_clipboard = models.BooleanField(RESTRICT_LABEL, default=False)
    swap_numbers = models.BooleanField(SWAP_LABEL, default=False)
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

    @classmethod
    def visible_to(cls, user):
        """Назначения, доступные учителю для просмотра и проверки."""
        queryset = cls.objects.all()
        if not getattr(user, 'is_superuser', False):
            queryset = queryset.filter(worksheet__owner=user)
        return queryset

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
        """Итог проверки: зачтённые доли задач, всего и процент.

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
        scores = {r.submission.task_id: r.credit for r in Review.objects.filter(
            submission__assignment=self).select_related('submission')}
        done = sum(scores.get(task_id, 0) for task_id in task_ids)
        percent = round(100 * done / total) if total else 0
        return {'done': done, 'total': total, 'percent': percent}


def locked_check_visibility(worksheet):
    """Режим сверки листка, если он уже кому-то выдан, иначе None.

    Все назначения одного листка живут в одном режиме: иначе ученики
    одного класса оказались бы в неравных условиях, а учитель терял бы
    из виду, кто что видит. При дополнительной выдаче сохраняется общий
    режим; изменить его для всех можно в настройках назначений листка.
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
    answer_json = models.JSONField(
        'Ответ по маске', default=dict, blank=True,
        help_text='Значения слотов маски: {"s1": "10", "s2": "девочек"}')
    auto_check = models.CharField(
        'Автосверка', max_length=8, blank=True, default='',
        choices=CHECK_CHOICES,
        help_text='Результат сравнения с правильным ответом; отметку ставит учитель')
    check_json = models.JSONField(
        'Сверка по слотам', default=dict, blank=True,
        help_text='Результат по каждому слоту маски: {"s1": "ok", "s2": "wrong"}')
    checked_at = models.DateTimeField('Сверено', null=True, blank=True)
    check_revealed = models.BooleanField(
        'Результат показан ученику', default=False,
        help_text='Ученик нажал «Проверить» для этого ответа; '
                  'сбрасывается при смене ответа')
    updated_at = models.DateTimeField('Изменён', auto_now=True)

    class Meta:
        abstract = True

    def run_check(self, reference=None, spec=None, known=None):
        """Пересчитать auto_check; возвращает True, если результат изменился.

        С рабочей маской (``spec``) сверяются слоты ``answer_json`` — итог и
        результат по каждому слоту (``check_json``); ``known`` — результаты
        слотов, чьё значение не менялось, их не пересчитываем. Исторические
        свободные ответы сохраняют прежнюю оценку; reference оставлен для
        совместимости.
        """
        from django.utils import timezone

        from .checks import check_mask
        from .checks.formulas import (UNAVAILABLE_KEY, UNAVAILABLE_LIMIT,
                                      FormulaUnavailable, unavailable_count)
        # Флаг для вызывающего кода: сверка не состоялась по временной причине
        self.check_unavailable = False
        # Старую оценку не пересчитываем, пока ученик не заполнил слоты.
        by_mask = (spec is not None and spec.is_valid
                   and (self.has_mask_values or not self.legacy_answer))
        if by_mask:
            if ((self.check_json or {}).get(UNAVAILABLE_KEY, 0) >= UNAVAILABLE_LIMIT
                    and known is not None):
                # Все значения и эталон прежние: окончательный результат
                # после лимита сбоев не запускает вычислитель снова.
                return False
            try:
                result, per_slot = check_mask(spec, self.answer_json or {}, known=known)
            except FormulaUnavailable as error:
                count = unavailable_count(self.check_json, error)
                if count >= UNAVAILABLE_LIMIT:
                    # Тот же ввод не сверился повторно — это не временная
                    # недоступность, а непосильное выражение: в ручную проверку.
                    changed = self.auto_check != self.CHECK_UNKNOWN
                    self.auto_check = self.CHECK_UNKNOWN
                    self.check_json = {**getattr(error, 'slot_checks', {}),
                                       UNAVAILABLE_KEY: count}
                    self.checked_at = timezone.now()
                    return changed
                # Вычислитель временно недоступен: прежний вердикт и
                # checked_at не трогаем, проверка повторится как устаревшая;
                # счётчик сбоев этого ввода — в check_json.
                self.check_unavailable = True
                self.check_json = {**(self.check_json or {}), UNAVAILABLE_KEY: count}
                return False
        else:
            # Исторический свободный ответ сохраняет прежнюю оценку.
            return False
        changed = result != self.auto_check or per_slot != (self.check_json or {})
        self.auto_check = result
        self.check_json = per_slot
        self.checked_at = timezone.now()
        return changed

    @property
    def mask_owner(self):
        """Задача или подпункт, чья маска описывает этот ответ."""
        raise NotImplementedError

    @property
    def mask_spec(self):
        return self.mask_owner.mask_spec

    @property
    def has_mask_values(self):
        from .checks import has_values
        return has_values(self.answer_json)

    def slot_check(self, name):
        return (self.check_json or {}).get(name, '')

    def slot_value(self, name):
        return (self.answer_json or {}).get(name, '')

    @property
    def student_slot_checks(self):
        """Результаты по слотам, которые можно показать ученику, — с тем же
        правилом раскрытия, что и student_check."""
        if self._student_check_visible():
            return self.check_json or {}
        return {}

    def mask_fragments(self, prefix, for_teacher=False):
        """Данные для ``_mask.html``: слоты со значениями ученика и бейджами
        (учителю — все, ученику — только раскрытые). None — маски нет."""
        spec = self.mask_spec
        if spec is None or not spec.is_valid:
            return None
        from .checks import render_fragments
        checks = (self.check_json or {}) if for_teacher else self.student_slot_checks
        return render_fragments(spec, prefix, self.answer_json or {}, checks,
                                seed=prefix)

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
        if not assignment.student_sees_checks:
            return False
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
    def display_answer(self):
        if self.answer_json:
            spec = self.mask_spec
            if spec is not None and self.has_mask_values:
                from .checks import filled_text
                return filled_text(spec, self.answer_json)
        return self.legacy_answer

    @property
    def legacy_answer(self):
        """Ответ в старых свободных полях (до масок / без маски)."""
        return self.answer_text or self.answer_number or (
            f'от {self.interval_low or "−∞"} до {self.interval_high or "+∞"}'
            if self.interval_low or self.interval_high else '')

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
    def mask_owner(self):
        return self.task

    @property
    def is_empty(self):
        return not (self.display_answer or self.photos.exists()
                    or any(not p.is_empty for p in self.parts.all()))


class SubmissionPart(AnswerFields):
    """Ответ ученика на один подпункт задачи. Маска принадлежит подпункту."""

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
    def mask_owner(self):
        return self.subitem

    @property
    def is_empty(self):
        return not self.display_answer


class SubmissionCheckAttempt(models.Model):
    """Неизменяемый снимок одного нажатия «Проверить»."""

    RESULT_OK = 'ok'
    RESULT_WRONG = 'wrong'
    RESULT_UNKNOWN = 'unknown'
    RESULT_INCOMPLETE = 'incomplete'
    RESULT_CHOICES = [
        (RESULT_OK, 'Верно'),
        (RESULT_WRONG, 'Неверно'),
        (RESULT_UNKNOWN, 'Не удалось проверить'),
        (RESULT_INCOMPLETE, 'Ответ заполнен частично'),
    ]

    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name='check_history',
        verbose_name='Ответ')
    number = models.PositiveIntegerField('Номер попытки')
    result = models.CharField(
        'Результат', max_length=12, choices=RESULT_CHOICES)
    snapshot = models.JSONField('Снимок ответа', default=dict)
    created_at = models.DateTimeField('Время попытки', auto_now_add=True)

    class Meta:
        verbose_name = 'Попытка самопроверки'
        verbose_name_plural = 'Попытки самопроверки'
        ordering = ['number']
        constraints = [
            models.UniqueConstraint(
                fields=['submission', 'number'],
                name='unique_check_attempt_submission_number'),
        ]

    def __str__(self):
        return f'{self.submission} / проверка #{self.number}'


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
    """Оценка учителя по задаче и комментарий. Итог учитывает доли задач.
    """

    submission = models.OneToOneField(
        Submission, on_delete=models.CASCADE, related_name='review',
        verbose_name='Ответ')
    GRADE_CHOICES = [('+', 'Полностью правильно'), ('.+', 'Верно, мелкие недочёты'),
                     ('+-', 'Незначительная ошибка'), ('=', 'Половина решения'),
                     ('-+', 'Существенное продвижение'), ('.-', 'Есть попытка'),
                     ('-', 'Не решено'), ('0', 'Не приступал')]
    SYMBOLS = {'=': '干', '+-': '±', '.-': '.–', '-': '–', '-+': '–+'}

    @classmethod
    def grade_options(cls):
        return [(value, label, cls.SYMBOLS.get(value, value)) for value, label in cls.GRADE_CHOICES]

    @property
    def grade_symbol(self):
        return self.SYMBOLS.get(self.grade, self.grade)

    CREDITS = {'+': 1, '.+': 1, '+-': .75, '=': .5}
    grade = models.CharField('Оценка', max_length=2, choices=GRADE_CHOICES, blank=True, default='')
    # Совместимость с прежними сохранёнными проверками.
    done = models.BooleanField('Выполнено', default=False)

    @property
    def credit(self):
        return self.CREDITS.get(self.grade, 0) if self.grade else int(self.done)

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

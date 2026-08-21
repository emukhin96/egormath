import secrets

from django.conf import settings
from django.db import models

from problems.models import Task, TaskSubitem, Topic


def _new_token():
    return secrets.token_urlsafe(16)


class Worksheet(models.Model):
    title = models.CharField('Название листка', max_length=190)
    grade_label = models.CharField(
        'Левый верхний подзаголовок', max_length=100, blank=True,
        help_text='Второй аргумент \\bighead, например «8 класс»')
    subtitle = models.CharField('Подзаголовок', max_length=190, blank=True)
    grade = models.PositiveSmallIntegerField(
        'Класс', choices=Task.GRADE_CHOICES, null=True, blank=True,
        help_text='Для фильтров в каталоге; в PDF не выводится')
    topics = models.ManyToManyField(
        Topic, blank=True, related_name='worksheets', verbose_name='Темы',
        help_text='Для фильтров в каталоге (темы задач учитываются '
                  'автоматически)')
    comment = models.TextField(
        'Комментарий', blank=True,
        help_text='Виден только вам в списке листков; '
                  'в листке и PDF не отображается')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='worksheets', verbose_name='Владелец')
    author_name = models.CharField(
        'Правый верхний подзаголовок', max_length=190, blank=True,
        help_text='Третий аргумент \\bighead; если пусто — имя владельца')
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Изменён', auto_now=True)

    class Meta:
        verbose_name = 'Листок'
        verbose_name_plural = 'Листки'
        ordering = ['-updated_at']

    def __str__(self):
        return self.title

    @property
    def display_author(self):
        return self.author_name or self.owner.get_full_name() or self.owner.username

    def ordered_items(self):
        return (self.items.select_related('task')
                .prefetch_related('task__subitems', 'task__images', 'subitems')
                .order_by('order', 'id'))

    def duplicate(self):
        """Полная копия листка со всеми элементами и настройками."""
        copy = Worksheet.objects.get(pk=self.pk)
        copy.pk = None
        copy.title = f'{self.title} (копия)'
        copy.save()
        for item in self.items.all():
            selected = list(item.subitems.all())
            item.pk = None
            item.worksheet = copy
            item.save()
            if selected:
                item.subitems.set(selected)
        return copy


class WorksheetItem(models.Model):
    worksheet = models.ForeignKey(
        Worksheet, on_delete=models.CASCADE, related_name='items',
        verbose_name='Листок')
    task = models.ForeignKey(
        Task, on_delete=models.PROTECT, related_name='worksheet_items',
        null=True, blank=True, verbose_name='Задача')
    text_latex = models.TextField(
        'Произвольный текст (LaTeX)', blank=True,
        help_text='Элемент-текст между задачами (в PDF — \\plaintext)')
    order = models.PositiveIntegerField('Порядок', default=0)
    rubric = models.CharField(
        'Рубрика', max_length=190, blank=True,
        help_text='Элемент-заголовок (\\rubr): задачи ниже относятся '
                  'к этой рубрике до следующей')
    rubric_note = models.CharField(
        'Пояснение к рубрике', max_length=400, blank=True)
    stars_override = models.PositiveSmallIntegerField(
        'Сложность в листке', choices=Task.STARS_CHOICES,
        null=True, blank=True,
        help_text='Пусто — как у задачи в базе')
    columns_override = models.PositiveSmallIntegerField(
        'Колонки подпунктов в листке', null=True, blank=True,
        help_text='Пусто — как у задачи в базе')
    all_subitems = models.BooleanField(
        'Все подпункты', default=True,
        help_text='Включать все подпункты задачи (в т.ч. добавленные позже)')
    subitems = models.ManyToManyField(
        TaskSubitem, blank=True, related_name='worksheet_items',
        verbose_name='Выбранные подпункты',
        help_text='Используется, когда «Все подпункты» выключено')

    class Meta:
        verbose_name = 'Элемент листка'
        verbose_name_plural = 'Элементы листка'
        ordering = ['order', 'id']
        constraints = [
            models.CheckConstraint(
                check=(models.Q(task__isnull=False)
                       | ~models.Q(text_latex='')
                       | ~models.Q(rubric='')),
                name='worksheetitem_task_or_text'),
        ]

    def __str__(self):
        if self.task_id:
            return f'{self.worksheet}: {self.order}. задача #{self.task_id}'
        if self.rubric:
            return f'{self.worksheet}: {self.order}. рубрика «{self.rubric}»'
        return f'{self.worksheet}: {self.order}. текст'

    @property
    def is_rubric(self):
        return self.task_id is None and bool(self.rubric)

    @property
    def is_text(self):
        return self.task_id is None and not self.rubric

    @property
    def effective_stars(self):
        if self.stars_override is not None:
            return self.stars_override
        return self.task.stars

    @property
    def effective_columns(self):
        if self.columns_override is not None:
            return self.columns_override
        return self.task.columns

    def selected_subitems(self):
        """Подпункты этого элемента: все задачи или явно выбранные."""
        if self.task_id is None:
            return []
        if self.all_subitems:
            return list(self.task.subitems.all())
        selected = sorted(self.subitems.all(), key=lambda s: (s.order, s.pk))
        return selected


class WorksheetPdf(models.Model):
    """Кэш сгенерированных PDF: один на (листок, вариант, хеш содержимого)."""

    VARIANT_STUDENT = 'student'
    VARIANT_ANSWERS = 'answers'
    VARIANT_TEACHER = 'teacher'
    VARIANT_CHOICES = [
        (VARIANT_STUDENT, 'Для ученика (без ответов)'),
        (VARIANT_ANSWERS, 'С ответами'),
        (VARIANT_TEACHER, 'Для учителя (ответы и решения)'),
    ]

    worksheet = models.ForeignKey(
        Worksheet, on_delete=models.CASCADE, related_name='pdfs',
        verbose_name='Листок')
    variant = models.CharField(
        'Вариант', max_length=10, choices=VARIANT_CHOICES)
    content_hash = models.CharField('Хеш содержимого', max_length=64)
    file = models.FileField('Файл', upload_to='worksheet_pdfs/%Y/%m/')
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'PDF листка'
        verbose_name_plural = 'PDF листков'
        constraints = [
            models.UniqueConstraint(
                fields=['worksheet', 'variant', 'content_hash'],
                name='unique_worksheet_pdf'),
        ]

    def __str__(self):
        return f'{self.worksheet} [{self.variant}]'


class ShareLink(models.Model):
    worksheet = models.ForeignKey(
        Worksheet, on_delete=models.CASCADE, related_name='share_links',
        verbose_name='Листок')
    token = models.CharField(
        'Токен', max_length=32, unique=True, default=_new_token)
    is_active = models.BooleanField('Активна', default=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True)

    class Meta:
        verbose_name = 'Публичная ссылка'
        verbose_name_plural = 'Публичные ссылки'

    def __str__(self):
        state = 'активна' if self.is_active else 'отключена'
        return f'{self.worksheet} /s/{self.token}/ ({state})'

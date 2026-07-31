import secrets

from django.conf import settings
from django.db import models

from problems.models import Task


def _new_token():
    return secrets.token_urlsafe(16)


class Worksheet(models.Model):
    title = models.CharField('Название листка', max_length=190)
    grade_label = models.CharField(
        'Класс / курс', max_length=100, blank=True,
        help_text='Второй аргумент \\bighead, например «8 класс»')
    subtitle = models.CharField('Подзаголовок', max_length=190, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='worksheets', verbose_name='Владелец')
    author_name = models.CharField(
        'Автор (в шапке PDF)', max_length=190, blank=True,
        help_text='Если пусто — имя владельца')
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
        return self.items.select_related('task').order_by('order', 'id')


class WorksheetItem(models.Model):
    worksheet = models.ForeignKey(
        Worksheet, on_delete=models.CASCADE, related_name='items',
        verbose_name='Листок')
    task = models.ForeignKey(
        Task, on_delete=models.PROTECT, related_name='worksheet_items',
        verbose_name='Задача')
    order = models.PositiveIntegerField('Порядок', default=0)
    rubric = models.CharField(
        'Рубрика', max_length=190, blank=True,
        help_text='Название рубрики (\\rubr). Подряд идущие задачи с одной '
                  'рубрикой группируются; пустая — продолжение предыдущей')
    rubric_note = models.CharField(
        'Пояснение к рубрике', max_length=400, blank=True)

    class Meta:
        verbose_name = 'Задача в листке'
        verbose_name_plural = 'Задачи в листке'
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.worksheet}: {self.order}. задача #{self.task_id}'


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

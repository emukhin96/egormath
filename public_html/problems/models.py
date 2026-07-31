from django.conf import settings
from django.db import models

from .latex_utils import strip_latex


class Topic(models.Model):
    name = models.CharField('Название', max_length=150)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='children', verbose_name='Родительская тема')
    order = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Тема'
        verbose_name_plural = 'Темы'
        ordering = ['order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'parent'], name='unique_topic_name_parent'),
        ]

    def __str__(self):
        if self.parent:
            return f'{self.parent} / {self.name}'
        return self.name

    def descendants_ids(self):
        """id темы и всех подтем (рекурсивно). Дерево маленькое — рекурсия ок."""
        ids = [self.pk]
        for child in self.children.all():
            ids.extend(child.descendants_ids())
        return ids


class Tag(models.Model):
    name = models.CharField('Название', max_length=64, unique=True)

    class Meta:
        verbose_name = 'Тег'
        verbose_name_plural = 'Теги'
        ordering = ['name']

    def __str__(self):
        return self.name


class Source(models.Model):
    title = models.CharField('Название', max_length=190)
    author = models.CharField('Автор(ы)', max_length=190, blank=True)
    year = models.PositiveSmallIntegerField('Год издания', null=True, blank=True)

    class Meta:
        verbose_name = 'Источник (учебник/задачник)'
        verbose_name_plural = 'Источники (учебники/задачники)'
        ordering = ['title']

    def __str__(self):
        if self.author:
            return f'{self.author}. {self.title}'
        return self.title


class Task(models.Model):
    ANSWER_TEXT = 'text'
    ANSWER_NUMBER = 'number'
    ANSWER_INTERVAL = 'interval'
    ANSWER_TYPE_CHOICES = [
        (ANSWER_TEXT, 'Текст'),
        (ANSWER_NUMBER, 'Число'),
        (ANSWER_INTERVAL, 'Числовой промежуток'),
    ]

    GRADE_CHOICES = [(g, f'{g} класс') for g in range(1, 12)]
    STARS_CHOICES = [(i, '★' * i if i else 'без звёзд') for i in range(4)]

    text_latex = models.TextField(
        'Условие (LaTeX)',
        help_text='Текст задачи в LaTeX, как для пакета egor')
    subitems_latex = models.TextField(
        'Подпункты (LaTeX)', blank=True,
        help_text='Содержимое 4-го аргумента \\task: строки \\item а; \\item б; ...')
    columns = models.PositiveSmallIntegerField(
        'Колонки подпунктов', default=0,
        help_text='0 — подпунктов нет; N — подпункты в N колонок')
    answer_latex = models.TextField('Ответ (LaTeX)', blank=True)
    solution_latex = models.TextField('Решение (LaTeX)', blank=True)
    text_plain = models.TextField(
        'Текст для поиска', blank=True, editable=False,
        help_text='Автоматически: условие без LaTeX-команд')
    grade_level = models.PositiveSmallIntegerField(
        'Класс изучения', choices=GRADE_CHOICES, null=True, blank=True)
    stars = models.PositiveSmallIntegerField(
        'Сложность (звёзды)', choices=STARS_CHOICES, default=0)
    answer_type = models.CharField(
        'Тип ответа ученика', max_length=10,
        choices=ANSWER_TYPE_CHOICES, default=ANSWER_TEXT)
    topics = models.ManyToManyField(
        Topic, blank=True, related_name='tasks', verbose_name='Темы')
    tags = models.ManyToManyField(
        Tag, blank=True, related_name='tasks', verbose_name='Теги')
    sources = models.ManyToManyField(
        Source, through='TaskSource', related_name='tasks',
        verbose_name='Источники')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_tasks',
        verbose_name='Автор')
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    updated_at = models.DateTimeField('Изменена', auto_now=True)

    class Meta:
        verbose_name = 'Задача'
        verbose_name_plural = 'Задачи'
        ordering = ['-created_at']

    def __str__(self):
        short = self.text_plain or strip_latex(self.text_latex)
        return f'#{self.pk}: {short[:80]}'

    def save(self, *args, **kwargs):
        self.text_plain = strip_latex(self.text_latex)
        super().save(*args, **kwargs)


class TaskSource(models.Model):
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name='source_refs',
        verbose_name='Задача')
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name='task_refs',
        verbose_name='Источник')
    number = models.CharField(
        'Номер в источнике', max_length=32,
        help_text='Например: 123, 5.17а, №452')

    class Meta:
        verbose_name = 'Номер задачи в источнике'
        verbose_name_plural = 'Номера задач в источниках'
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'source'], name='unique_task_source'),
        ]

    def __str__(self):
        return f'{self.source} № {self.number}'

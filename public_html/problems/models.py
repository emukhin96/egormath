import io
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.validators import FileExtensionValidator
from django.db import models
from PIL import Image

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
    columns = models.PositiveSmallIntegerField(
        'Колонки подпунктов', default=0,
        help_text='0 — подпункты одной колонкой; N — подпункты в N колонок')
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
    variant_of = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='variants', verbose_name='Вариант задачи',
        help_text='«Локальная» копия для конкретного листка: '
                  'в каталоге не показывается')
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

    @property
    def has_subitem_answers(self):
        return any(s.answer_latex.strip() for s in self.subitems.all())

    def make_variant(self, user=None):
        """Скрытая копия задачи для «локальной» правки в одном листке."""
        original = self
        copy = Task.objects.get(pk=self.pk)
        copy.pk = None
        copy.variant_of = original.variant_of or original
        if user is not None:
            copy.created_by = user
        copy.save()
        copy.topics.set(original.topics.all())
        copy.tags.set(original.tags.all())
        for ref in original.source_refs.all():
            TaskSource.objects.create(
                task=copy, source=ref.source, number=ref.number)
        for sub in original.subitems.all():
            TaskSubitem.objects.create(
                task=copy, order=sub.order,
                text_latex=sub.text_latex, answer_latex=sub.answer_latex)
        for img in original.images.all():
            # Копия строки ссылается на тот же файл в storage
            copy.images.create(image=img.image.name, order=img.order)
        return copy


class TaskImage(models.Model):
    """Иллюстрация к задаче.

    В PDF: \\taskpic{файл} внутри условия, блок картинок выпускается
    внизу страницы командой \\flushpics (механика пакета egor).
    Кроме растровых картинок поддерживается векторная графика в PDF
    (\\includegraphics в lualatex понимает .pdf) — такие файлы
    не сжимаются и в вебе показываются ссылкой.
    """

    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name='images',
        verbose_name='Задача')
    image = models.FileField(
        'Файл', upload_to='task_images/',
        validators=[FileExtensionValidator(['png', 'jpg', 'jpeg', 'pdf'])],
        help_text='PNG/JPEG или векторный PDF')
    order = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Картинка задачи'
        verbose_name_plural = 'Картинки задач'
        ordering = ['order', 'id']

    def __str__(self):
        return f'Задача #{self.task_id}: {self.filename}'

    @property
    def filename(self):
        """Имя файла в storage — оно же имя для \\taskpic и assets API."""
        return os.path.basename(self.image.name)

    @property
    def is_pdf(self):
        return self.image.name.lower().endswith('.pdf')

    def save(self, *args, **kwargs):
        # Сжимаем только свежезагруженный растровый файл
        # (не PDF и не ссылку на существующий файл)
        if (self.image and not self.pk and not self.image._committed
                and not self.image.name.lower().endswith('.pdf')):
            self.image = self._compress(self.image)
        super().save(*args, **kwargs)

    @staticmethod
    def _compress(uploaded):
        """Ограничивает размер; PNG (схемы, прозрачность) остаётся PNG."""
        img = Image.open(uploaded)
        fmt = img.format
        max_side = settings.SUBMISSION_PHOTO_MAX_SIDE
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        base = os.path.splitext(os.path.basename(uploaded.name))[0][:40]
        if fmt == 'PNG':
            img.save(buf, format='PNG', optimize=True)
            name = base + '.png'
        else:
            img.convert('RGB').save(
                buf, format='JPEG', quality=85, optimize=True)
            name = base + '.jpg'
        return ContentFile(buf.getvalue(), name=name)


class TaskSubitem(models.Model):
    """Подпункт задачи (в PDF — \\item внутри 4-го аргумента \\task)."""

    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name='subitems',
        verbose_name='Задача')
    order = models.PositiveIntegerField('Порядок', default=0)
    text_latex = models.TextField('Текст подпункта (LaTeX)')
    answer_latex = models.TextField('Ответ (LaTeX)', blank=True)

    class Meta:
        verbose_name = 'Подпункт задачи'
        verbose_name_plural = 'Подпункты задач'
        ordering = ['order', 'id']

    def __str__(self):
        return f'Задача #{self.task_id}, подпункт {self.order}: ' \
               f'{strip_latex(self.text_latex)[:40]}'


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

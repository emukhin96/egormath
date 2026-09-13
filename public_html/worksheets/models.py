import re
import secrets

from django.conf import settings
from django.db import models

from problems.models import (GradeBand, Task, TaskSubitem, Topic,
                             normalize_grade_level)


def _new_token():
    return secrets.token_urlsafe(16)


_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def _translit(text):
    """Транслитерация для имён файлов: кириллица → латиница, без спецсимволов."""
    out = ''.join(_TRANSLIT.get(ch, ch) for ch in text.lower())
    return re.sub(r'[^a-z0-9]+', '', out)


class Worksheet(models.Model):
    title = models.CharField('Название листка', max_length=190)
    grade_label = models.CharField(
        'Левый верхний подзаголовок', max_length=100, blank=True,
        help_text='Второй аргумент \\bighead, например «8 класс»')
    subtitle = models.CharField('Подзаголовок', max_length=190, blank=True)
    grade = models.PositiveSmallIntegerField(
        'Класс', choices=Task.GRADE_FIELD_CHOICES, null=True, blank=True,
        help_text='Для фильтров в каталоге; в PDF не выводится')
    topics = models.ManyToManyField(
        Topic, blank=True, related_name='worksheets', verbose_name='Темы',
        help_text='Для фильтров в каталоге (темы задач учитываются '
                  'автоматически)')
    grade_bands = models.ManyToManyField(
        GradeBand, blank=True, related_name='worksheets',
        verbose_name='Классы')
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
    pdf_basename = models.CharField(
        'Имя PDF-файла', max_length=80, blank=True,
        help_text='Без расширения, например alg8-kv_ur; '
                  'пусто — сгенерируется из темы, класса и названия')
    student_pdf_options = models.JSONField(
        'Оформление PDF для ученика', default=dict, blank=True,
        help_text='Последние параметры ученического PDF, собранного учителем')
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Изменён', auto_now=True)

    class Meta:
        verbose_name = 'Листок'
        verbose_name_plural = 'Листки'
        ordering = ['-updated_at']

    def __str__(self):
        return self.title

    @classmethod
    def visible_to(cls, user):
        """Листки, которыми учитель вправе полноценно управлять."""
        queryset = cls.objects.all()
        if not getattr(user, 'is_superuser', False):
            queryset = queryset.filter(owner=user)
        return queryset

    @property
    def grade_option(self):
        """Значение селекта класса: 11 из старых данных = 10–11."""
        return normalize_grade_level(self.grade)

    @property
    def display_author(self):
        return self.author_name or self.owner.get_full_name() or self.owner.username

    def ordered_items(self):
        return (self.items.filter(deleted_at__isnull=True)
                .select_related('task')
                .prefetch_related('task__subitems', 'task__images', 'subitems')
                .order_by('order', 'id'))

    def _auto_pdf_basename(self):
        """Имя файла по шаблону «тема + класс — короткое название»: alg8-kv_ur."""
        topic = self.topics.order_by('pk').first()
        prefix = _translit(topic.name)[:3] if topic else 'list'
        grade = str(self.grade) if self.grade else ''
        words = re.findall(r'[а-яёa-z0-9]+', self.title.lower())[:3]
        short = '_'.join(filter(None, (_translit(w)[:2] for w in words)))
        return f'{prefix}{grade}-{short}' if short else f'{prefix}{grade}'

    def pdf_filename(self, variant=''):
        """Имя PDF: ручное pdf_basename или автогенерация + суффикс варианта."""
        base = self.pdf_basename.strip() or self._auto_pdf_basename()
        suffix = {'answers': '-otvety', 'teacher': '-uchitel'}.get(variant, '')
        return f'{base}{suffix}.pdf'

    def beamer_filename(self):
        """Имя PDF презентации — тот же базис, что у листка."""
        base = self.pdf_basename.strip() or self._auto_pdf_basename()
        return f'{base}-prezentaciya.pdf'

    def duplicate(self, owner=None):
        """Полная копия листка со всеми элементами и настройками."""
        copy = Worksheet.objects.get(pk=self.pk)
        copy.pk = None
        copy.title = f'{self.title} (копия)'
        if owner is not None:
            copy.owner = owner
        copy.save()
        copy.topics.set(self.topics.all())
        copy.grade_bands.set(self.grade_bands.all())
        for item in self.items.filter(deleted_at__isnull=True):
            selected = list(item.subitems.all())
            item.pk = None
            item.worksheet = copy
            item.save()
            if selected:
                item.subitems.set(selected)
        return copy


class Collection(models.Model):
    """Каталожная подборка с полноценным Worksheet как содержимым."""

    worksheet = models.OneToOneField(
        Worksheet, on_delete=models.CASCADE, related_name='collection',
        verbose_name='Листок-содержимое')
    source = models.ForeignKey(
        'problems.Source', on_delete=models.PROTECT,
        related_name='collections', verbose_name='Источник')
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='children', verbose_name='Родительская подборка')
    locator = models.CharField('Ключ в источнике', max_length=500)
    source_path = models.JSONField(
        'Путь в источнике', default=list, blank=True)
    order = models.PositiveIntegerField('Порядок', default=0)
    is_published = models.BooleanField('Опубликована', default=False)

    class Meta:
        verbose_name = 'Подборка'
        verbose_name_plural = 'Подборки'
        ordering = ['source', 'order', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'locator'],
                name='unique_collection_source_locator'),
        ]

    def __str__(self):
        return self.worksheet.title


class WorksheetItem(models.Model):
    # Стили текстового элемента — команды пакета egor
    TEXT_STYLE_CHOICES = [
        ('plain', 'Обычный'),
        ('rule', 'Правило'),
        ('light', 'Тонкая линия'),
        ('memo', 'Памятка'),
    ]

    worksheet = models.ForeignKey(
        Worksheet, on_delete=models.CASCADE, related_name='items',
        verbose_name='Листок')
    task = models.ForeignKey(
        Task, on_delete=models.PROTECT, related_name='worksheet_items',
        null=True, blank=True, verbose_name='Задача')
    text_latex = models.TextField(
        'Произвольный текст (LaTeX)', blank=True,
        help_text='Элемент-текст между задачами (в PDF — \\plaintext)')
    text_style = models.CharField(
        'Стиль текста', max_length=10, choices=TEXT_STYLE_CHOICES,
        default='plain',
        help_text='Оформление текстового элемента: \\plaintext, \\ruletext, '
                  '\\lighttext или \\memotext пакета egor')
    order = models.PositiveIntegerField('Порядок', default=0)
    rubric = models.CharField(
        'Рубрика', max_length=190, blank=True,
        help_text='Элемент-заголовок (\\rubr): задачи ниже относятся '
                  'к этой рубрике до следующей')
    rubric_note = models.TextField(
        'Пояснение к рубрике', blank=True)
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
    deleted_at = models.DateTimeField(
        'Удалено', null=True, blank=True,
        help_text='Мягкое удаление: элемент можно вернуть кнопкой '
                  '«Отменить» до следующего удаления')

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
    filter_key = models.CharField(
        'Ключ скрытий', max_length=40, blank=True, default='',
        help_text='Пусто — полный листок; иначе идентификатор набора скрытых элементов')
    file = models.FileField('Файл', upload_to='worksheet_pdfs/%Y/%m/')
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'PDF листка'
        verbose_name_plural = 'PDF листков'
        constraints = [
            models.UniqueConstraint(
                fields=['worksheet', 'variant', 'filter_key', 'content_hash'],
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
    hidden_items = models.ManyToManyField(
        WorksheetItem, blank=True, related_name='hidden_in_links',
        verbose_name='Скрытые задачи',
        help_text='Эти элементы листка не показываются по данной ссылке '
                  '(страница и PDF)')

    class Meta:
        verbose_name = 'Публичная ссылка'
        verbose_name_plural = 'Публичные ссылки'

    def __str__(self):
        state = 'активна' if self.is_active else 'отключена'
        return f'{self.worksheet} /s/{self.token}/ ({state})'


class PdfCompileLock(models.Model):
    """Межпроцессный lock «одна черновая сборка PDF на пользователя».

    Кэш по умолчанию (LocMemCache) свой в каждом WSGI-процессе и не даёт
    общей блокировки, поэтому lock хранится в БД: уникальность user
    атомарно гарантируется СУБД. Протухшие записи (упавший процесс)
    удаляются при следующей попытке взять lock.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        verbose_name='Пользователь')
    created_at = models.DateTimeField('Взят', auto_now_add=True)

    class Meta:
        verbose_name = 'Блокировка сборки PDF'
        verbose_name_plural = 'Блокировки сборки PDF'

    def __str__(self):
        return f'Сборка PDF: {self.user} с {self.created_at:%H:%M:%S}'

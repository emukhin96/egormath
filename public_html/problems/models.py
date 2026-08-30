import io
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.validators import FileExtensionValidator
from django.db import models
from PIL import Image

from .latex_utils import strip_latex


class Topic(models.Model):
    name = models.CharField('Название', max_length=255)
    code = models.CharField(
        'Код', max_length=24, unique=True, null=True, blank=True,
        help_text='ARI, ARI.02, ARI.02.03')
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
        if self.code:
            return f'{self.code} {self.name}'
        if self.parent:
            return f'{self.parent} / {self.name}'
        return self.name

    def descendants_ids(self):
        """id темы и всех подтем (рекурсивно). Дерево маленькое — рекурсия ок."""
        ids = [self.pk]
        for child in self.children.all():
            ids.extend(child.descendants_ids())
        return ids


def topic_tree():
    """Все темы плоским списком в порядке дерева; у каждой — атрибут depth.

    Для чекбоксов/списков, где нужно показать дерево любой глубины
    (диалоги выбора тем). Один запрос к БД.
    """
    by_parent = {}
    for topic in Topic.objects.all():
        by_parent.setdefault(topic.parent_id, []).append(topic)

    def walk(parent_id, depth):
        for topic in by_parent.get(parent_id, []):
            topic.depth = depth
            topic.indent = '— ' * depth  # префикс для <option> в select
            yield topic
            yield from walk(topic.pk, depth + 1)

    return list(walk(None, 0))


def normalize_grade_level(value):
    """11 и 10 — одна метка 10–11; иное без изменений."""
    if value == 11:
        return 10
    return value


class GradeBand(models.Model):
    """Дискретная метка класса: 5, 6, …, 10–11. Не диапазон."""

    code = models.CharField('Код', max_length=16, unique=True)
    name = models.CharField('Название', max_length=32)
    order = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Класс (метка)'
        verbose_name_plural = 'Классы (метки)'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class FacetType(models.Model):
    MODE_SINGLE = 'SINGLE'
    MODE_MULTIPLE = 'MULTIPLE'
    MODE_CHOICES = [
        (MODE_SINGLE, 'Один'),
        (MODE_MULTIPLE, 'Несколько'),
    ]

    code = models.CharField('Код', max_length=32, unique=True)
    name = models.CharField('Название', max_length=100)
    selection_mode = models.CharField(
        'Режим выбора', max_length=10,
        choices=MODE_CHOICES, default=MODE_MULTIPLE)
    order = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Тип фасета'
        verbose_name_plural = 'Типы фасетов'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class FacetValue(models.Model):
    facet_type = models.ForeignKey(
        FacetType, on_delete=models.PROTECT,
        related_name='values', verbose_name='Тип')
    code = models.CharField('Код', max_length=64)
    name = models.CharField('Название', max_length=160)
    order = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Значение фасета'
        verbose_name_plural = 'Значения фасетов'
        ordering = ['facet_type', 'order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['facet_type', 'code'], name='unique_facet_value_code'),
        ]

    def __str__(self):
        return f'{self.facet_type.code}:{self.name}'


class ExamModel(models.Model):
    TYPE_OGE = 'OGE'
    TYPE_EGE_BASE = 'EGE_BASE'
    TYPE_EGE_PROFILE = 'EGE_PROFILE'
    TYPE_CHOICES = [
        (TYPE_OGE, 'ОГЭ'),
        (TYPE_EGE_BASE, 'ЕГЭ база'),
        (TYPE_EGE_PROFILE, 'ЕГЭ профиль'),
    ]

    code = models.CharField('Код', max_length=40, unique=True)
    exam_type = models.CharField(
        'Экзамен', max_length=16, choices=TYPE_CHOICES)
    exam_year = models.PositiveSmallIntegerField('Год модели')
    name = models.CharField('Название', max_length=160)

    class Meta:
        verbose_name = 'Модель экзамена'
        verbose_name_plural = 'Модели экзаменов'
        ordering = ['exam_type', '-exam_year']
        constraints = [
            models.UniqueConstraint(
                fields=['exam_type', 'exam_year'],
                name='unique_exam_type_year'),
        ]

    def __str__(self):
        return self.name


class ExamItem(models.Model):
    exam_model = models.ForeignKey(
        ExamModel, on_delete=models.PROTECT,
        related_name='items', verbose_name='Модель')
    item_number = models.PositiveSmallIntegerField('Номер задания')
    code = models.CharField('Код', max_length=48, unique=True)
    name = models.CharField('Название', max_length=255)
    order = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Задание экзамена'
        verbose_name_plural = 'Задания экзаменов'
        ordering = ['exam_model', 'order', 'item_number']
        constraints = [
            models.UniqueConstraint(
                fields=['exam_model', 'item_number'],
                name='unique_exam_item_number'),
        ]

    def __str__(self):
        return f'{self.code} {self.name}'


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

    # 10 и 11 — одна метка. GRADE_CHOICES — для селектов 5–11.
    # GRADE_FIELD_CHOICES оставляет 1–4 и 11 валидными для старых записей.
    GRADE_CHOICES = [
        (5, '5'), (6, '6'), (7, '7'), (8, '8'), (9, '9'), (10, '10–11'),
    ]
    GRADE_FIELD_CHOICES = (
        [(g, str(g)) for g in range(1, 5)] + GRADE_CHOICES + [(11, '10–11')]
    )
    STARS_CHOICES = [(i, '★' * i if i else 'без звёзд') for i in range(4)]
    DIFFICULTY_CHOICES = [(i, str(i)) for i in range(1, 6)]

    text_latex = models.TextField(
        'Условие (LaTeX)',
        help_text='Текст задачи в LaTeX, как для пакета egor')
    columns = models.PositiveSmallIntegerField(
        'Колонки подпунктов', default=0,
        help_text='0 — подпункты одной колонкой; N — подпункты в N колонок')
    answer_latex = models.TextField('Ответ (LaTeX)', blank=True)
    solution_latex = models.TextField('Решение (LaTeX)', blank=True)
    author_answer_latex = models.TextField(
        'Авторский ответ (LaTeX)', blank=True,
        help_text='Ответ из задачника; AI и редактор это поле не меняют')
    author_solution_latex = models.TextField(
        'Авторское решение (LaTeX)', blank=True,
        help_text='Решение или указание из задачника; AI это поле не меняет')
    text_plain = models.TextField(
        'Текст для поиска', blank=True, editable=False,
        help_text='Автоматически: условие без LaTeX-команд')
    grade_level = models.PositiveSmallIntegerField(
        'Класс изучения', choices=GRADE_FIELD_CHOICES, null=True, blank=True)
    stars = models.PositiveSmallIntegerField(
        'Сложность (звёзды)', choices=STARS_CHOICES, default=0)
    difficulty = models.PositiveSmallIntegerField(
        'Техническая сложность', choices=DIFFICULTY_CHOICES,
        null=True, blank=True)
    answer_type = models.CharField(
        'Тип ответа ученика', max_length=10,
        choices=ANSWER_TYPE_CHOICES, default=ANSWER_TEXT)
    topics = models.ManyToManyField(
        Topic, through='TaskTopic', blank=True,
        related_name='tasks', verbose_name='Темы')
    grade_bands = models.ManyToManyField(
        GradeBand, blank=True, related_name='tasks', verbose_name='Классы')
    facet_values = models.ManyToManyField(
        FacetValue, blank=True, related_name='tasks', verbose_name='Фасеты')
    exam_items = models.ManyToManyField(
        ExamItem, blank=True, related_name='tasks',
        verbose_name='Задания экзамена')
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

    @property
    def grade_option(self):
        """Значение селекта класса: 11 из старых данных = 10–11."""
        return normalize_grade_level(self.grade_level)

    @property
    def grade_display(self):
        opt = self.grade_option
        if opt is None:
            return ''
        return dict(self.GRADE_CHOICES).get(opt, str(opt))

    def save(self, *args, **kwargs):
        self.text_plain = strip_latex(self.text_latex)
        # При частичном сохранении text_plain едет вместе с text_latex
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'text_latex' in update_fields:
            kwargs['update_fields'] = list(update_fields) + ['text_plain']
        super().save(*args, **kwargs)

    @property
    def has_subitem_answers(self):
        return any(s.effective_answer_latex for s in self.subitems.all())

    @property
    def effective_answer_latex(self):
        """Проверенная редакторская/AI-версия, иначе текст из источника."""
        return (self.answer_latex or '').strip() or \
            (self.author_answer_latex or '').strip()

    @property
    def effective_solution_latex(self):
        """Проверенная редакторская/AI-версия, иначе текст из источника."""
        return (self.solution_latex or '').strip() or \
            (self.author_solution_latex or '').strip()

    @property
    def has_blank_answer(self):
        """Нет ответа: «Дописать AI-ответ» берёт только такие задачи.

        Решение без ответа — ответ ещё нужно дописать. Ответ без решения —
        ответ уже есть, пакет эту задачу пропускает.
        """
        subs = list(self.subitems.all())
        if subs:
            return any(not s.effective_answer_latex for s in subs)
        return not self.effective_answer_latex

    def make_variant(self, user=None):
        """Скрытая копия задачи для «локальной» правки в одном листке."""
        original = self
        copy = Task.objects.get(pk=self.pk)
        copy.pk = None
        copy.variant_of = original.variant_of or original
        if user is not None:
            copy.created_by = user
        copy.save()
        copy_task_taxonomy(original, copy)
        copy.tags.set(original.tags.all())
        for ref in original.source_refs.all():
            TaskSource.objects.create(
                task=copy, source=ref.source, number=ref.number,
                locator=None, source_path=ref.source_path,
                page=ref.page)
        for sub in original.subitems.all():
            TaskSubitem.objects.create(
                task=copy, order=sub.order,
                text_latex=sub.text_latex,
                answer_latex=sub.answer_latex,
                solution_latex=sub.solution_latex,
                author_answer_latex=sub.author_answer_latex,
                author_solution_latex=sub.author_solution_latex)
        for img in original.images.all():
            # Копия строки ссылается на тот же файл в storage
            copy.images.create(image=img.image.name, order=img.order)
        return copy


class TaskTopic(models.Model):
    """Связь задачи с темой: одна основная и любое число дополнительных."""

    ROLE_PRIMARY = 'PRIMARY'
    ROLE_SECONDARY = 'SECONDARY'
    ROLE_CHOICES = [
        (ROLE_PRIMARY, 'Основная'),
        (ROLE_SECONDARY, 'Дополнительная'),
    ]

    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name='topic_links',
        verbose_name='Задача')
    topic = models.ForeignKey(
        Topic, on_delete=models.PROTECT, related_name='task_links',
        verbose_name='Тема')
    role = models.CharField(
        'Роль', max_length=10, choices=ROLE_CHOICES, default=ROLE_SECONDARY)
    relevance = models.DecimalField(
        'Вес', max_digits=3, decimal_places=2, default=0.50)

    class Meta:
        verbose_name = 'Тема задачи'
        verbose_name_plural = 'Темы задач'
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'topic'], name='unique_task_topic'),
            models.UniqueConstraint(
                fields=['task'],
                condition=models.Q(role='PRIMARY'),
                name='unique_task_one_primary_topic'),
        ]

    def __str__(self):
        return f'{self.task_id} → {self.topic} ({self.role})'


def copy_task_taxonomy(original, copy):
    """Копирует темы (с ролью), классы, фасеты и экзамены на другую задачу."""
    for link in original.topic_links.all():
        TaskTopic.objects.create(
            task=copy, topic=link.topic, role=link.role,
            relevance=link.relevance)
    copy.grade_bands.set(original.grade_bands.all())
    copy.facet_values.set(original.facet_values.all())
    copy.exam_items.set(original.exam_items.all())
    if copy.difficulty != original.difficulty:
        copy.difficulty = original.difficulty
        copy.save(update_fields=['difficulty'])


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
    solution_latex = models.TextField('Решение (LaTeX)', blank=True)
    author_answer_latex = models.TextField(
        'Авторский ответ (LaTeX)', blank=True)
    author_solution_latex = models.TextField(
        'Авторское решение (LaTeX)', blank=True)

    class Meta:
        verbose_name = 'Подпункт задачи'
        verbose_name_plural = 'Подпункты задач'
        ordering = ['order', 'id']

    def __str__(self):
        return f'Задача #{self.task_id}, подпункт {self.order}: ' \
               f'{strip_latex(self.text_latex)[:40]}'

    @property
    def effective_answer_latex(self):
        return (self.answer_latex or '').strip() or \
            (self.author_answer_latex or '').strip()

    @property
    def effective_solution_latex(self):
        return (self.solution_latex or '').strip() or \
            (self.author_solution_latex or '').strip()


class TaskSource(models.Model):
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name='source_refs',
        verbose_name='Задача')
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name='task_refs',
        verbose_name='Источник')
    number = models.CharField(
        'Номер в источнике', max_length=190,
        help_text='Например: 123, 5.17а, №452')
    locator = models.CharField(
        'Ключ в источнике', max_length=190, null=True, blank=True,
        help_text='Стабильный ключ импорта, например 1.1.A01')
    source_path = models.JSONField(
        'Путь в источнике', default=list, blank=True,
        help_text='Глава, параграф, уровень или вариант')
    page = models.PositiveIntegerField(
        'Страница', null=True, blank=True)

    class Meta:
        verbose_name = 'Номер задачи в источнике'
        verbose_name_plural = 'Номера задач в источниках'
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'source'], name='unique_task_source'),
            models.UniqueConstraint(
                fields=['source', 'locator'],
                name='unique_source_locator'),
        ]

    def __str__(self):
        return f'{self.source} № {self.number}'

    def save(self, *args, **kwargs):
        """При ручной смене источника старый ключ импорта недействителен."""
        changed_source = False
        if self.pk:
            previous_source = (TaskSource.objects.filter(pk=self.pk)
                               .values_list('source_id', flat=True).first())
            changed_source = (previous_source is not None
                              and previous_source != self.source_id)
        if changed_source:
            self.locator = None
            self.source_path = []
            self.page = None
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = list(set(update_fields) | {
                    'locator', 'source_path', 'page'})
        super().save(*args, **kwargs)


class TextbookImportBatch(models.Model):
    """Партия черновиков, полученная из проверяемого JSON парсера."""

    STATUS_REVIEW = 'review'
    STATUS_READY = 'ready'
    STATUS_IMPORTED = 'imported'
    STATUS_CHOICES = [
        (STATUS_REVIEW, 'На проверке'),
        (STATUS_READY, 'Готова к загрузке'),
        (STATUS_IMPORTED, 'Загружена'),
    ]

    title = models.CharField('Название партии', max_length=190)
    profile = models.CharField('Профиль парсера', max_length=32)
    source = models.ForeignKey(
        Source, on_delete=models.PROTECT, related_name='import_batches',
        verbose_name='Источник')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='textbook_import_batches', verbose_name='Редактор')
    status = models.CharField(
        'Статус', max_length=12, choices=STATUS_CHOICES,
        default=STATUS_REVIEW)
    diagnostics = models.JSONField('Диагностика', default=dict, blank=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    updated_at = models.DateTimeField('Изменена', auto_now=True)

    class Meta:
        verbose_name = 'Импорт задачника'
        verbose_name_plural = 'Импорты задачников'
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class TextbookTaskDraft(models.Model):
    """Одна вручную проверяемая задача до записи в рабочий каталог."""

    STATUS_REVIEW = 'needs_review'
    STATUS_APPROVED = 'approved'
    STATUS_CONFLICT = 'conflict'
    STATUS_SKIPPED = 'skipped'
    STATUS_IMPORTED = 'imported'
    STATUS_CHOICES = [
        (STATUS_REVIEW, 'Не проверена'),
        (STATUS_APPROVED, 'Одобрена'),
        (STATUS_CONFLICT, 'Конфликт'),
        (STATUS_SKIPPED, 'Пропущена'),
        (STATUS_IMPORTED, 'Импортировано'),
    ]

    batch = models.ForeignKey(
        TextbookImportBatch, on_delete=models.CASCADE, related_name='drafts',
        verbose_name='Партия')
    external_id = models.CharField('Ключ задачи', max_length=190)
    source_number = models.CharField('Номер в источнике', max_length=190)
    source_path = models.JSONField('Путь в источнике', default=list, blank=True)
    collection_key = models.CharField(
        'Ключ подборки', max_length=500, blank=True)
    collection_title = models.CharField(
        'Название подборки', max_length=190, blank=True)
    topic_original = models.CharField(
        'Тема в задачнике', max_length=255, blank=True)
    topic = models.ForeignKey(
        Topic, on_delete=models.PROTECT, null=True, blank=True,
        related_name='textbook_drafts', verbose_name='Тема рубрикатора')
    text_latex = models.TextField('Условие (LaTeX)')
    subitems = models.JSONField('Подпункты', default=list, blank=True)
    images = models.JSONField('Изображения', default=list, blank=True)
    topic_candidates = models.JSONField(
        'Кандидаты рубрикатора', default=list, blank=True)
    author_answer_latex = models.TextField('Авторский ответ', blank=True)
    author_solution_latex = models.TextField('Авторское решение', blank=True)
    solution_source_external_id = models.CharField(
        'Ключ сопоставленного решения', max_length=190, blank=True)
    confidence = models.DecimalField(
        'Уверенность', max_digits=4, decimal_places=3, default=0)
    warnings = models.JSONField('Предупреждения', default=list, blank=True)
    status = models.CharField(
        'Статус', max_length=16, choices=STATUS_CHOICES,
        default=STATUS_REVIEW)
    imported_task = models.ForeignKey(
        Task, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='textbook_drafts', verbose_name='Созданная задача')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_textbook_drafts',
        verbose_name='Проверил')
    reviewed_at = models.DateTimeField('Проверена', null=True, blank=True)

    class Meta:
        verbose_name = 'Черновик задачи из задачника'
        verbose_name_plural = 'Черновики задач из задачника'
        ordering = ['external_id', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['batch', 'external_id'],
                name='unique_batch_external_task'),
        ]

    def __str__(self):
        return f'{self.batch}: {self.external_id}'

    @property
    def author_answer_subitem_count(self):
        return sum(bool(str(item.get('author_answer_latex') or '').strip())
                   for item in self.subitems)

    @property
    def author_solution_subitem_count(self):
        return sum(bool(str(item.get('author_solution_latex') or '').strip())
                   for item in self.subitems)

    @property
    def has_author_answer_material(self):
        return bool(self.author_answer_latex.strip()
                    or self.author_answer_subitem_count)

    @property
    def has_author_solution_material(self):
        return bool(self.author_solution_latex.strip()
                    or self.author_solution_subitem_count)

    def unmatched_images(self):
        resolved = {
            asset.stem for asset in self.batch.assets.all()
        } if self.batch_id else set()
        return [name for name in self.images
                if os.path.splitext(os.path.basename(
                    str(name).replace('\\', '/')))[0].lower()
                not in resolved]


class TextbookImportAsset(models.Model):
    """Файл рисунка, сопоставленный черновикам партии по имени."""

    batch = models.ForeignKey(
        TextbookImportBatch, on_delete=models.CASCADE, related_name='assets',
        verbose_name='Партия')
    stem = models.CharField('Нормализованное имя', max_length=255)
    original_name = models.CharField('Исходное имя файла', max_length=255)
    file = models.FileField(
        'Файл', upload_to='textbook_import_assets/',
        validators=[FileExtensionValidator(['png', 'jpg', 'jpeg', 'pdf'])])

    class Meta:
        verbose_name = 'Рисунок партии импорта'
        verbose_name_plural = 'Рисунки партий импорта'
        constraints = [
            models.UniqueConstraint(
                fields=['batch', 'stem'], name='unique_batch_image_stem'),
        ]
        ordering = ['original_name', 'pk']

    def __str__(self):
        return f'{self.batch}: {self.original_name}'

    @property
    def is_pdf(self):
        return self.original_name.lower().endswith('.pdf')


class NeuroSolveQuota(models.Model):
    """Квота нейрогенерации: не больше N запросов в минуту и один in-flight.

    Платный внешний API и синхронный вызов до минуты — без серверного
    лимита любой учитель мог бы исчерпать баланс и воркеры.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        verbose_name='Пользователь', related_name='neuro_quota')
    in_flight_at = models.DateTimeField('Занят с', null=True, blank=True)
    window_started = models.DateTimeField('Начало окна')
    window_count = models.PositiveIntegerField('Запросов в окне', default=0)

    class Meta:
        verbose_name = 'Квота нейрогенерации'
        verbose_name_plural = 'Квоты нейрогенерации'

    def __str__(self):
        return f'Квота нейросети: {self.user}'

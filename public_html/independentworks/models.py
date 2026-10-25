"""Шаблоны, неизменяемые варианты и независимые ответы по пунктам."""
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from assignments.models import Review


class Family(models.Model):
    key = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=255)
    origin = models.CharField(max_length=30, default='manual')
    tasks = models.ManyToManyField('problems.Task', related_name='analog_families', through='FamilyMember')

    @classmethod
    def link_analog(cls, source, copy, key=None):
        """Ручной аналог: копия входит в семейство исходной задачи (или её
        каталожного оригинала); если семейства нет — создаётся новое."""
        family = source.analog_families.first()
        if not family and source.variant_of_id:
            family = source.variant_of.analog_families.first()
        if family is None:
            family = cls.objects.create(key='manual:analog:' + (key or uuid.uuid4().hex),
                                        title=f'Аналоги задачи {source.pk}')
            family.tasks.add(source)
        family.tasks.add(copy)
        return family


class FamilyMember(models.Model):
    family = models.ForeignKey(Family, on_delete=models.CASCADE)
    task = models.ForeignKey('problems.Task', on_delete=models.CASCADE)
    origin = models.CharField(max_length=30, default='manual')
    evidence = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['family', 'task'], name='iw_family_task')]


class Work(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField('Название', max_length=190)
    source_worksheet = models.ForeignKey('worksheets.Worksheet', null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='independent_templates')
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def visible_to(cls, user):
        return cls.objects.all() if user.is_superuser else cls.objects.filter(owner=user)


class Position(models.Model):
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name='positions')
    order = models.PositiveIntegerField(default=1)
    text = models.TextField('Пояснение', blank=True)
    mismatch_confirmed = models.BooleanField(default=False)
    confirmed_composition = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['order', 'pk']


class Candidate(models.Model):
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name='candidates')
    task = models.ForeignKey('problems.Task', on_delete=models.PROTECT)
    # Пусто означает целую задачу; при выдаче список разрешается в снимок.
    subitem_ids = models.JSONField(default=list, blank=True)


class Run(models.Model):
    work = models.ForeignKey(Work, on_delete=models.PROTECT, related_name='runs')
    title = models.CharField(max_length=190)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    duration = models.PositiveIntegerField('Длительность, минут', default=40)
    deadline = models.DateTimeField('Общее окончание', null=True, blank=True)
    max_variants = models.PositiveIntegerField(null=True, blank=True)
    restrict_clipboard = models.BooleanField(default=False)
    swap_numbers = models.BooleanField(default=False)
    # Ушёл со страницы дольше 2 секунд (порог — iw_leave_lock.js) — задания под
    # заглушкой, пока учитель не разблокирует (Attempt.locked_at). Можно
    # включить и после выдачи.
    lock_on_leave = models.BooleanField(default=False)
    allow_photos = models.BooleanField(default=True)
    self_check = models.BooleanField(default=False)
    release_mode = models.CharField(max_length=12, default='manual')
    release_flags = models.JSONField(default=list)
    plan = models.JSONField(default=dict)
    fingerprint = models.CharField(max_length=64)
    issued_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    kind = models.CharField(max_length=12, default='initial')
    parent = models.ForeignKey('Attempt', null=True, blank=True, on_delete=models.PROTECT, related_name='followup_runs')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def kind_label(self):
        return {'initial': 'Самостоятельная', 'correction': 'Работа над ошибками',
                'retake': 'Пересдача'}.get(self.kind, 'Самостоятельная')


class Variant(models.Model):
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name='variants')
    number = models.PositiveIntegerField()
    signature = models.CharField(max_length=64)
    notes = models.JSONField(default=list)

    class Meta:
        ordering = ['number']
        constraints = [models.UniqueConstraint(fields=['run', 'number'], name='iw_variant_number')]


class Point(models.Model):
    variant = models.ForeignKey(Variant, on_delete=models.CASCADE, related_name='points')
    position = models.PositiveIntegerField()
    part = models.PositiveIntegerField(default=0)
    label = models.CharField(max_length=50)
    source_key = models.CharField(max_length=100)
    candidate_key = models.CharField(max_length=255)
    root_key = models.CharField(max_length=100)
    snapshot = models.JSONField(default=dict)

    class Meta:
        ordering = ['position', 'part', 'pk']


class Asset(models.Model):
    point = models.ForeignKey(Point, on_delete=models.CASCADE, related_name='assets')
    file = models.FileField(upload_to='independent_assets/%Y/%m/')
    name = models.CharField(max_length=255)
    audiences = models.JSONField(default=list)


class Attempt(models.Model):
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name='attempts')
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name='attempts')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children')
    root = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='corrections')
    clipboard_exempt = models.BooleanField(default=False)
    # Когда страницу закрыла заглушка «Вы ушли со страницы»; учитель
    # разблокирует разово — при следующем уходе блокировка повторится.
    locked_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    release_flags = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['run', 'student'], name='iw_run_student')]

    @property
    def restrict_clipboard(self):
        """Исключённому ученику копирование не запрещают и числа не подменяют."""
        return self.run.restrict_clipboard and not self.clipboard_exempt

    @property
    def swap_numbers(self):
        return self.run.swap_numbers and not self.clipboard_exempt

    @property
    def finished(self):
        return bool(self.submitted_at or (self.ends_at and timezone.now() >= self.ends_at))

    @property
    def state(self):
        if not self.started_at:
            return 'Не начато'
        return 'Сдано' if self.finished else 'Выполняется'

    @property
    def disclosure(self):
        if not self.finished:
            return set()
        return set(self.run.release_flags) if self.run.release_mode == 'auto' else set()


class Answer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name='answers')
    point = models.ForeignKey(Point, on_delete=models.PROTECT)
    values = models.JSONField(default=dict)
    auto_check = models.CharField(max_length=12, blank=True)
    checks = models.JSONField(default=dict)
    check_revealed = models.BooleanField(default=False)
    grade = models.CharField(max_length=2, blank=True, choices=Review.GRADE_CHOICES)
    comment = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['attempt', 'point'], name='iw_answer_point')]

    @property
    def credit(self):
        if self.grade:
            return Review.CREDITS.get(self.grade, 0)
        return int(self.auto_check == 'ok')

    @property
    def pending(self):
        return not self.grade and self.auto_check not in ('ok', 'wrong')

    @property
    def grade_symbol(self):
        return Review.SYMBOLS.get(self.grade, self.grade)


class AnswerCheckAttempt(models.Model):
    """Неизменяемый снимок одного нажатия «Проверить»."""

    answer = models.ForeignKey(Answer, on_delete=models.CASCADE, related_name='check_history')
    number = models.PositiveIntegerField()
    result = models.CharField(max_length=12)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['number']
        constraints = [models.UniqueConstraint(
            fields=['answer', 'number'], name='iw_unique_check_attempt_answer_number')]


class Photo(models.Model):
    answer = models.ForeignKey(Answer, on_delete=models.CASCADE, related_name='photos')
    file = models.FileField(upload_to='independent_photos/%Y/%m/')
    created_at = models.DateTimeField(auto_now_add=True)

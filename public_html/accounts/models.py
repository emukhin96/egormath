import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

# Код ссылки регистрации учеников: без похожих символов (0/o, 1/l/i),
# чтобы ссылку можно было продиктовать или переписать с доски.
STUDENT_CODE_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'
STUDENT_CODE_LENGTH = 8
INVITE_DEFAULT_DAYS = 14


def default_teacher():
    """Пока сайт рассчитан на одного преподавателя — суперпользователя.

    Когда появится ссылка на регистрацию к конкретному учителю, ученик
    будет записываться к владельцу ссылки, а не к этому fallback.
    """
    User = get_user_model()
    return User.objects.filter(is_superuser=True).order_by('pk').first()


def generate_student_code():
    """Свободный код для ссылки ``/accounts/register/?t=<код>``."""
    while True:
        code = ''.join(secrets.choice(STUDENT_CODE_ALPHABET)
                       for _ in range(STUDENT_CODE_LENGTH))
        if not Profile.objects.filter(student_code=code).exists():
            return code


def generate_invite_token():
    return secrets.token_urlsafe(32)


def default_invite_expiry():
    return timezone.now() + timedelta(days=INVITE_DEFAULT_DAYS)


class Profile(models.Model):
    ROLE_TEACHER = 'teacher'
    ROLE_STUDENT = 'student'
    ROLE_CHOICES = [
        (ROLE_TEACHER, 'Учитель'),
        (ROLE_STUDENT, 'Ученик'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='profile', verbose_name='Пользователь')
    role = models.CharField(
        'Роль', max_length=10, choices=ROLE_CHOICES, default=ROLE_STUDENT)
    grade = models.PositiveSmallIntegerField(
        'Класс', null=True, blank=True,
        help_text='Для учеников: класс обучения (5–11)')
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='students',
        verbose_name='Учитель',
        help_text='Для учеников: учитель, который ведёт этого ученика')
    base_editor = models.BooleanField(
        'Правит общую базу задач', default=False,
        help_text='Для учителей: право менять общие задачи напрямую. '
                  'У суперпользователя подразумевается всегда; остальные '
                  'правят общие задачи только копией для своего листка '
                  '(accounts/permissions.py).')
    show_foreign_tasks = models.BooleanField(
        'Показывать задачи других учителей', default=False,
        help_text='Для редакторов базы: показывать в каталоге и поиске '
                  'задачи других учителей, не принятые в общие '
                  '(accounts/permissions.py, catalog_tasks). По прямой '
                  'ссылке такая задача открывается всегда.')
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='invited_teachers',
        verbose_name='Пригласил',
        help_text='Для учителей: кто выписал приглашение.')
    student_code = models.CharField(
        'Код ссылки регистрации', max_length=STUDENT_CODE_LENGTH,
        unique=True, null=True, blank=True,
        help_text='Для учителей: ученик по ссылке /accounts/register/?t=<код> '
                  'записывается к этому учителю.')
    onboarding_done_at = models.DateTimeField(
        'Первые шаги скрыты', null=True, blank=True,
        help_text='Для учителей: когда закрыта карточка «Первые шаги».')

    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} ({self.get_role_display()})'

    def save(self, *args, **kwargs):
        # Код ссылки регистрации учеников нужен каждому учителю с момента
        # создания профиля; у ученика его нет.
        if self.role == self.ROLE_TEACHER and not self.student_code:
            self.student_code = generate_student_code()
        super().save(*args, **kwargs)

    @classmethod
    def for_teacher(cls, user):
        """Профиль учителя; суперпользователю без профиля (createsuperuser)
        профиль заводится на месте — иначе ему негде хранить код ссылки
        регистрации учеников."""
        try:
            profile = user.profile
        except cls.DoesNotExist:
            if not user.is_superuser:
                raise
            profile = cls.objects.create(user=user, role=cls.ROLE_TEACHER)
        if profile.role == cls.ROLE_TEACHER and not profile.student_code:
            profile.save(update_fields=['student_code'])
        return profile

    @classmethod
    def teacher_by_student_code(cls, code):
        """Учитель — владелец кода из ссылки регистрации, если учитель
        активен; иначе ``None``."""
        if not code:
            return None
        profile = (cls.objects.filter(
            role=cls.ROLE_TEACHER, student_code=code, user__is_active=True)
            .select_related('user').first())
        return profile.user if profile else None

    @property
    def is_teacher(self):
        return self.role == self.ROLE_TEACHER

    @property
    def is_student(self):
        return self.role == self.ROLE_STUDENT

    @classmethod
    def students_for(cls, user):
        """Ученики, доступные учителю для списка, правок и выдачи заданий.

        Обычный учитель видит только тех, кто записан к нему.
        Суперпользователь видит всех учеников: самостоятельная регистрация
        пока общая, без персональной ссылки учителя.
        """
        qs = cls.objects.filter(role=cls.ROLE_STUDENT)
        if not getattr(user, 'is_superuser', False):
            qs = qs.filter(teacher=user)
        return qs

    @classmethod
    def student_users_for(cls, user):
        """Пользователи-ученики, доступные учителю (для форм выдачи)."""
        User = get_user_model()
        qs = User.objects.filter(profile__role=cls.ROLE_STUDENT)
        if not getattr(user, 'is_superuser', False):
            qs = qs.filter(profile__teacher=user)
        return qs


class StudentGroup(models.Model):
    """Произвольная группа учеников одного учителя (ученик может состоять
    в нескольких группах)."""

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='owned_groups', verbose_name='Учитель')
    name = models.CharField('Название', max_length=100)
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True,
        related_name='member_groups', verbose_name='Ученики')

    class Meta:
        verbose_name = 'Группа учеников'
        verbose_name_plural = 'Группы учеников'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['teacher', 'name'], name='unique_group_teacher_name'),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def visible_to(cls, user):
        """Группы, которыми учитель вправе управлять."""
        queryset = cls.objects.all()
        if not getattr(user, 'is_superuser', False):
            queryset = queryset.filter(teacher=user)
        return queryset


class TeacherInvite(models.Model):
    """Приглашение учителя: одна ссылка — одна регистрация.

    Ссылку суперпользователь копирует со страницы «Учителя» и отправляет
    сам (почты на сайте нет). Отзыв приглашения — удаление записи:
    неизвестный токен на странице регистрации показывается как
    недействительная ссылка.
    """

    token = models.CharField(
        'Токен', max_length=64, unique=True, editable=False,
        default=generate_invite_token)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='teacher_invites', verbose_name='Выписал')
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    expires_at = models.DateTimeField(
        'Действует до', default=default_invite_expiry)
    note = models.CharField(
        'Заметка', max_length=200, blank=True,
        help_text='Кому предназначено — для списка приглашений.')
    email = models.EmailField('Почта', blank=True)
    base_editor = models.BooleanField(
        'Право править базу', default=False,
        help_text='Выдать право менять общие задачи сразу при регистрации.')
    used_at = models.DateTimeField('Погашено', null=True, blank=True)
    used_by = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='teacher_invite',
        verbose_name='Зарегистрировался')

    class Meta:
        verbose_name = 'Приглашение учителя'
        verbose_name_plural = 'Приглашения учителей'
        ordering = ['-created_at']

    def __str__(self):
        return self.note or f'Приглашение #{self.pk}'

    @property
    def is_used(self):
        return self.used_at is not None

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    @classmethod
    def pending(cls):
        """Непогашенные и не просроченные — список на странице «Учителя»."""
        return cls.objects.filter(
            used_at__isnull=True, expires_at__gt=timezone.now())

    def claim(self):
        """Погасить приглашение атомарно: условный UPDATE проходит только у
        одного из двух одновременных запросов с тем же токеном."""
        now = timezone.now()
        claimed = TeacherInvite.objects.filter(
            pk=self.pk, used_at__isnull=True, expires_at__gt=now,
        ).update(used_at=now)
        if claimed:
            self.used_at = now
        return bool(claimed)

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models


def default_teacher():
    """Пока сайт рассчитан на одного преподавателя — суперпользователя.

    Когда появится ссылка на регистрацию к конкретному учителю, ученик
    будет записываться к владельцу ссылки, а не к этому fallback.
    """
    User = get_user_model()
    return User.objects.filter(is_superuser=True).order_by('pk').first()


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

    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} ({self.get_role_display()})'

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

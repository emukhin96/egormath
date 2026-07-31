from django.conf import settings
from django.db import models


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

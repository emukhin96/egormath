import secrets

from django.conf import settings
from django.db import migrations

# Как accounts.models.STUDENT_CODE_ALPHABET: миграция не импортирует модели
ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'


def assign_student_codes(apps, schema_editor):
    """Код ссылки регистрации учеников — всем учителям; суперпользователю
    без профиля (createsuperuser) профиль заводится здесь же."""
    User = apps.get_model('auth', 'User')
    Profile = apps.get_model('accounts', 'Profile')
    for user in User.objects.filter(is_superuser=True, profile__isnull=True):
        Profile.objects.create(user=user, role='teacher')
    taken = set(Profile.objects.exclude(student_code=None)
                .values_list('student_code', flat=True))
    for profile in Profile.objects.filter(role='teacher', student_code=None):
        code = ''.join(secrets.choice(ALPHABET) for _ in range(8))
        while code in taken:
            code = ''.join(secrets.choice(ALPHABET) for _ in range(8))
        taken.add(code)
        profile.student_code = code
        profile.save(update_fields=['student_code'])


def clear_student_codes(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    Profile.objects.update(student_code=None)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0005_teacherinvite'),
    ]

    operations = [
        migrations.RunPython(assign_student_codes, clear_student_codes),
    ]

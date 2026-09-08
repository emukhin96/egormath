from django.conf import settings
from django.db import migrations


def attach_unattached_students(apps, schema_editor):
    """Самостоятельно зарегистрированные ученики — к первому суперпользователю."""
    User = apps.get_model('auth', 'User')
    Profile = apps.get_model('accounts', 'Profile')
    teacher = User.objects.filter(is_superuser=True).order_by('pk').first()
    if teacher is None:
        return
    Profile.objects.filter(
        role='student', teacher__isnull=True,
    ).update(teacher=teacher)


def unattach_students(apps, schema_editor):
    """Обратная операция не восстанавливает, кто был без учителя."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0002_auto_20260802_0019'),
    ]

    operations = [
        migrations.RunPython(attach_unattached_students, unattach_students),
    ]

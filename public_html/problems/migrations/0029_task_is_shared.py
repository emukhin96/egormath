from django.conf import settings
from django.db import migrations, models


def mark_existing_shared(apps, schema_editor):
    """Все задачи, созданные до разделения на общие и личные, — общие."""
    Task = apps.get_model('problems', 'Task')
    Task.objects.update(is_shared=True)


def noop(apps, schema_editor):
    """Поле удаляется вместе с данными — восстанавливать нечего."""


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('problems', '0028_textbook_draft_position'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='is_shared',
            field=models.BooleanField(
                default=False,
                help_text='Общую задачу видят все учителя, правят только '
                          'редакторы базы. Личная видна автору и редакторам.',
                verbose_name='В общей базе'),
        ),
        migrations.RunPython(mark_existing_shared, noop),
        migrations.AddIndex(
            model_name='task',
            index=models.Index(fields=['is_shared', 'created_by'],
                               name='problems_task_shared_author'),
        ),
    ]

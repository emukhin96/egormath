from django.db import migrations, models


def forwards(apps, schema_editor):
    Assignment = apps.get_model('assignments', 'Assignment')
    Assignment.objects.filter(clipboard_mode='block').update(restrict_clipboard=True)
    Assignment.objects.filter(clipboard_mode='swap').update(swap_numbers=True)


def backwards(apps, schema_editor):
    Assignment = apps.get_model('assignments', 'Assignment')
    Assignment.objects.filter(swap_numbers=True).update(clipboard_mode='swap')
    Assignment.objects.filter(restrict_clipboard=True).update(clipboard_mode='block')


class Migration(migrations.Migration):
    """Режим копирования → две независимые настройки: запрет и подмена чисел."""

    dependencies = [
        ('assignments', '0014_assignment_clipboard_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='assignment',
            name='restrict_clipboard',
            field=models.BooleanField(default=False, verbose_name='Запретить копирование условий и вставку ответов'),
        ),
        migrations.AddField(
            model_name='assignment',
            name='swap_numbers',
            field=models.BooleanField(default=False, verbose_name='Подменять числа при копировании условий'),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='assignment',
            name='clipboard_mode',
        ),
    ]

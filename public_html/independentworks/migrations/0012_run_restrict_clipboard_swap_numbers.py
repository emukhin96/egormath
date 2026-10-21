from django.db import migrations, models


def forwards(apps, schema_editor):
    Run = apps.get_model('independentworks', 'Run')
    Run.objects.filter(clipboard_mode='block').update(restrict_clipboard=True)
    Run.objects.filter(clipboard_mode='swap').update(swap_numbers=True)


def backwards(apps, schema_editor):
    Run = apps.get_model('independentworks', 'Run')
    Run.objects.filter(swap_numbers=True).update(clipboard_mode='swap')
    Run.objects.filter(restrict_clipboard=True).update(clipboard_mode='block')


class Migration(migrations.Migration):
    """Режим копирования → две независимые настройки: запрет и подмена чисел."""

    dependencies = [
        ('independentworks', '0011_hide_answer_assets'),
    ]

    operations = [
        migrations.AddField(
            model_name='run',
            name='restrict_clipboard',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='run',
            name='swap_numbers',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='run',
            name='clipboard_mode',
        ),
    ]

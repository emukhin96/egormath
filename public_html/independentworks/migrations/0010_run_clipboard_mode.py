from django.db import migrations, models


def forwards(apps, schema_editor):
    Run = apps.get_model('independentworks', 'Run')
    Run.objects.filter(restrict_clipboard=True).update(clipboard_mode='block')


def backwards(apps, schema_editor):
    Run = apps.get_model('independentworks', 'Run')
    Run.objects.filter(clipboard_mode='block').update(restrict_clipboard=True)


class Migration(migrations.Migration):
    """Флаг «Ограничить копирование» → режим из трёх: запись, подмена чисел, запрет."""

    dependencies = [
        ('independentworks', '0009_run_self_check_answer_check_history'),
    ]

    operations = [
        migrations.AddField(
            model_name='run',
            name='clipboard_mode',
            field=models.CharField(choices=[('watch', 'Разрешить и записывать в журнал'), ('swap', 'Разрешить, но подменять числа в скопированном'), ('block', 'Запретить копирование условий и вставку ответов')], default='watch', max_length=8),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='run',
            name='restrict_clipboard',
        ),
    ]

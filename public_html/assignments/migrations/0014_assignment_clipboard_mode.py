from django.db import migrations, models


def forwards(apps, schema_editor):
    Assignment = apps.get_model('assignments', 'Assignment')
    Assignment.objects.filter(restrict_clipboard=True).update(clipboard_mode='block')


def backwards(apps, schema_editor):
    Assignment = apps.get_model('assignments', 'Assignment')
    Assignment.objects.filter(clipboard_mode='block').update(restrict_clipboard=True)


class Migration(migrations.Migration):
    """Флаг «Ограничить копирование» → режим из трёх: запись, подмена чисел, запрет."""

    dependencies = [
        ('assignments', '0013_assignment_restrict_clipboard'),
    ]

    operations = [
        migrations.AddField(
            model_name='assignment',
            name='clipboard_mode',
            field=models.CharField(choices=[('watch', 'Разрешить и записывать в журнал'), ('swap', 'Разрешить, но подменять числа в скопированном'), ('block', 'Запретить копирование условий и вставку ответов')], default='watch', max_length=8, verbose_name='Копирование условий'),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='assignment',
            name='restrict_clipboard',
        ),
    ]

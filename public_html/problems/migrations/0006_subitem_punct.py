"""Срезает хвостовые «;» и «.» у текстов подпунктов: по новой конвенции
знаки препинания расставляет система (в PDF и на веб-страницах),
а в базе подпункт хранится без них."""

from django.db import migrations


def forwards(apps, schema_editor):
    TaskSubitem = apps.get_model('problems', 'TaskSubitem')
    for sub in TaskSubitem.objects.all().iterator():
        stripped = sub.text_latex.strip()
        if stripped.endswith((';', '.')):
            sub.text_latex = stripped[:-1].rstrip()
            sub.save(update_fields=['text_latex'])


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0005_taskimage'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

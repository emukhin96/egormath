"""Перенос Task.subitems_latex («\\item а; \\item б;») в модель TaskSubitem."""

import re

from django.db import migrations

ITEM_RE = re.compile(r'\\item\b')


def split_items(text):
    """Разбивает текст подпунктов по \\item; текст до первого \\item
    (если есть) считается первым подпунктом."""
    chunks = [c.strip() for c in ITEM_RE.split(text)]
    return [c for c in chunks if c]


def forwards(apps, schema_editor):
    Task = apps.get_model('problems', 'Task')
    TaskSubitem = apps.get_model('problems', 'TaskSubitem')
    for task in Task.objects.exclude(subitems_latex='').iterator():
        for i, chunk in enumerate(split_items(task.subitems_latex)):
            TaskSubitem.objects.create(
                task=task, order=(i + 1) * 10, text_latex=chunk)


def backwards(apps, schema_editor):
    Task = apps.get_model('problems', 'Task')
    TaskSubitem = apps.get_model('problems', 'TaskSubitem')
    for task in Task.objects.filter(subitems__isnull=False).distinct():
        lines = '\n'.join(
            f'\\item {s.text_latex}'
            for s in task.subitems.order_by('order', 'id'))
        Task.objects.filter(pk=task.pk).update(subitems_latex=lines)
    TaskSubitem.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0002_auto_20260802_0019'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

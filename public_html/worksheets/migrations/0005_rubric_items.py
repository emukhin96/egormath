"""Рубрика становится самостоятельным элементом листка.

Для каждого элемента-задачи с непустой rubric создаётся элемент-рубрика
перед ним, поле у задачи очищается. Порядок элементов перенумеровывается.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    Worksheet = apps.get_model('worksheets', 'Worksheet')
    WorksheetItem = apps.get_model('worksheets', 'WorksheetItem')
    for worksheet in Worksheet.objects.all():
        items = list(worksheet.items.order_by('order', 'id'))
        order = 0
        for item in items:
            if item.task_id and item.rubric:
                order += 10
                WorksheetItem.objects.create(
                    worksheet=worksheet, order=order,
                    rubric=item.rubric, rubric_note=item.rubric_note)
                item.rubric = ''
                item.rubric_note = ''
            order += 10
            item.order = order
            item.save()


def backwards(apps, schema_editor):
    """Рубрики-элементы возвращаются на следующий элемент-задачу."""
    Worksheet = apps.get_model('worksheets', 'Worksheet')
    for worksheet in Worksheet.objects.all():
        items = list(worksheet.items.order_by('order', 'id'))
        pending = None
        for item in items:
            if item.task_id is None and item.rubric:
                pending = item
                continue
            if item.task_id and pending is not None:
                item.rubric = pending.rubric
                item.rubric_note = pending.rubric_note
                item.save()
                pending.delete()
                pending = None


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0004_auto_20260805_0315'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

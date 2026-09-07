"""Линейные метки ОГЭ/ЕГЭ (item_number=0) для уже применённого сида 0010."""

from django.db import migrations


def seed_exam_line_items(apps, schema_editor):
    from problems.rubricator_data import EXAM_MODELS

    ExamModel = apps.get_model('problems', 'ExamModel')
    ExamItem = apps.get_model('problems', 'ExamItem')
    for model_code, exam_type, year, name, items in EXAM_MODELS:
        line_items = [row for row in items if row[0] == 0]
        if not line_items:
            continue
        model, _ = ExamModel.objects.update_or_create(
            code=model_code,
            defaults={
                'exam_type': exam_type,
                'exam_year': year,
                'name': name,
            })
        for number, item_code, item_name in line_items:
            ExamItem.objects.update_or_create(
                code=item_code,
                defaults={
                    'exam_model': model,
                    'item_number': number,
                    'name': item_name,
                    'order': number,
                })


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0017_task_answer_type_formula'),
    ]

    operations = [
        migrations.RunPython(seed_exam_line_items, migrations.RunPython.noop),
    ]

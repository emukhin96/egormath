from django.db import migrations


def preserve_answers(apps, schema_editor):
    """Переносит старую запись в текст до удаления типа задачи."""
    alias = schema_editor.connection.alias
    for model_name, relation in [('Submission', 'task'),
                                  ('SubmissionPart', 'submission__task')]:
        model = apps.get_model('assignments', model_name)
        for obj in model.objects.using(alias).select_related(relation).iterator():
            task = obj.task if model_name == 'Submission' else obj.submission.task
            value = ''
            if task.answer_type == 'number':
                value = obj.answer_number
            elif task.answer_type == 'interval' and (obj.interval_low or obj.interval_high):
                value = f'от {obj.interval_low or "−∞"} до {obj.interval_high or "+∞"}'
            if value and not obj.answer_text:
                model.objects.using(alias).filter(pk=obj.pk).update(answer_text=value)


class Migration(migrations.Migration):
    dependencies = [
        ('problems', '0019_exam_line_items'),
        ('assignments', '0008_submissioncheckattempt'),
    ]
    operations = [
        migrations.RunPython(preserve_answers, migrations.RunPython.noop),
        migrations.RemoveField(model_name='task', name='answer_type'),
        migrations.RemoveField(model_name='task', name='answer_mode'),
    ]

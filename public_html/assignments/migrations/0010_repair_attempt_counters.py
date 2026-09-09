"""Восстановить счётчики, затёртые параллельным сохранением ответа."""
from django.db import migrations
from django.db.models import Max


def repair(apps, schema_editor):
    Submission = apps.get_model('assignments', 'Submission')
    for submission in Submission.objects.annotate(last_attempt=Max('check_history__number')).iterator():
        if submission.last_attempt and submission.last_attempt > submission.check_attempts:
            Submission.objects.filter(pk=submission.pk).update(check_attempts=submission.last_attempt)


class Migration(migrations.Migration):
    dependencies = [('assignments', '0009_review_grade_alter_assignment_check_visibility')]
    operations = [migrations.RunPython(repair, migrations.RunPython.noop)]

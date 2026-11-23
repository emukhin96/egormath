"""Класс и раздел источников для полок «Подборок»: по названию
(problems/source_meta.py), а где название молчит — по классу листков
подборок источника и по темам его задач (корень рубрикатора большинства).
Заполняются только пустые поля; редактор потом правит в админке."""
from collections import Counter

from django.db import migrations

from problems.source_meta import TOPIC_ROOT_SUBJECTS, guess_grades, guess_subject


def _root_codes(Topic):
    rows = {pk: (parent_id, code) for pk, parent_id, code
            in Topic.objects.values_list('pk', 'parent_id', 'code')}
    roots = {}
    for pk in rows:
        node, seen = pk, set()
        while rows[node][0] and rows[node][0] in rows and node not in seen:
            seen.add(node)
            node = rows[node][0]
        roots[pk] = rows[node][1]
    return roots


def fill(apps, schema_editor):
    Source = apps.get_model('problems', 'Source')
    Topic = apps.get_model('problems', 'Topic')
    TaskTopic = apps.get_model('problems', 'TaskTopic')
    Worksheet = apps.get_model('worksheets', 'Worksheet')
    WorksheetItem = apps.get_model('worksheets', 'WorksheetItem')
    roots = None
    for source in Source.objects.all():
        texts = (source.title, source.short_title)
        changed = []
        if not source.grade_from:
            low, high = guess_grades(*texts)
            if not low:
                grades = sorted(set(Worksheet.objects.filter(
                    collection__source_id=source.pk, grade__isnull=False)
                    .values_list('grade', flat=True)))
                grades = [g for g in grades if 1 <= g <= 11]
                if grades:
                    low, high = grades[0], grades[-1]
            if low:
                source.grade_from, source.grade_to = low, high
                changed += ['grade_from', 'grade_to']
        if not source.subject:
            subject = guess_subject(*texts)
            if not subject:
                if roots is None:
                    roots = _root_codes(Topic)
                task_ids = WorksheetItem.objects.filter(
                    worksheet__collection__source_id=source.pk,
                    task__isnull=False).values('task_id')
                counts = Counter(
                    TOPIC_ROOT_SUBJECTS.get(roots.get(topic_id), '')
                    for topic_id in TaskTopic.objects.filter(task_id__in=task_ids)
                    .values_list('topic_id', flat=True))
                counts.pop('', None)
                if counts:
                    subject = counts.most_common(1)[0][0]
            if subject:
                source.subject = subject
                changed.append('subject')
        if changed:
            source.save(update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0037_source_shelf_fields'),
        ('worksheets', '0024_worksheet_presets_pdf_prefix'),
    ]

    operations = [
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]

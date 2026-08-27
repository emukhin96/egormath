"""Сид рубрикатора и перенос старых одиночных классов в GradeBand.

Связи задач со старым деревом тем не переносим — задачи остаются без темы.
Старая автотаблица M2M задач (без through) удаляется: данные не нужны.
"""

from django.db import migrations


def seed_and_migrate_grades(apps, schema_editor):
    from problems.rubricator import migrate_legacy_grades, seed_rubricator
    seed_rubricator()
    migrate_legacy_grades()


def drop_legacy_task_topics(apps, schema_editor):
    # Старый M2M без through: problems_task_topics
    schema_editor.execute('DROP TABLE IF EXISTS problems_task_topics')


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0009_rubricator'),
        ('worksheets', '0014_rubricator'),
    ]

    operations = [
        migrations.RunPython(drop_legacy_task_topics, migrations.RunPython.noop),
        migrations.RunPython(seed_and_migrate_grades, migrations.RunPython.noop),
    ]

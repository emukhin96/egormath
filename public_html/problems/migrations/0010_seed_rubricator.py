"""Сид рубрикатора и перенос старых одиночных классов в GradeBand.

Связи задач уже скопированы в TaskTopic в 0009. Старая автотаблица M2M
убирается, если вдруг осталась после замены поля.
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

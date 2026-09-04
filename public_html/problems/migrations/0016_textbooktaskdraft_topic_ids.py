"""Несколько тем рубрикатора у черновика импорта."""

from django.db import migrations, models


def copy_primary_into_topic_ids(apps, schema_editor):
    Draft = apps.get_model('problems', 'TextbookTaskDraft')
    for draft in Draft.objects.exclude(topic_id=None).iterator():
        draft.topic_ids = [draft.topic_id]
        draft.save(update_fields=['topic_ids'])


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0015_textbooktaskdraft_imported_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='textbooktaskdraft',
            name='topic_ids',
            field=models.JSONField(
                blank=True, default=list,
                verbose_name='Темы рубрикатора'),
        ),
        migrations.AlterField(
            model_name='textbooktaskdraft',
            name='topic',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.PROTECT,
                related_name='textbook_drafts',
                to='problems.topic',
                verbose_name='Основная тема'),
        ),
        migrations.RunPython(
            copy_primary_into_topic_ids, migrations.RunPython.noop),
    ]

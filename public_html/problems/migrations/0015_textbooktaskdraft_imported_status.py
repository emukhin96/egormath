"""Статус «Импортировано» у черновика задачника."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0014_textbook_import_assets_and_topic_candidates'),
    ]

    operations = [
        migrations.AlterField(
            model_name='textbooktaskdraft',
            name='status',
            field=models.CharField(
                choices=[
                    ('needs_review', 'Не проверена'),
                    ('approved', 'Одобрена'),
                    ('conflict', 'Конфликт'),
                    ('skipped', 'Пропущена'),
                    ('imported', 'Импортировано'),
                ],
                default='needs_review',
                max_length=16,
                verbose_name='Статус',
            ),
        ),
    ]

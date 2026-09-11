from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0021_task_full_answer_only'),
    ]

    operations = [
        migrations.AddField(
            model_name='textbooktaskdraft',
            name='exam_item_codes',
            field=models.JSONField(
                blank=True, default=list,
                verbose_name='Коды экзаменационных заданий'),
        ),
        migrations.AddField(
            model_name='textbooktaskdraft',
            name='grade_band_codes',
            field=models.JSONField(
                blank=True, default=list,
                verbose_name='Коды классов'),
        ),
        migrations.AddField(
            model_name='textbooktaskdraft',
            name='tags',
            field=models.JSONField(
                blank=True, default=list,
                verbose_name='Теги источника'),
        ),
    ]

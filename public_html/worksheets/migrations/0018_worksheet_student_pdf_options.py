from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0017_collection_parent_topics'),
    ]

    operations = [
        migrations.AddField(
            model_name='worksheet',
            name='student_pdf_options',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Последние параметры ученического PDF, собранного учителем',
                verbose_name='Оформление PDF для ученика'),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0012_textbookimportbatch_textbooktaskdraft_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='textbooktaskdraft',
            name='images',
            field=models.JSONField(
                blank=True, default=list, verbose_name='Изображения'),
        ),
    ]

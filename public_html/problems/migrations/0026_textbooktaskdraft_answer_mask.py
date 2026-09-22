from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0025_ege_profile_2027'),
    ]

    operations = [
        migrations.AddField(
            model_name='textbooktaskdraft',
            name='answer_mask',
            field=models.TextField(
                blank=True, verbose_name='Маска ответа для ученика'),
        ),
    ]

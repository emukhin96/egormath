# Пояснение рубрики: в корпусе бывают определения длиннее 400 символов.
# CharField + MySQL STRICT режет INSERT (500 на «Загрузить в каталог»).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0015_alter_worksheet_grade_collection_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='worksheetitem',
            name='rubric_note',
            field=models.TextField(blank=True, verbose_name='Пояснение к рубрике'),
        ),
    ]

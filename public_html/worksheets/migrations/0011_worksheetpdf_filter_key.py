from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0010_sharelink_hidden_items'),
    ]

    operations = [
        migrations.AddField(
            model_name='worksheetpdf',
            name='filter_key',
            field=models.CharField(
                blank=True, default='',
                help_text='Пусто — полный листок; иначе идентификатор набора скрытых элементов',
                max_length=40, verbose_name='Ключ скрытий'),
        ),
    ]

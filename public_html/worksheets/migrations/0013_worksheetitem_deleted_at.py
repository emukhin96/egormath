from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0012_worksheetpdf_unique_filter_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='worksheetitem',
            name='deleted_at',
            field=models.DateTimeField(
                blank=True, null=True,
                help_text='Мягкое удаление: элемент можно вернуть кнопкой «Отменить» до следующего удаления',
                verbose_name='Удалено'),
        ),
    ]

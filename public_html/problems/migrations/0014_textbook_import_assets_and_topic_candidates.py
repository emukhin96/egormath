from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0013_textbooktaskdraft_images'),
    ]

    operations = [
        migrations.AddField(
            model_name='textbooktaskdraft',
            name='topic_candidates',
            field=models.JSONField(
                blank=True, default=list,
                verbose_name='Кандидаты рубрикатора'),
        ),
        migrations.CreateModel(
            name='TextbookImportAsset',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name='ID')),
                ('stem', models.CharField(
                    max_length=255, verbose_name='Нормализованное имя')),
                ('original_name', models.CharField(
                    max_length=255, verbose_name='Исходное имя файла')),
                ('file', models.FileField(
                    upload_to='textbook_import_assets/',
                    validators=[django.core.validators.FileExtensionValidator(
                        ['png', 'jpg', 'jpeg', 'pdf'])],
                    verbose_name='Файл')),
                ('batch', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='assets',
                    to='problems.textbookimportbatch',
                    verbose_name='Партия')),
            ],
            options={
                'verbose_name': 'Рисунок партии импорта',
                'verbose_name_plural': 'Рисунки партий импорта',
                'ordering': ['original_name', 'pk'],
            },
        ),
        migrations.AddConstraint(
            model_name='textbookimportasset',
            constraint=models.UniqueConstraint(
                fields=('batch', 'stem'), name='unique_batch_image_stem'),
        ),
    ]

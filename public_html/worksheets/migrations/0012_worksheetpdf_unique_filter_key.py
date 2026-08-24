from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0011_worksheetpdf_filter_key'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='worksheetpdf',
            name='unique_worksheet_pdf',
        ),
        migrations.AddConstraint(
            model_name='worksheetpdf',
            constraint=models.UniqueConstraint(
                fields=('worksheet', 'variant', 'filter_key', 'content_hash'),
                name='unique_worksheet_pdf',
            ),
        ),
    ]

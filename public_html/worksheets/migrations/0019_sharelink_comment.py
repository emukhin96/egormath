from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('worksheets', '0018_worksheet_student_pdf_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='sharelink',
            name='comment',
            field=models.CharField(blank=True, max_length=500, verbose_name='Комментарий для учителя'),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_attach_unattached_students'),
        ('assignments', '0011_alter_review_grade'),
    ]

    operations = [
        migrations.AddField(
            model_name='assignment',
            name='recipient_origin_known',
            field=models.BooleanField(default=False, verbose_name='Способ выдачи сохранён'),
        ),
        migrations.AddField(
            model_name='assignment',
            name='source_groups',
            field=models.ManyToManyField(blank=True, related_name='worksheet_assignments', to='accounts.studentgroup', verbose_name='Группы при выдаче'),
        ),
    ]

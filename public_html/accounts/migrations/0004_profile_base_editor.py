from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_attach_unattached_students'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='base_editor',
            field=models.BooleanField(
                default=False,
                help_text='Для учителей: право менять общие задачи напрямую. '
                          'У суперпользователя подразумевается всегда; '
                          'остальные правят общие задачи только копией для '
                          'своего листка (accounts/permissions.py).',
                verbose_name='Правит общую базу задач'),
        ),
    ]

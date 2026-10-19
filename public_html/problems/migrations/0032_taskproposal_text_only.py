# Предложения только текстом (решение 7 от 19.10.2026): вид, копия-версия и
# снимок полей больше не хранятся, ответ редактора — статус без текста.
# На проде очереди ещё нет, поэтому данные не переносятся.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0031_taskproposal_kind_labels'),
    ]

    operations = [
        migrations.RemoveField(model_name='taskproposal', name='kind'),
        migrations.RemoveField(model_name='taskproposal', name='variant'),
        migrations.RemoveField(model_name='taskproposal', name='snapshot'),
        migrations.RemoveField(model_name='taskproposal', name='resolution_note'),
        migrations.AlterField(
            model_name='taskproposal',
            name='message',
            field=models.TextField(verbose_name='Что исправить'),
        ),
        migrations.AlterField(
            model_name='taskproposal',
            name='seen_by_author_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Статус просмотрен автором'),
        ),
        migrations.AlterField(
            model_name='taskproposal',
            name='task',
            field=models.ForeignKey(help_text='Общая задача, к которой предложение', on_delete=models.deletion.CASCADE, related_name='proposals', to='problems.task', verbose_name='Задача'),
        ),
    ]

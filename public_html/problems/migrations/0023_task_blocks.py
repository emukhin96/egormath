# Сформировано Django 4.2.30 on 2026-09-10 22:57

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0022_textbooktaskdraft_exam_and_tags'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='block_position',
            field=models.PositiveSmallIntegerField(default=0, editable=False, verbose_name='Номер в блоке'),
        ),
        migrations.AddField(
            model_name='textbooktaskdraft',
            name='block_position',
            field=models.PositiveSmallIntegerField(default=0, editable=False, verbose_name='Номер в блоке'),
        ),
        migrations.CreateModel(
            name='TaskBlock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=190, verbose_name='Ключ блока')),
                ('title', models.CharField(max_length=190, verbose_name='Название')),
                ('size', models.PositiveSmallIntegerField(default=5, verbose_name='Число вопросов')),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='task_blocks', to='problems.source')),
            ],
        ),
        migrations.AddField(
            model_name='task',
            name='block',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='tasks', to='problems.taskblock', verbose_name='Общий блок'),
        ),
        migrations.AddField(
            model_name='textbooktaskdraft',
            name='block',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='drafts', to='problems.taskblock', verbose_name='Общий блок'),
        ),
        migrations.AddConstraint(
            model_name='taskblock',
            constraint=models.UniqueConstraint(fields=('source', 'key'), name='unique_source_task_block'),
        ),
    ]

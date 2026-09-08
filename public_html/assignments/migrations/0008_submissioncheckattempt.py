from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('assignments', '0007_answer_json'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubmissionCheckAttempt',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False,
                    verbose_name='ID')),
                ('number', models.PositiveIntegerField(
                    verbose_name='Номер попытки')),
                ('result', models.CharField(
                    choices=[
                        ('ok', 'Верно'),
                        ('wrong', 'Неверно'),
                        ('unknown', 'Не удалось проверить'),
                        ('incomplete', 'Ответ заполнен частично'),
                    ], max_length=12, verbose_name='Результат')),
                ('snapshot', models.JSONField(
                    default=dict, verbose_name='Снимок ответа')),
                ('created_at', models.DateTimeField(
                    auto_now_add=True, verbose_name='Время попытки')),
                ('submission', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='check_history', to='assignments.submission',
                    verbose_name='Ответ')),
            ],
            options={
                'verbose_name': 'Попытка самопроверки',
                'verbose_name_plural': 'Попытки самопроверки',
                'ordering': ['number'],
            },
        ),
        migrations.AddConstraint(
            model_name='submissioncheckattempt',
            constraint=models.UniqueConstraint(
                fields=('submission', 'number'),
                name='unique_check_attempt_submission_number'),
        ),
    ]

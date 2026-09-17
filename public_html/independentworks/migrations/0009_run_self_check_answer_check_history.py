from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('independentworks', '0008_attempt_clipboard_exempt_run_restrict_clipboard')]

    operations = [
        migrations.AddField(
            model_name='run', name='self_check',
            field=models.BooleanField(default=False)),
        migrations.AddField(
            model_name='answer', name='check_revealed',
            field=models.BooleanField(default=False)),
        migrations.CreateModel(
            name='AnswerCheckAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.PositiveIntegerField()),
                ('result', models.CharField(max_length=12)),
                ('snapshot', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('answer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='check_history', to='independentworks.answer')),
            ],
            options={'ordering': ['number']},
        ),
        migrations.AddConstraint(
            model_name='answercheckattempt',
            constraint=models.UniqueConstraint(fields=('answer', 'number'), name='iw_unique_check_attempt_answer_number')),
    ]

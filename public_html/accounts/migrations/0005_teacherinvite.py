# Приглашения учителей и поля профиля для них (docs/USERS_PLAN.md, раздел 6).

import accounts.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_profile_base_editor'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='invited_by',
            field=models.ForeignKey(blank=True, help_text='Для учителей: кто выписал приглашение.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='invited_teachers', to=settings.AUTH_USER_MODEL, verbose_name='Пригласил'),
        ),
        migrations.AddField(
            model_name='profile',
            name='onboarding_done_at',
            field=models.DateTimeField(blank=True, help_text='Для учителей: когда закрыта карточка «Первые шаги».', null=True, verbose_name='Первые шаги скрыты'),
        ),
        migrations.AddField(
            model_name='profile',
            name='student_code',
            field=models.CharField(blank=True, help_text='Для учителей: ученик по ссылке /accounts/register/?t=<код> записывается к этому учителю.', max_length=8, null=True, unique=True, verbose_name='Код ссылки регистрации'),
        ),
        migrations.CreateModel(
            name='TeacherInvite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(default=accounts.models.generate_invite_token, editable=False, max_length=64, unique=True, verbose_name='Токен')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создано')),
                ('expires_at', models.DateTimeField(default=accounts.models.default_invite_expiry, verbose_name='Действует до')),
                ('note', models.CharField(blank=True, help_text='Кому предназначено — для списка приглашений.', max_length=200, verbose_name='Заметка')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='Почта')),
                ('base_editor', models.BooleanField(default=False, help_text='Выдать право менять общие задачи сразу при регистрации.', verbose_name='Право править базу')),
                ('used_at', models.DateTimeField(blank=True, null=True, verbose_name='Погашено')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='teacher_invites', to=settings.AUTH_USER_MODEL, verbose_name='Выписал')),
                ('used_by', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='teacher_invite', to=settings.AUTH_USER_MODEL, verbose_name='Зарегистрировался')),
            ],
            options={
                'verbose_name': 'Приглашение учителя',
                'verbose_name_plural': 'Приглашения учителей',
                'ordering': ['-created_at'],
            },
        ),
    ]

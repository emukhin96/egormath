"""Восстановление пароля по почте (решение 2 плана пользователей, PR 5).

Стандартные ``PasswordReset*``-view Django с шаблонами сайта. Ссылка
«Забыли пароль?» на странице входа и сама форма есть только при настроенной
почте (``core.mailing.mail_enabled``); без почты страница объясняет, к кому
обратиться. Письмо — текстом, в нём логин: у ученика с несколькими
аккаунтами на один адрес придёт по письму на каждый. Если адреса нет в
системе или у пользователя нет почты, страница «письмо отправлено» та же —
по ответу не проверить, чей адрес в базе. Сбой SMTP страницу не роняет:
``PasswordResetForm`` Django пишет его в лог ``django.contrib.auth``.
"""
from django.contrib.auth import views as auth_views
from django.shortcuts import render
from django.urls import reverse_lazy

from core.mailing import mail_enabled


class PasswordResetView(auth_views.PasswordResetView):
    template_name = 'accounts/password_reset_form.html'
    email_template_name = 'accounts/password_reset_email.txt'
    subject_template_name = 'accounts/password_reset_subject.txt'
    success_url = reverse_lazy('password_reset_done')

    def dispatch(self, request, *args, **kwargs):
        if not mail_enabled():
            return render(request, 'accounts/password_reset_unavailable.html')
        return super().dispatch(request, *args, **kwargs)


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'

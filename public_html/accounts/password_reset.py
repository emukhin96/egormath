"""Восстановление пароля по почте (решение 2 плана пользователей, PR 5).

Стандартные ``PasswordReset*``-view Django с шаблонами сайта. Ссылка
«Забыли пароль?» на странице входа и сама форма есть только при настроенной
почте (``core.mailing.mail_enabled``); без почты страница объясняет, к кому
обратиться. Письмо — текстом, в нём логин: у ученика с несколькими
аккаунтами на один адрес придёт по письму на каждый. Если адреса нет в
системе или у пользователя нет почты, страница «письмо отправлено» та же —
по ответу не проверить, чей адрес в базе. Сбой SMTP страницу не роняет:
``PasswordResetForm`` Django пишет его в лог ``django.contrib.auth``.

Форма анонимная, поэтому частота ограничена (``throttled``): не больше
``RESET_PER_EMAIL`` запросов на один адрес и ``RESET_PER_IP`` с одного IP за
``RESET_WINDOW`` секунд; сверх лимита письмо не уходит, а страница та же —
иначе по ответу можно было бы и адрес в базе угадать, и ящик завалить, и
дневной лимит отправки Timeweb выбрать. Счётчики в кэше ``default``
(locmem): у gunicorn они свои на каждый воркер, то есть реальный потолок в
``workers`` раз выше, для защиты от скрипта этого достаточно.
"""
import hashlib
import logging

from django.contrib.auth import views as auth_views
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse_lazy

from core.mailing import mail_enabled

log = logging.getLogger(__name__)

RESET_WINDOW = 60 * 60       # секунд
RESET_PER_EMAIL = 3          # писем на один адрес за окно
RESET_PER_IP = 30            # запросов с одного IP за окно: класс за школьным NAT


def client_ip(request):
    """IP клиента: за Caddy — первый адрес из X-Forwarded-For, иначе
    REMOTE_ADDR. Подделка заголовка обходит только лимит по IP, лимит по
    адресу остаётся."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    first = forwarded.split(',')[0].strip()
    return first or request.META.get('REMOTE_ADDR', '')


def throttled(kind, value, limit, window=RESET_WINDOW):
    """Увеличить счётчик ``kind:value`` и сказать, превышен ли ``limit`` за
    ``window``. Значение хэшируется: адрес в ключе кэша не нужен."""
    key = f'pwreset:{kind}:{hashlib.sha1(value.encode()).hexdigest()}'
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:  # ключ истёк между add и incr
        cache.add(key, 1, window)
        count = 1
    return count > limit


class PasswordResetView(auth_views.PasswordResetView):
    template_name = 'accounts/password_reset_form.html'
    email_template_name = 'accounts/password_reset_email.txt'
    subject_template_name = 'accounts/password_reset_subject.txt'
    success_url = reverse_lazy('password_reset_done')

    def dispatch(self, request, *args, **kwargs):
        if not mail_enabled():
            return render(request, 'accounts/password_reset_unavailable.html')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        email = form.cleaned_data['email'].strip().lower()
        by_email = throttled('email', email, RESET_PER_EMAIL)
        by_ip = throttled('ip', client_ip(self.request), RESET_PER_IP)
        if by_email or by_ip:
            log.warning('Сброс пароля: лимит запросов %s, письмо не отправлено',
                        'на адрес' if by_email else 'с IP')
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'

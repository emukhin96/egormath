"""``manage.py mail_check <адрес>`` — тестовое письмо и сводка настроек почты.

Печатает бэкенд, хост, порт, режим шифрования, логин и отправителя — без
пароля, — затем отправляет письмо. На проде:
``deploy/vps/manage.sh mail_check адрес@example.com`` (deploy/MAIL.md,
раздел «Проверка»). Сбой SMTP — ошибка команды с ответом сервера.
"""
from django.conf import settings
from django.core import mail
from django.core.management.base import BaseCommand, CommandError

from core.mailing import SMTP_BACKEND, mail_enabled


class Command(BaseCommand):
    help = 'Отправить тестовое письмо и показать, через что уходит почта сайта'

    def add_arguments(self, parser):
        parser.add_argument('recipient', help='Адрес, на который отправить тестовое письмо')

    def handle(self, recipient, **options):
        backend = getattr(settings, 'EMAIL_BACKEND', SMTP_BACKEND)
        self.stdout.write(f'Бэкенд: {backend}')
        if backend == SMTP_BACKEND:
            if settings.EMAIL_USE_SSL:
                mode = 'SSL с подключения'
            elif settings.EMAIL_USE_TLS:
                mode = 'STARTTLS'
            else:
                mode = 'без шифрования'
            host = settings.EMAIL_HOST or '(EMAIL_HOST не задан)'
            self.stdout.write(
                f'SMTP: {host}:{settings.EMAIL_PORT}, {mode}, '
                f'логин {settings.EMAIL_HOST_USER or "(пусто)"}, '
                f'таймаут {settings.EMAIL_TIMEOUT} с')
        self.stdout.write(f'Отправитель: {settings.DEFAULT_FROM_EMAIL}')
        editors = ', '.join(settings.PROPOSAL_NOTIFY_EMAILS) or '(нет — письма о предложениях не уходят)'
        self.stdout.write(f'Адреса редакторов (PROPOSAL_NOTIFY_EMAILS): {editors}')
        if not mail_enabled():
            raise CommandError(
                'EMAIL_HOST не задан — письма с сайта не отправляются. Настройка: deploy/MAIL.md')
        body = (
            'Это тестовое письмо с сайта «Математика» (manage.py mail_check).\n'
            f'Если вы его читаете, почта настроена: {backend}'
            + (f', {settings.EMAIL_HOST}:{settings.EMAIL_PORT}' if backend == SMTP_BACKEND else '')
            + '.\n')
        try:
            sent = mail.send_mail(
                'Проверка почты сайта «Математика»', body,
                settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False)
        except Exception as exc:  # noqa: BLE001 — показать причину, не трассировку
            raise CommandError(f'Сервер почты не принял письмо: {exc}') from exc
        if not sent:
            raise CommandError('Письмо не отправлено: бэкенд вернул 0')
        self.stdout.write(self.style.SUCCESS(f'Тестовое письмо отправлено на {recipient}'))

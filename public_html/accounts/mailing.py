"""Письма раздела «Учителя»: приглашение учителя по почте (PR 5 плана
пользователей).

Текстом, от ``DEFAULT_FROM_EMAIL``, через ``core.mailing.send_quietly``:
сбой SMTP — в лог, администратор видит сообщение об ошибке и копирует
ссылку вручную. Без настроенной почты (``mail_enabled``) кнопок
«Отправить письмом» на странице нет.
"""
from django.utils import timezone

from core.mailing import send_quietly

INVITE_SUBJECT = 'Приглашение на сайт «Математика»'


def send_teacher_invite(invite, url):
    """Письмо приглашённому: кто пригласил, ссылка, до какого числа.
    ``url`` — абсолютная ссылка на регистрацию (view знает хост)."""
    inviter = invite.created_by.get_full_name() or invite.created_by.username
    until = timezone.localtime(invite.expires_at).strftime('%d.%m.%Y')
    body = '\n'.join([
        'Здравствуйте!',
        '',
        f'{inviter} приглашает вас зарегистрироваться как учитель на сайте «Математика».',
        '',
        f'Ссылка для регистрации: {url}',
        '',
        f'Ссылка действует до {until} и подходит для одной регистрации.',
        'Если вы не ждали этого письма, просто не открывайте ссылку.',
    ])
    return send_quietly(INVITE_SUBJECT, body, [invite.email])

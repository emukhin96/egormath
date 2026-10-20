"""Общая почта сайта: включена ли отправка и «тихая» отправка письма.

Почта настраивается секретами ``EMAIL_*`` (``core/settings.py``, инструкция
для прода — ``deploy/MAIL.md``). Без ``EMAIL_HOST`` на проде письма не
отправляются, а ссылки и кнопки «по почте» (восстановление пароля,
приглашение учителя письмом) спрятаны; локально при ``DEBUG`` письма
печатаются в консоль ``runserver``, в тестах — ``locmem``. Значения
секретов сюда не попадают: в лог идёт только тема письма и ошибка SMTP.
"""
import logging

from django.conf import settings
from django.core import mail

log = logging.getLogger(__name__)

SMTP_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'


def mail_enabled():
    """SMTP настроен или бэкенд не почтовый (console локально, locmem в
    тестах) — тогда письмо есть куда отдать."""
    backend = getattr(settings, 'EMAIL_BACKEND', SMTP_BACKEND)
    return bool(getattr(settings, 'EMAIL_HOST', '')) or backend != SMTP_BACKEND


def send_quietly(subject, body, recipients):
    """Письмо текстом от ``DEFAULT_FROM_EMAIL``. Сбой почты не ломает
    основной сценарий (предложение создано, приглашение выписано): ошибка
    SMTP — в лог, вызывающему — ``False``."""
    recipients = [r for r in recipients if r]
    if not recipients or not mail_enabled():
        return False
    try:
        sent = mail.send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                              recipients, fail_silently=False)
    except Exception:  # noqa: BLE001 — любой сбой почты не трогает основной сценарий
        log.exception('Не удалось отправить письмо «%s»', subject)
        return False
    if not sent:
        log.warning('Письмо «%s» не отправлено: сервер почты не принял', subject)
    return bool(sent)

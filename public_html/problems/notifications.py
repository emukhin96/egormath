"""Почтовые уведомления об очереди предложений (docs/USERS_PLAN.md, 5.4).

Уровень 1 — счётчики в кабинете — работает всегда; почта — только если в
``.secrets/`` настроен SMTP (``EMAIL_HOST``) и адреса редакторов
(``PROPOSAL_NOTIFY_EMAILS``). Локально при ``DEBUG`` без ``EMAIL_HOST``
письма печатаются в консоль ``runserver`` (console backend в settings).
Сбой SMTP не должен ломать отправку предложения: ``fail_silently=True``,
ошибка только в лог. Значения секретов сюда не попадают.
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


def _send(subject, body, recipients):
    recipients = [r for r in recipients if r]
    if not recipients or not mail_enabled():
        return False
    try:
        sent = mail.send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                              recipients, fail_silently=True)
    except Exception:  # noqa: BLE001 — любой сбой почты не трогает основной сценарий
        log.exception('Не удалось отправить письмо «%s»', subject)
        return False
    if not sent:
        log.warning('Письмо «%s» не отправлено: сервер почты не принял', subject)
    return bool(sent)


def notify_new_proposal(proposal, url=None):
    """Редакторам: новое предложение. ``url`` — абсолютная ссылка на
    страницу предложения (view знает хост запроса, модуль — нет)."""
    subject = f'Задача #{proposal.task_id}: предложено исправление'
    lines = [f'{proposal.author_name} предлагает исправить задачу #{proposal.task_id}:',
             '', proposal.message.strip()]
    if url:
        lines += ['', f'Открыть: {url}']
    return _send(subject, '\n'.join(lines), settings.PROPOSAL_NOTIFY_EMAILS)


def notify_resolved(proposal, url=None):
    """Автору: статус от редактора, если у автора указана почта."""
    email = (proposal.author.email or '').strip()
    if not email:
        return False
    verdict = 'принято' if proposal.status == proposal.STATUS_ACCEPTED else 'отклонено'
    subject = f'Ваше предложение по задаче #{proposal.task_id} {verdict}'
    lines = [f'Предложение по задаче #{proposal.task_id} {verdict}.']
    if url:
        lines += ['', f'Мои предложения: {url}']
    return _send(subject, '\n'.join(lines), [email])

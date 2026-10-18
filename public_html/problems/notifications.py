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


def _author_name(user):
    return user.get_full_name() or user.username


def notify_new_proposal(proposal, url=None):
    """Редакторам базы: новое предложение. ``url`` — абсолютная ссылка на
    страницу предложения (view знает хост запроса, модуль — нет)."""
    task_id = proposal.task_id
    if proposal.kind == proposal.KIND_NEW:
        subject = f'Задача #{task_id}: предложена в общие задачи'
    else:
        subject = f'Задача #{task_id}: предложено исправление'
    lines = [
        f'{_author_name(proposal.author)} — {proposal.get_kind_display().lower()}.',
        '',
        proposal.message.strip() or '(без комментария)',
    ]
    if proposal.variant_id:
        lines += ['', f'Приложена локальная копия #{proposal.variant_id}.']
    if url:
        lines += ['', f'Открыть: {url}']
    return _send(subject, '\n'.join(lines), settings.PROPOSAL_NOTIFY_EMAILS)


def notify_resolved(proposal, url=None):
    """Автору: решение редактора, если у автора указана почта."""
    email = (proposal.author.email or '').strip()
    if not email:
        return False
    verdict = 'принято' if proposal.status == proposal.STATUS_ACCEPTED else 'отклонено'
    subject = f'Ваше предложение по задаче #{proposal.task_id} {verdict}'
    lines = [f'Предложение по задаче #{proposal.task_id} {verdict}.']
    if proposal.resolution_note.strip():
        lines += ['', 'Ответ редактора:', proposal.resolution_note.strip()]
    if url:
        lines += ['', f'Мои предложения: {url}']
    return _send(subject, '\n'.join(lines), [email])

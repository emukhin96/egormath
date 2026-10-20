"""Почтовые уведомления об очереди предложений (docs/USERS_PLAN.md, 5.4).

Уровень 1 — счётчики в кабинете — работает всегда; почта — только если в
``.secrets/`` настроен SMTP (``EMAIL_HOST``, см. ``deploy/MAIL.md``) и адреса
редакторов (``PROPOSAL_NOTIFY_EMAILS``). Локально при ``DEBUG`` без
``EMAIL_HOST`` письма печатаются в консоль ``runserver`` (console backend в
settings). Отправитель — ``DEFAULT_FROM_EMAIL``; сбой SMTP не должен ломать
отправку предложения: ошибка только в лог (``core.mailing.send_quietly``).
Значения секретов сюда не попадают.
"""
from django.conf import settings

from core.mailing import mail_enabled, send_quietly as _send  # noqa: F401 — mail_enabled реэкспорт для тестов


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

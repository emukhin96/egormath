"""Очередь предложений исправлений общих задач (docs/USERS_PLAN.md, разделы
5 и 15, решение 7 от 19.10.2026).

Предложение — только текст по общей задаче: автор (обычно приглашённый
учитель) описывает, что исправить; редактор читает, вносит правку на
карточке задачи сам и ставит статус «Принято» или «Отклонено». Снимков
полей, приложенных копий и применения по полям нет — решение всегда за
человеком и руками человека.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from accounts.permissions import base_editor_required, visible_tasks
from .models import Task, TaskProposal
from .notifications import notify_new_proposal, notify_resolved

MASK_PREFILL = 'Предлагаю маску ответа:\n'
PROPOSE_LABEL = 'Предложить исправление'
# «Мои предложения»: строк на странице общего списка (по дате отправки).
# Непросмотренные статусы — отдельным блоком над списком целиком, чтобы
# отметка просмотра не меняла порядок и разбиение на страницы.
MINE_PAGE = 50


class ProposalError(Exception):
    """Отказ создать или решить предложение — текст для пользователя."""


def open_proposal(user, task):
    return TaskProposal.objects.filter(
        task=task, author=user, status=TaskProposal.STATUS_NEW).first()


def proposal_options(user, task):
    """Что показать на карточке: ``None`` — предложение не предусмотрено
    (своя задача или локальная копия правятся напрямую), иначе словарь с
    ``open`` — уже отправленным и ещё не решённым предложением автора.
    Роль здесь не проверяется: редактору карточка кнопку не показывает
    (editor.context), но сервер ему не запрещает."""
    if not task.is_shared or task.variant_of_id:
        return None
    return {'task': task, 'label': PROPOSE_LABEL, 'open': open_proposal(user, task)}


@transaction.atomic
def create_proposal(user, task, message):
    """Новое предложение. Повторное открытое предложение той же задачи от
    того же автора не создаётся — строка задачи блокируется, чтобы два
    клика не дали два."""
    message = (message or '').strip()
    if message == MASK_PREFILL.strip():
        # Одна заготовка «Предлагаю маску ответа:» без самой маски — пустое
        # предложение; required у textarea она тоже «выполняет» (7bc2877)
        message = ''
    task = Task.objects.select_for_update().get(pk=task.pk)
    if not task.is_shared or task.variant_of_id:
        raise ProposalError('Предложить исправление можно только для общей задачи.')
    if not message:
        raise ProposalError('Напишите, что исправить.')
    if open_proposal(user, task):
        raise ProposalError('Ваше предложение по этой задаче уже ждёт ответа редактора.')
    return TaskProposal.objects.create(task=task, author=user, message=message)


@transaction.atomic
def resolve_proposal(proposal, status, user):
    """Статус «Принято» / «Отклонено»: саму задачу редактор правит на
    карточке, здесь только отметка и сброс просмотра у автора."""
    if status not in (TaskProposal.STATUS_ACCEPTED, TaskProposal.STATUS_REJECTED):
        raise ProposalError('Неизвестный статус.')
    proposal = TaskProposal.objects.select_for_update().get(pk=proposal.pk)
    if not proposal.is_open:
        raise ProposalError('Предложение уже обработано.')
    proposal.status = status
    proposal.resolved_at = timezone.now()
    proposal.resolved_by = user
    proposal.seen_by_author_at = None
    proposal.save(update_fields=['status', 'resolved_at', 'resolved_by',
                                 'seen_by_author_at'])
    return proposal


# ---- views ----------------------------------------------------------------

def _safe_next(request, target):
    """Адрес возврата только на наш хост: чужой адрес или схема вроде
    ``javascript:`` отбрасываются и для редиректа, и для ссылки в шаблоне."""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return ''


def _back(request, task):
    """После отправки — туда, откуда пришли (поле next), иначе на карточку."""
    target = _safe_next(request, request.POST.get('next') or request.GET.get('next'))
    return redirect(target) if target else redirect('task_detail', pk=task.pk)


@teacher_required
def task_propose(request, pk):
    """GET — отдельная страница с той же формой, что в диалоге карточки
    (ссылка «Предложить маску» из самостоятельных, работа без JS);
    POST — создание предложения и возврат назад."""
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    options = proposal_options(request.user, task)
    if options is None:
        raise PermissionDenied('Для этой задачи предложение не предусмотрено.')
    if request.method == 'POST':
        try:
            proposal = create_proposal(request.user, task, request.POST.get('message', ''))
        except ProposalError as exc:
            level = messages.warning if 'уже ждёт' in str(exc) else messages.error
            level(request, str(exc))
            return _back(request, task)
        notify_new_proposal(proposal, url=request.build_absolute_uri(
            reverse('proposal_detail', args=[proposal.pk])))
        messages.success(request, 'Предложение отправлено редакторам.')
        return _back(request, task)
    return render(request, 'problems/propose.html', {
        'task': task, 'propose': options,
        'prefill': MASK_PREFILL if request.GET.get('mask') else '',
        'next': _safe_next(request, request.GET.get('next', '')),
    })


@teacher_required
def proposals_mine(request):
    """Свои предложения со статусом. Непросмотренные решения показываются
    все сразу отдельным блоком над списком (он у автора всегда короткий) и
    после показа считаются просмотренными; общий список — по дате отправки
    постранично, его порядок от отметки не зависит."""
    own = TaskProposal.objects.filter(author=request.user).select_related('task', 'resolved_by')
    unread = list(own.filter(seen_by_author_at__isnull=True)
                  .exclude(status=TaskProposal.STATUS_NEW)
                  .order_by('-resolved_at', '-pk'))
    page = Paginator(own.order_by('-created_at', '-pk'), MINE_PAGE).get_page(
        request.GET.get('page'))
    proposals = list(page)
    unread_ids = {p.pk for p in unread}
    for proposal in unread + proposals:
        proposal.unread = proposal.pk in unread_ids
    if unread_ids:
        TaskProposal.objects.filter(pk__in=unread_ids, author=request.user).update(
            seen_by_author_at=timezone.now())
    return render(request, 'problems/proposals_mine.html', {
        'unread': unread, 'proposals': proposals, 'page': page,
        'unread_total': len(unread), 'params': request.GET.urlencode(),
    })


@base_editor_required
def proposal_list(request):
    status = request.GET.get('status', 'new')
    if status not in ('new', 'all'):
        status = 'new'
    queryset = TaskProposal.objects.select_related('task', 'author', 'resolved_by')
    if status == 'new':
        queryset = queryset.filter(status=TaskProposal.STATUS_NEW)
    page = Paginator(queryset, 50).get_page(request.GET.get('page'))
    return render(request, 'problems/proposal_list.html', {
        'page': page, 'status': status,
        'status_choices': [('new', 'Новые'), ('all', 'Все')],
        'new_total': TaskProposal.objects.filter(status=TaskProposal.STATUS_NEW).count(),
        'params': request.GET.urlencode(),
    })


def _proposal(pk):
    return get_object_or_404(
        TaskProposal.objects.select_related('task', 'author', 'resolved_by'), pk=pk)


@base_editor_required
def proposal_detail(request, pk):
    proposal = _proposal(pk)
    return render(request, 'problems/proposal_detail.html', {
        'proposal': proposal, 'task': proposal.task,
    })


def _resolve_view(request, pk, status, done):
    proposal = _proposal(pk)
    try:
        proposal = resolve_proposal(proposal, status, request.user)
    except ProposalError as exc:
        messages.error(request, str(exc))
        return redirect('proposal_detail', pk=pk)
    notify_resolved(proposal, url=request.build_absolute_uri(reverse('proposals_mine')))
    messages.success(request, done)
    return redirect('proposal_detail', pk=pk)


@base_editor_required
@require_POST
def proposal_accept(request, pk):
    """«Принято»: правку редактор уже внёс на карточке задачи."""
    return _resolve_view(request, pk, TaskProposal.STATUS_ACCEPTED, 'Предложение принято.')


@base_editor_required
@require_POST
def proposal_reject(request, pk):
    return _resolve_view(request, pk, TaskProposal.STATUS_REJECTED, 'Предложение отклонено.')

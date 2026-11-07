"""Аналоги на карточке задачи: блок «Аналоги» и ручная семья редактора.

Список строит ``independentworks.analog_lists``; здесь — контекст блока и
действия редактора «Отвязать» / «Связать с задачей №…».
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.permissions import base_editor_required, cart_tasks, is_base_editor, visible_tasks
from independentworks import analog_lists


def card_context(request, task, item=None):
    """Контекст ``problems/_analogs.html``: аналоги видимы учителю, блок без
    аналогов не показывается (редактору — только форма «Связать»)."""
    analogs, total = analog_lists.analog_tasks(request.user, task)
    from assignments.task_usage import attach_usage
    attach_usage(request, analogs)
    editor = is_base_editor(request.user)
    ctx = {'analogs': analogs, 'analogs_total': total, 'analogs_more': max(total - len(analogs), 0),
           'analog_editor': editor, 'analog_next': request.get_full_path()}
    if item is not None and not task.block_id:
        from worksheets.analog_views import row_actions_context
        ctx.update(row_actions_context(item))
    return ctx


def _back(request, task):
    target = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        target = reverse('task_detail', args=[task.pk])
    return redirect(target.split('#')[0] + '#analogs')


@base_editor_required
@require_POST
def task_analog_unlink(request, pk):
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    analog = get_object_or_404(visible_tasks(request.user), pk=request.POST.get('task'))
    if analog_lists.unlink(task, analog, request.user):
        messages.success(request, f'Задача #{analog.pk} больше не аналог задачи #{task.pk}.')
    else:
        messages.error(request, f'Задача #{analog.pk} не связана с задачей #{task.pk}.')
    return _back(request, task)


@base_editor_required
@require_POST
def task_analog_link(request, pk):
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    raw = request.POST.get('target', '').strip().lstrip('#№ ')
    target = cart_tasks(request.user).filter(pk=int(raw)).first() if raw.isdigit() else None
    if target is None:
        messages.error(request, f'Задача №{raw or "—"} не найдена.')
    elif analog_lists.catalog_original(target).pk == analog_lists.catalog_original(task).pk:
        messages.error(request, 'Это та же задача.')
    else:
        analog_lists.link(task, target, request.user)
        messages.success(request, f'Задача #{target.pk} связана с задачей #{task.pk} как аналог.')
    return _back(request, task)

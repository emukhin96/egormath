"""Очередь предложений исправлений общей базы (docs/USERS_PLAN.md, раздел 5).

Автор (обычно приглашённый учитель) предлагает исправить общую задачу
(``fix``, при желании приложив свою локальную копию как предложенную
версию) или принять свою личную задачу в базу (``new``). Редактор базы
видит снимок рядом с задачей в базе, применяет выбранные поля теми же
формами, что и карточка задачи (``editor.block_form``, формсет
подпунктов: валидация масок, ``updated_at`` для перепроверки), или
отклоняет с причиной. Решение всегда за человеком, авто-слияния нет.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from accounts.permissions import base_editor_required, visible_tasks
from .editor import BLOCKS, StructureFormSet, block_form
from .models import Task, TaskProposal
from .notifications import notify_new_proposal, notify_resolved

# Поля снимка — одни и те же у задачи и у подпункта.
FIELDS = ('text_latex', 'author_answer_latex', 'answer_latex',
          'author_solution_latex', 'solution_latex', 'answer_mask')
FIELD_LABELS = {
    'text_latex': 'Условие',
    'author_answer_latex': 'Авторский ответ',
    'answer_latex': 'Редакторский / AI ответ',
    'author_solution_latex': 'Авторское решение',
    'solution_latex': 'Редакторское / AI решение',
    'answer_mask': 'Маска ответа',
    'full_answer_only': 'Только развёрнутый ответ',
}
# Чекбоксы «Применить»: ключ — блок редактора (editor.BLOCKS), кроме
# «подпункты» — это формсет структуры. Ответ, решение и маска применяются и
# к подпунктам по порядку.
SECTIONS = [
    ('condition', 'Условие'),
    ('answer', 'Ответ'),
    ('solution', 'Решение'),
    ('mask', 'Маска ответа'),
    ('subitems', 'Подпункты'),
]
SECTION_FIELDS = {
    'condition': ('text_latex',),
    'answer': ('author_answer_latex', 'answer_latex'),
    'solution': ('author_solution_latex', 'solution_latex'),
    'mask': ('answer_mask', 'full_answer_only'),
}
SECTION_LABELS = dict(SECTIONS)
MASK_PREFILL = 'Предлагаю маску ответа:\n'
# «Мои предложения»: строк на странице общего списка (по дате отправки).
# Непросмотренные ответы — отдельным блоком над списком целиком, чтобы
# отметка просмотра не меняла порядок и разбиение на страницы.
MINE_PAGE = 50


class ProposalError(Exception):
    """Отказ создать или применить предложение — текст для пользователя."""


def snapshot_of(task):
    """Поля задачи и подпунктов по порядку: предложенная версия на момент
    отправки, независимая от дальнейших правок копии."""
    data = {field: getattr(task, field) or '' for field in FIELDS}
    data['full_answer_only'] = bool(task.full_answer_only)
    data['subitems'] = [
        {'order': sub.order, **{field: getattr(sub, field) or '' for field in FIELDS}}
        for sub in task.subitems.all()]
    return data


def own_variants(user, task):
    """Локальные копии этой задачи у автора — их можно приложить."""
    return Task.objects.filter(variant_of=task, created_by=user).order_by('-updated_at', '-pk')


def open_proposal(user, task):
    return TaskProposal.objects.filter(
        task=task, author=user, status=TaskProposal.STATUS_NEW).first()


def proposal_options(user, task):
    """Что можно предложить с этой карточки: ``None`` — ничего.

    Общая задача — исправление (с выбором своей локальной копии, если есть);
    своя локальная копия общей задачи — «предложить эту версию»; своя личная
    задача — принять в базу. Роль здесь не проверяется: редактор базы тоже
    вправе предложить, но карточка ему кнопку не показывает (editor.context).
    """
    if task.variant_of_id:
        original = task.variant_of
        if task.created_by_id != user.pk or not original.is_shared:
            return None
        return {'kind': TaskProposal.KIND_FIX, 'task': original, 'variant': task,
                'label': 'Предложить эту версию в базу', 'variants': [],
                'open': open_proposal(user, original)}
    if task.is_shared:
        return {'kind': TaskProposal.KIND_FIX, 'task': task, 'variant': None,
                'label': 'Предложить исправление',
                'variants': list(own_variants(user, task)),
                'open': open_proposal(user, task)}
    if task.created_by_id == user.pk:
        return {'kind': TaskProposal.KIND_NEW, 'task': task, 'variant': None,
                'label': 'Предложить задачу в общую базу', 'variants': [],
                'open': open_proposal(user, task)}
    return None


@transaction.atomic
def create_proposal(user, task, *, kind, message='', variant=None):
    """Новое предложение со снимком копии (или самой личной задачи).
    Повторное открытое предложение той же задачи от того же автора не
    создаётся — строка задачи блокируется, чтобы два клика не дали два."""
    message = (message or '').strip()
    task = Task.objects.select_for_update().get(pk=task.pk)
    if kind == TaskProposal.KIND_FIX:
        if not task.is_shared or task.variant_of_id:
            raise ProposalError('Предложить исправление можно только для задачи общей базы.')
        if variant is not None and (variant.variant_of_id != task.pk
                                    or variant.created_by_id != user.pk):
            raise ProposalError('Приложить можно только свою локальную копию этой задачи.')
        if variant is None and not message:
            raise ProposalError('Напишите, что исправить, или приложите свою копию задачи.')
    elif kind == TaskProposal.KIND_NEW:
        if task.created_by_id != user.pk or task.is_shared or task.variant_of_id:
            raise ProposalError('В общую базу можно предложить только свою личную задачу.')
        variant = None
    else:
        raise ProposalError('Неизвестный вид предложения.')
    if open_proposal(user, task):
        raise ProposalError('Ваше предложение по этой задаче уже ждёт ответа редактора.')
    source = variant if variant is not None else (
        task if kind == TaskProposal.KIND_NEW else None)
    return TaskProposal.objects.create(
        task=task, kind=kind, author=user, message=message, variant=variant,
        snapshot=snapshot_of(source) if source is not None else {})


def _field_row(name, current, proposed):
    return {'name': name, 'label': FIELD_LABELS[name], 'current': current,
            'proposed': proposed, 'changed': current != proposed,
            'is_mask': name == 'answer_mask', 'is_bool': name == 'full_answer_only'}


def compare(proposal):
    """Сравнение «в базе ↔ предложено» для страницы редактора: разделы как
    чекбоксы «Применить», подпункты по порядку; ``changed`` — есть отличия,
    такие строки подсвечиваются и отмечены к применению по умолчанию."""
    current = snapshot_of(proposal.task)
    proposed = proposal.snapshot
    cur_subs, new_subs = current['subitems'], proposed.get('subitems', [])
    count_differs = len(cur_subs) != len(new_subs)
    subitem_rows = []
    for index in range(max(len(cur_subs), len(new_subs))):
        cur = cur_subs[index] if index < len(cur_subs) else None
        new = new_subs[index] if index < len(new_subs) else None
        fields = [_field_row(name, (cur or {}).get(name, ''), (new or {}).get(name, ''))
                  for name in FIELDS]
        subitem_rows.append({'index': index, 'current': cur, 'proposed': new,
                             'fields': fields,
                             'changed': cur is None or new is None
                             or any(f['changed'] for f in fields)})
    sections = []
    for key, label in SECTIONS:
        if key == 'subitems':
            changed = count_differs or any(
                row['fields'][0]['changed'] for row in subitem_rows
                if row['current'] and row['proposed'])
            sections.append({'key': key, 'label': label, 'changed': changed, 'fields': []})
            continue
        names = SECTION_FIELDS[key]
        fields = [_field_row(name, current.get(name, ''), proposed.get(name, ''))
                  for name in names]
        changed = any(f['changed'] for f in fields)
        if key != 'condition':
            changed = changed or (count_differs and bool(cur_subs or new_subs)) or any(
                f['changed'] for row in subitem_rows for f in row['fields']
                if f['name'] in names)
        sections.append({'key': key, 'label': label, 'changed': changed, 'fields': fields})
    return {'sections': sections, 'subitems': subitem_rows,
            'count_differs': count_differs,
            'any_changed': any(s['changed'] for s in sections)}


def _apply_block(block, owner, values):
    """Поля одного блока редактора на задачу или подпункт — через ту же
    ModelForm, что и карточка (маска проходит clean_mask_text)."""
    data = {field: values.get(field, '') for field in BLOCKS[block]}
    form = block_form(block, owner, data)
    if not form.is_valid():
        details = '; '.join(f'{field}: {", ".join(errors)}' for field, errors in form.errors.items())
        raise ProposalError(f'{SECTION_LABELS.get(block, block)}: {details}')
    form.save()


def _apply_subitems(task, rows):
    """Структура подпунктов из снимка через формсет редактора: лишние строки
    удаляются, недостающие создаются, порядок — по позиции в снимке."""
    existing = list(task.subitems.all())
    total = max(len(existing), len(rows))
    data = {'subitems-TOTAL_FORMS': str(total),
            'subitems-INITIAL_FORMS': str(len(existing)),
            'subitems-MIN_NUM_FORMS': '0', 'subitems-MAX_NUM_FORMS': '1000'}
    for index in range(total):
        prefix = f'subitems-{index}'
        if index < len(existing):
            data[f'{prefix}-id'] = str(existing[index].pk)
        if index < len(rows):
            data[f'{prefix}-order'] = str((index + 1) * 10)
            data[f'{prefix}-text_latex'] = rows[index].get('text_latex', '')
        else:
            data[f'{prefix}-order'] = str(existing[index].order)
            data[f'{prefix}-text_latex'] = existing[index].text_latex
            data[f'{prefix}-DELETE'] = 'on'
    formset = StructureFormSet(data, instance=task)
    if not formset.is_valid():
        errors = [str(e) for e in formset.non_form_errors()] + [
            f'строка {i + 1}: {"; ".join(", ".join(v) for v in e.values())}'
            for i, e in enumerate(formset.errors) if e]
        raise ProposalError('Подпункты: ' + '; '.join(errors))
    formset.save()


def _resolve(proposal, status, user, note):
    proposal.status = status
    proposal.resolved_at = timezone.now()
    proposal.resolved_by = user
    proposal.resolution_note = (note or '').strip()
    proposal.seen_by_author_at = None
    proposal.save(update_fields=['status', 'resolved_at', 'resolved_by',
                                 'resolution_note', 'seen_by_author_at'])


@transaction.atomic
def apply_proposal(proposal, sections, user, note=''):
    """Выбранные разделы снимка — в общую задачу; для ``new`` задача
    становится общей. Любая ошибка валидации откатывает всё."""
    proposal = TaskProposal.objects.select_for_update().get(pk=proposal.pk)
    if not proposal.is_open:
        raise ProposalError('Предложение уже обработано.')
    task = Task.objects.select_for_update().get(pk=proposal.task_id)
    chosen = [key for key, _ in SECTIONS if key in set(sections)]
    snapshot = proposal.snapshot
    if chosen and not snapshot:
        raise ProposalError('У предложения нет предложенной версии — применять нечего.')
    proposed_subs = snapshot.get('subitems', [])
    if 'subitems' in chosen:
        _apply_subitems(task, proposed_subs)
    subs = list(task.subitems.all())
    for key in chosen:
        if key == 'subitems':
            continue
        _apply_block(key, task, snapshot)
        if key == 'mask':
            _apply_block('answer_policy', task, snapshot)
        if key == 'condition' or not (subs or proposed_subs):
            continue
        if len(subs) != len(proposed_subs):
            raise ProposalError('Число подпунктов в базе и в предложении отличается — '
                                'отметьте «Подпункты», чтобы применить их вместе.')
        for sub, row in zip(subs, proposed_subs):
            _apply_block(key, sub, row)
    # Как после ручной правки: дата меняется, маски перепроверяются.
    updates = {'updated_at': timezone.now()}
    if proposal.kind == TaskProposal.KIND_NEW:
        updates['is_shared'] = True
    Task.objects.filter(pk=task.pk).update(**updates)
    _resolve(proposal, TaskProposal.STATUS_ACCEPTED, user, note)
    return proposal


@transaction.atomic
def reject_proposal(proposal, user, note):
    if not (note or '').strip():
        raise ProposalError('Укажите причину отклонения — автор увидит её в ответе.')
    proposal = TaskProposal.objects.select_for_update().get(pk=proposal.pk)
    if not proposal.is_open:
        raise ProposalError('Предложение уже обработано.')
    _resolve(proposal, TaskProposal.STATUS_REJECTED, user, note)
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
    task = get_object_or_404(visible_tasks(request.user).select_related('variant_of'), pk=pk)
    options = proposal_options(request.user, task)
    if options is None:
        raise PermissionDenied('Для этой задачи предложение не предусмотрено.')
    target = options['task']
    if request.method == 'POST':
        variant = None
        variant_id = request.POST.get('variant', '')
        if variant_id.isdigit():
            variant = get_object_or_404(own_variants(request.user, target), pk=int(variant_id))
        try:
            proposal = create_proposal(request.user, target, kind=options['kind'],
                                       message=request.POST.get('message', ''),
                                       variant=variant)
        except ProposalError as exc:
            level = messages.warning if 'уже ждёт' in str(exc) else messages.error
            level(request, str(exc))
            return _back(request, task)
        notify_new_proposal(proposal, url=request.build_absolute_uri(
            reverse('proposal_detail', args=[proposal.pk])))
        messages.success(request, 'Предложение отправлено редакторам базы.')
        return _back(request, task)
    return render(request, 'problems/propose.html', {
        'task': task, 'propose': options,
        'prefill': MASK_PREFILL if request.GET.get('mask') else '',
        'next': _safe_next(request, request.GET.get('next', '')),
    })


@teacher_required
def proposals_mine(request):
    """Свои предложения со статусом и ответом редактора. Непросмотренные
    ответы показываются все сразу отдельным блоком над списком (он у автора
    всегда короткий) и после показа считаются просмотренными; общий список —
    по дате отправки постранично, его порядок от отметки не зависит."""
    own = (TaskProposal.objects.filter(author=request.user)
           .select_related('task', 'variant', 'resolved_by'))
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
        TaskProposal.objects.select_related('task', 'author', 'variant', 'resolved_by'), pk=pk)


@base_editor_required
def proposal_detail(request, pk):
    proposal = _proposal(pk)
    diff = compare(proposal) if proposal.has_snapshot else None
    return render(request, 'problems/proposal_detail.html', {
        'proposal': proposal, 'task': proposal.task, 'diff': diff,
        'sections': [s for s in (diff['sections'] if diff else [])],
    })


@base_editor_required
@require_POST
def proposal_apply(request, pk):
    proposal = _proposal(pk)
    try:
        proposal = apply_proposal(proposal, request.POST.getlist('sections'),
                                  request.user, request.POST.get('note', ''))
    except ProposalError as exc:
        messages.error(request, str(exc))
        return redirect('proposal_detail', pk=pk)
    notify_resolved(proposal, url=request.build_absolute_uri(reverse('proposals_mine')))
    messages.success(request, 'Задача принята в общую базу.'
                     if proposal.kind == TaskProposal.KIND_NEW else 'Предложение применено.')
    return redirect('proposal_detail', pk=pk)


@base_editor_required
@require_POST
def proposal_reject(request, pk):
    proposal = _proposal(pk)
    try:
        proposal = reject_proposal(proposal, request.user, request.POST.get('note', ''))
    except ProposalError as exc:
        messages.error(request, str(exc))
        return redirect('proposal_detail', pk=pk)
    notify_resolved(proposal, url=request.build_absolute_uri(reverse('proposals_mine')))
    messages.success(request, 'Предложение отклонено.')
    return redirect('proposal_detail', pk=pk)

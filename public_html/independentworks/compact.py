"""Компактный вид конструктора: перенос кандидатов, объединение номеров, отмена.

Кандидат не пересоздаётся, а меняет номер (``position``): его маски,
подпункты и ``pk`` остаются прежними, поэтому отмена возвращает тот же
состав, а подтверждение «разное число подпунктов» снова совпадает с
``confirmed_composition``.
"""
import uuid
from collections import defaultdict

from django.db import transaction
from django.db.models import prefetch_related_objects
from django.shortcuts import get_object_or_404

from .models import Work, Position, Candidate, FamilyMember
from .pool import validate_selection
from .services import WorkError, digest

UNDO_KEY = 'iw_undo'
BLOCK_MESSAGE = 'Задачи блока переносятся только вместе.'
ANSWER_LIMIT = 90


def state(work):
    """Всё, что меняют перенос и объединение, — для отмены и её проверки."""
    return {
        'positions': [{'id': p.pk, 'order': p.order, 'text': p.text,
                       'mismatch_confirmed': p.mismatch_confirmed,
                       'confirmed_composition': p.confirmed_composition}
                      for p in Position.objects.filter(work=work).order_by('order', 'pk')],
        'candidates': [{'id': c.pk, 'position': c.position_id, 'task': c.task_id,
                        'parts': c.subitem_ids}
                       for c in Candidate.objects.filter(position__work=work).order_by('pk')],
    }


def _lock(work):
    return Work.objects.select_for_update().get(pk=work.pk)


def _renumber(positions):
    for order, position in enumerate(positions, 1):
        if position.order != order:
            position.order = order
            position.save(update_fields=['order'])


def _number(work, position_id):
    """Номер в нумерации страницы: пояснения без задач номер не занимают."""
    number = 0
    for position in work.positions.prefetch_related('candidates'):
        if position.candidates.all() or not position.text:
            number += 1
        if position.pk == position_id:
            return number
    return number


def _blocks(position):
    return {c.task.block_id for c in position.candidates.select_related('task') if c.task.block_id}


def _reject_block_target(rows):
    if any(c.task.block_id for c in rows):
        raise WorkError('Номер общего блока не принимает другие задачи.')


@transaction.atomic
def move_candidate(work, candidate_id, target_id=None, before_id=None):
    """Переносит кандидата в пул другого номера или отдельным номером.

    ``target_id`` — номер-цель; иначе создаётся новый номер перед
    ``before_id`` (пусто — в конец). Опустевший номер без пояснения
    удаляется. Возвращает (состояние до, сообщение) или None, если
    перенос ничего не меняет.
    """
    work = _lock(work)
    candidate = get_object_or_404(Candidate.objects.select_related('task', 'position'),
                                  pk=candidate_id, position__work=work)
    if candidate.task.block_id:
        raise WorkError(BLOCK_MESSAGE)
    source = candidate.position
    positions = list(work.positions.all())
    before = state(work)
    if target_id is not None:
        target = get_object_or_404(work.positions, pk=target_id)
        if target.pk == source.pk:
            return None
        rows = list(target.candidates.select_related('task'))
        if not rows and target.text:
            raise WorkError('Пояснение не принимает задачи. Отпустите задачу на номер или между номерами.')
        _reject_block_target(rows)
    else:
        index = len(positions)
        if before_id is not None:
            index = next((i for i, p in enumerate(positions) if p.pk == before_id), None)
            if index is None:
                raise WorkError('Состав изменился. Обновите страницу и повторите перетаскивание.', 409)
            # Номера общего блока идут подряд: вставка между ними разорвала бы блок.
            if index > 0 and _blocks(positions[index - 1]) & _blocks(positions[index]):
                raise WorkError('Между номерами общего блока нельзя вставить номер.')
        source_index = positions.index(source)
        alone = not source.text and source.candidates.count() == 1
        if alone and index in (source_index, source_index + 1):
            return None
        target = Position.objects.create(work=work, order=len(positions) + 1)
        positions.insert(index, target)
    validate_selection(target, candidate.task, candidate.subitem_ids, candidate)
    candidate.position = target
    candidate.save(update_fields=['position'])
    # Подтверждение объёма привязано к составу номера — после переноса
    # оно не действует ни в старом, ни в новом номере (как add_candidate).
    Position.objects.filter(pk__in=[source.pk, target.pk]).update(mismatch_confirmed=False)
    if not source.text and not source.candidates.exists():
        positions.remove(source)
        source.delete()
    _renumber(positions)
    work.save(update_fields=['updated_at'])
    number = _number(work, target.pk)
    message = f'Объединено в №{number}' if target_id is not None else f'Вынесено в отдельный №{number}'
    return before, message


@transaction.atomic
def merge_positions(work, ids):
    """Все кандидаты — в первый по порядку номер, остальные номера удаляются.

    Пояснения удаляемых номеров дописываются к пояснению первого через
    пустую строку, чтобы текст учителя не пропал.
    """
    work = _lock(work)
    ids = list(dict.fromkeys(ids))
    if len(ids) < 2:
        raise WorkError('Выберите хотя бы два номера.')
    chosen = list(work.positions.filter(pk__in=ids).prefetch_related('candidates__task'))
    if len(chosen) != len(ids):
        raise WorkError('Состав изменился. Обновите страницу.', 409)
    chosen.sort(key=lambda p: (p.order, p.pk))
    for position in chosen:
        rows = list(position.candidates.all())
        if not rows and position.text:
            raise WorkError('Пояснение нельзя объединить с номером.')
        if any(c.task.block_id for c in rows):
            raise WorkError('Номера общего блока не объединяются.')
    before = state(work)
    first, rest = chosen[0], chosen[1:]
    for position in rest:
        for candidate in position.candidates.all():
            validate_selection(first, candidate.task, candidate.subitem_ids, candidate)
            candidate.position = first
            candidate.save(update_fields=['position'])
    texts = [p.text.strip() for p in chosen if p.text.strip()]
    if any(p.text.strip() for p in rest):
        first.text = '\n\n'.join(texts)
    first.mismatch_confirmed = False
    first.save(update_fields=['text', 'mismatch_confirmed'])
    Position.objects.filter(pk__in=[p.pk for p in rest]).delete()
    _renumber(list(work.positions.all()))
    work.save(update_fields=['updated_at'])
    return before, f'Объединено в №{_number(work, first.pk)}'


def remember(request, work, before, message):
    """Одна отмена на сессию: только последнее действие."""
    request.session[UNDO_KEY] = {
        'token': uuid.uuid4().hex, 'work': work.pk, 'before': before,
        'after': digest(state(work)), 'message': message, 'fresh': True}


def pending_undo(request, work):
    """Тост «… · Отменить» показывается один раз — сразу после действия."""
    saved = request.session.get(UNDO_KEY)
    if not saved or saved.get('work') != work.pk or not saved.get('fresh'):
        return None
    saved['fresh'] = False
    request.session.modified = True
    return {'token': saved['token'], 'message': saved['message']}


@transaction.atomic
def undo(request, work, token):
    saved = request.session.get(UNDO_KEY)
    if not saved or saved.get('work') != work.pk or saved.get('token') != token:
        # Устаревший тост в другой вкладке не стирает действующую отмену.
        raise WorkError('Отменять нечего: действие уже отменено или было не последним.', 409)
    del request.session[UNDO_KEY]
    work = _lock(work)
    if digest(state(work)) != saved['after']:
        raise WorkError('Состав изменился после этого действия — отменить его уже нельзя.', 409)
    before = saved['before']
    existing = {p.pk: p for p in work.positions.all()}
    for row in before['positions']:
        position = existing.get(row['id'])
        create = position is None
        if create:
            if Position.objects.filter(pk=row['id']).exists():
                raise WorkError('Не удалось восстановить номер. Обновите страницу.', 409)
            # Прежний pk: на номер могут ссылаться открытые вкладки и якоря.
            position = Position(pk=row['id'], work=work)
        position.order = row['order']
        position.text = row['text']
        position.mismatch_confirmed = row['mismatch_confirmed']
        position.confirmed_composition = row['confirmed_composition']
        position.save(force_insert=create)
    candidates = {c.pk: c for c in Candidate.objects.filter(position__work=work)}
    for row in before['candidates']:
        candidate = candidates[row['id']]
        if candidate.position_id != row['position']:
            candidate.position_id = row['position']
            candidate.save(update_fields=['position'])
    # Номера, созданные действием, к этому моменту пусты.
    work.positions.exclude(pk__in=[row['id'] for row in before['positions']]).delete()
    work.save(update_fields=['updated_at'])


def _families(tasks):
    """Семьи аналогов, как во вкладке «Связанные аналоги» при подборе:
    семьи самой задачи и задачи, вариантом которой она является."""
    ids = {t.pk for t in tasks} | {t.variant_of_id for t in tasks if t.variant_of_id}
    titles, by_task = {}, defaultdict(set)
    for member in FamilyMember.objects.filter(task_id__in=ids).select_related('family'):
        titles[member.family_id] = member.family.title
        by_task[member.task_id].add(member.family_id)
    result = {t.pk: by_task[t.pk] | by_task.get(t.variant_of_id, set()) for t in tasks}
    return result, titles


def similar_hints(positions):
    """Соседние одиночные номера из одной семьи — кандидаты в объединение.

    Возвращает все пары; страница показывает первые три нескрытые.
    """
    numbered = [p for p in positions if p.rows or not p.text]
    singles = [p.rows[0].task for p in numbered if len(p.rows) == 1]
    families, titles = _families(singles)
    hints = []
    for first, second in zip(numbered, numbered[1:]):
        if len(first.rows) != 1 or len(second.rows) != 1:
            continue
        a, b = first.rows[0].task, second.rows[0].task
        if a.pk == b.pk or a.block_id or b.block_id:
            continue
        common = families[a.pk] & families[b.pk]
        if common:
            hints.append({'first': first, 'second': second, 'family': titles[min(common)]})
    return hints[:20]


def _short_answers(candidate):
    from worksheets.latex import subitem_label
    parts = candidate.selected
    owners = [(subitem_label(i) if parts else '', o) for i, o in enumerate(parts or [candidate.task])]
    rows, used, more = [], 0, False
    for label, owner in owners:
        text = owner.effective_answer_latex
        if not text:
            continue
        if used + len(text) > ANSWER_LIMIT:
            more = True
            break
        rows.append((label, text))
        used += len(text)
    return rows, more and bool(rows)


def decorate(positions):
    """Подписи плашек компактного вида: источник, ответ, признак блока."""
    previous = set()
    for position in positions:
        position.block_ids = {c.task.block_id for c in position.rows if c.task.block_id}
        position.closed = bool(position.block_ids)
        # Промежуток перед номером не выводится внутри общего блока.
        position.inside_block = bool(previous & position.block_ids)
        previous = position.block_ids
    candidates = [c for p in positions for c in p.rows]
    prefetch_related_objects([c.task for c in candidates], 'source_refs__source')
    for candidate in candidates:
        ref = next(iter(candidate.task.source_refs.all()), None)
        candidate.label = (f'{ref.source}, №{ref.number}' if ref and ref.number
                           else f'Задача #{candidate.task_id}')
        candidate.preview = candidate.task.text_latex or next(
            (p.text_latex for p in candidate.selected if p.text_latex), '')
        candidate.short_answers, candidate.answers_more = _short_answers(candidate)
        candidate.is_block = bool(candidate.task.block_id)

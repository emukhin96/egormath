"""Выдача, фиксация содержания, таймер и проверка самостоятельных."""
import hashlib
import itertools
import json
import math
import random
import re
import uuid
from datetime import timedelta
from pathlib import Path
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from assignments.checks import parse_mask, check_mask, collect_values, filled_text, reference_text
from livefile import files as livefiles
from problems.models import Task
from problems.task_images import taskpic_indices
from .models import Work, Position, Candidate, Run, Variant, Point, Asset, Attempt, Answer

FLAGS = {'checks', 'answer', 'solution', 'comment'}


class WorkError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def selected(candidate):
    parts = list(candidate.task.subitems.all())
    if candidate.subitem_ids:
        ids = set(candidate.subitem_ids)
        parts = [p for p in parts if p.pk in ids]
        if len(parts) != len(ids):
            raise WorkError('Выбранные подпункты изменились. Обновите кандидата.')
    return parts


def composition(position):
    """Подтверждение действует только для конкретного состава подпунктов."""
    return digest([(c.pk, c.task_id, [p.pk for p in selected(c)])
                   for c in position.candidates.select_related('task').order_by('pk')])


@transaction.atomic
def add_candidate(position, task, subitem_ids=None):
    """Блок добавляется целиком; новый аналог занимает те же позиции блока."""
    Work.objects.select_for_update().get(pk=position.work_id)
    ids = sorted(set(subitem_ids or []))
    if task.subitems.filter(pk__in=ids).count() != len(ids):
        raise WorkError('Подпункт не принадлежит выбранной задаче.')
    if not task.block_id:
        Candidate.objects.get_or_create(position=position, task=task, subitem_ids=ids)
        Position.objects.filter(pk=position.pk).update(mismatch_confirmed=False)
    else:
        from problems.task_blocks import block_members
        try:
            members = block_members(task)
        except ValueError as error:
            raise WorkError(str(error))
        positions = list(position.work.positions.all())
        index = next(i for i, p in enumerate(positions) if p.pk == position.pk)
        current = position.candidates.select_related('task').first()
        if current:
            if not current.task.block_id:
                raise WorkError('Для общего блока добавьте отдельный пустой номер.')
            index -= current.task.block_position - 1
            targets = positions[index:index + len(members)]
            if len(targets) != len(members) or any(not p.candidates.filter(task__block_id=current.task.block_id, task__block_position=i).exists() for i, p in enumerate(targets, 1)):
                raise WorkError('Восстановите порядок номеров общего блока.')
        else:
            targets = [position] + [Position.objects.create(work=position.work, order=position.order) for _ in members[1:]]
            positions[index:index + 1] = targets
            for order, item in enumerate(positions, 1):
                item.order = order
                item.save(update_fields=['order'])
        for target, member in zip(targets, members):
            Candidate.objects.get_or_create(position=target, task=member, subitem_ids=ids if member.pk == task.pk else [])
            Position.objects.filter(pk=target.pk).update(mismatch_confirmed=False)
    position.work.save(update_fields=['updated_at'])


def candidate_data(candidate, number):
    task = candidate.task
    parts = selected(candidate)
    images = list(task.images.all())
    all_parts = list(task.subitems.all())
    answer_refs = taskpic_indices(task.effective_answer_latex)
    solution_refs = taskpic_indices(task.effective_solution_latex)
    statement_refs = taskpic_indices(task.text_latex)
    for part in all_parts:
        statement_refs |= taskpic_indices(part.text_latex)
        answer_refs |= taskpic_indices(part.effective_answer_latex)
        solution_refs |= taskpic_indices(part.effective_solution_latex)
    known = statement_refs | answer_refs | solution_refs
    rows = []
    from worksheets.latex import subitem_label
    for index, owner in enumerate(parts or [task]):
        spec = parse_mask(owner.answer_mask)
        reference = owner.effective_answer_latex or (reference_text(spec) if spec.is_valid else '')
        common = task.text_latex if parts else ''
        text = owner.text_latex
        # У каждого вопроса блока сохраняем необходимое общее условие.
        if task.block_id:
            from types import SimpleNamespace
            from worksheets.block_presentation import block_presentations
            members = list(task.block.tasks.order_by('block_position', 'pk'))
            presentations = block_presentations([SimpleNamespace(pk=m.pk, task=m, task_id=m.pk) for m in members])
            presentation = presentations.get(task.pk)
            if presentation:
                common = '\n'.join(filter(None, [next((p.common for p in presentations.values() if p.common), ''), common]))
                if not parts:
                    text = presentation.text
        sources = []
        point_statement = taskpic_indices(common + text)
        point_answer = taskpic_indices(owner.effective_answer_latex)
        point_solution = taskpic_indices(owner.effective_solution_latex)
        for i, img in enumerate(images):
            audiences = []
            if i in point_statement or i not in known:
                audiences.append('statement')
            if i in point_answer:
                audiences.append('answer')
            if i in point_solution:
                audiences.append('solution')
            if audiences:
                try:
                    with img.image.open('rb') as stream:
                        checksum = hashlib.sha256(stream.read()).hexdigest()
                except OSError as error:
                    raise WorkError('Вложение недоступно. Восстановите файл и обновите предпросмотр.', 409) from error
                sources.append({'path': img.image.name, 'name': img.filename, 'audiences': audiences, 'sha256': checksum})
        key = f't{task.pk}:s{owner.pk}' if parts else f't{task.pk}'
        rows.append({'position': number, 'part': index if parts else 0,
                     'label': f'{number}' + (subitem_label(index) if parts else ''),
                     'source_key': key, 'root_key': key,
                     'candidate_key': f't{task.pk}:' + ','.join(str(p.pk) for p in parts),
                     'snapshot': {'common': common, 'text': text,
                                  'answer': reference,
                                  'solution': owner.effective_solution_latex,
                                  'mask': '' if task.full_answer_only else owner.answer_mask,
                                  'assets': sources}})
    return rows


def material(work):
    """Содержание предпросмотра; хеш включает файлы и выбранные подпункты."""
    positions = []
    notes = []
    number = 0
    for position in work.positions.prefetch_related('candidates__task__subitems', 'candidates__task__images', 'candidates__task__block__tasks'):
        candidates = list(position.candidates.all())
        if not candidates:
            if position.text:
                notes.append({'before': number + 1, 'text': position.text})
                continue
            raise WorkError('В одном из номеров нет кандидатов.')
        number += 1
        if position.text:
            notes.append({'before': number, 'text': position.text})
        counts = {len(selected(c)) or 1 for c in candidates}
        if len(counts) > 1 and (not position.mismatch_confirmed or position.confirmed_composition != composition(position)):
            raise WorkError(f'Подтвердите разное число подпунктов в №{number}.')
        positions.append([{'id': c.pk, 'block': c.task.block_id,
                           'block_position': c.task.block_position,
                           'block_size': c.task.block.size if c.task.block_id else 0,
                           'points': candidate_data(c, number)} for c in candidates])
    if not positions:
        raise WorkError('Добавьте хотя бы один номер.')
    return {'title': work.title, 'positions': positions, 'notes': notes}


def valid_combination(combo):
    keys = [p['source_key'] for c in combo for p in c['points']]
    if len(keys) != len(set(keys)):
        return False
    blocks = {}
    for c in combo:
        if c['block']:
            blocks.setdefault((c['block'], c['block_size']), []).append(c['block_position'])
    return all(sorted(positions) == list(range(1, size + 1)) for (_, size), positions in blocks.items())


def generate(data, count, seed, seen=None):
    rng = random.Random(seed)
    pools = data['positions']
    space = math.prod(len(p) for p in pools)
    exhaustive = space <= 20000
    iterator = itertools.product(*pools) if exhaustive else (tuple(rng.choice(p) for p in pools) for _ in range(10000))
    choices = {}
    for combo in iterator:
        if not valid_combination(combo):
            continue
        signature = tuple(tuple(p['source_key'] for p in c['points']) for c in combo)
        choices.setdefault(signature, combo)
    if not choices:
        raise WorkError('Нет допустимых комбинаций: проверьте повтор подпунктов и полноту блоков.' if exhaustive else 'Поиск не завершён: сузьте пулы или повторите подбор.')
    remaining = list(choices.items())
    rng.shuffle(remaining)
    picked = []
    used = {}
    seen = set(seen or [])
    # Предпочитаем новые для ученика пункты, затем различие вариантов и баланс.
    while remaining and len(picked) < count:
        def score(entry):
            sig, combo = entry
            fresh = -sum(p['source_key'] in seen for c in combo for p in c['points'])
            distance = min((sum(a != b for a, b in zip(sig, old[0])) for old in picked), default=0)
            balance = -sum(used.get(c['id'], 0) for c in combo)
            return fresh, distance, balance
        best = max(remaining, key=score)
        picked.append(best)
        remaining.remove(best)
        for c in best[1]:
            used[c['id']] = used.get(c['id'], 0) + 1
    if len(picked) < count and not exhaustive:
        raise WorkError('Ограничение поиска достигнуто. Это не доказывает нехватку вариантов: уменьшите их число или повторите подбор.')
    variants = [[p for c in combo for p in c['points']] for _, combo in picked]
    repeats = sorted({p['source_key'] for rows in variants for p in rows if p['source_key'] in seen})
    return variants, len(variants) < count, repeats


def prior_keys(attempt):
    top = attempt
    while top.parent_id:
        top = top.parent
    ids = {top.pk}
    frontier = {top.pk}
    while frontier:
        frontier = set(Attempt.objects.filter(parent_id__in=frontier).values_list('pk', flat=True))
        ids |= frontier
    return list(Point.objects.filter(variant__attempts__pk__in=ids, variant__attempts__student=attempt.student).values_list('source_key', flat=True))


def correction_fingerprint(parent):
    return digest({'points': list(parent.variant.points.values('id', 'snapshot')),
                   'answers': list(parent.answers.order_by('point_id').values('point_id', 'grade', 'auto_check', 'updated_at'))})


def prepare(work, owner, students, duration=40, deadline=None, max_variants=None,
            allow_photos=True, self_check=False, release_mode='manual', release_flags=None,
            parent=None, kind='initial', previous=None, restrict_clipboard=False):
    if kind not in ('initial', 'correction', 'retake') or (kind == 'initial') != (parent is None):
        raise WorkError('Исходная попытка нужна только для исправления или пересдачи.')
    if parent is not None and parent.run.work_id != work.pk:
        raise WorkError('Исходная попытка относится к другой самостоятельной.')
    if duration < 1 or duration > 1440 or (max_variants is not None and max_variants < 1):
        raise WorkError('Длительность — от 1 до 1440 минут; число вариантов — положительное.')
    if deadline and deadline <= timezone.now():
        raise WorkError('Общее окончание должно быть в будущем.')
    flags = sorted(set(release_flags or []) & FLAGS)
    if release_mode not in ('auto', 'manual'):
        raise WorkError('Неизвестный режим публикации.')
    recipients = sorted(set(students))
    if not recipients:
        raise WorkError('Выберите учеников.')
    seed = uuid.uuid4().hex
    data = material(work) if kind != 'correction' else None
    repeats = []
    shortage = False
    if parent:
        if not parent.finished or result(parent)['pending']:
            raise WorkError('Сначала завершите проверку исходной попытки.')
        recipients = [parent.student_id]
    if kind == 'correction':
        old = {a.point_id: a for a in parent.answers.all()}
        points = []
        for point in parent.variant.points.all():
            if old.get(point.pk) and old[point.pk].credit >= 1:
                continue
            snapshot = dict(point.snapshot)
            snapshot['assets'] = [{'asset_id': a.pk, 'name': a.name, 'audiences': a.audiences} for a in point.assets.all()]
            points.append({k: getattr(point, k) for k in ('position', 'part', 'label', 'source_key', 'candidate_key', 'root_key')} | {'snapshot': snapshot})
        if not points:
            raise WorkError('Ошибочных пунктов нет.')
        variants = [points]
        notes = parent.variant.notes
    else:
        variants, shortage, repeats = generate(data, min(len(recipients), max_variants or len(recipients)), seed, prior_keys(parent) if parent else None)
        notes = data['notes']
    shuffled = list(recipients)
    random.Random(seed).shuffle(shuffled)
    assignment = {str(student): i % len(variants) + 1 for i, student in enumerate(shuffled)}
    plan = {'variants': variants, 'students': assignment, 'notes': notes, 'shortage': shortage,
            'repeats': repeats, 'seed': seed}
    with transaction.atomic():
        if previous is not None:
            previous = Run.objects.select_for_update().get(pk=previous.pk)
            if (previous.work_id != work.pk or previous.owner_id != owner.pk
                    or previous.parent_id != (parent.pk if parent else None) or previous.kind != kind):
                raise WorkError('Предпросмотр относится к другой выдаче.', 409)
            if previous.issued_at or previous.superseded_at:
                raise WorkError('Предпросмотр уже выдан или заменён. Откройте актуальную выдачу.', 409)
            previous.superseded_at = timezone.now()
            previous.save(update_fields=['superseded_at'])
        return Run.objects.create(work=work, owner=owner, title=work.title, duration=duration,
                                  deadline=deadline, max_variants=max_variants, allow_photos=allow_photos,
                                  self_check=self_check, restrict_clipboard=restrict_clipboard,
                                  release_mode=release_mode, release_flags=flags,
                                  fingerprint=correction_fingerprint(parent) if kind == 'correction' else digest(data),
                                  plan=plan, kind=kind, parent=parent)


def issue(run_id, confirm=False):
    """При откате БД удаляем только файлы этой неудачной выдачи."""
    written = []
    try:
        with transaction.atomic():
            return _issue(run_id, confirm, written)
    except Exception:
        for storage, name in written:
            try:
                storage.delete(name)
            except OSError:
                import logging
                logging.getLogger(__name__).exception('Не удалось убрать файл отменённой выдачи')
        raise


def _issue(run_id, confirm, written):
    run = Run.objects.select_for_update().select_related('work', 'parent').get(pk=run_id)
    if run.issued_at:
        return run
    if run.superseded_at:
        raise WorkError('Предпросмотр заменён новым. Выдайте актуальный просмотренный вариант.', 409)
    if run.deadline and run.deadline <= timezone.now():
        raise WorkError('Срок уже прошёл. Подготовьте новое проведение.')
    current = correction_fingerprint(run.parent) if run.kind == 'correction' else digest(material(run.work))
    if current != run.fingerprint:
        raise WorkError('Задачи или шаблон изменились. Обновите предпросмотр.', 409)
    if (run.plan['shortage'] or run.plan['repeats']) and not confirm:
        raise WorkError('Подтвердите предупреждение о повторениях.')
    for number, points in enumerate(run.plan['variants'], 1):
        variant = Variant.objects.create(run=run, number=number, signature=digest(points), notes=run.plan['notes'])
        for row in points:
            values = dict(row)
            snapshot = dict(values.pop('snapshot'))
            sources = snapshot.pop('assets', [])
            point = Point.objects.create(variant=variant, snapshot=snapshot, **values)
            for source in sources:
                try:
                    if 'asset_id' in source:
                        original = Asset.objects.get(pk=source['asset_id']).file
                    else:
                        from django.core.files.storage import default_storage
                        original = default_storage.open(source['path'], 'rb')
                    with (original.open('rb') if hasattr(original, 'storage') else original) as stream:
                        content = stream.read()
                except (Asset.DoesNotExist, OSError) as error:
                    raise WorkError('Вложение изменилось или недоступно. Обновите предпросмотр.', 409) from error
                if source.get('sha256') and hashlib.sha256(content).hexdigest() != source['sha256']:
                    raise WorkError('Картинка изменилась. Обновите предпросмотр.', 409)
                asset = Asset(point=point, name=source['name'], audiences=source['audiences'])
                asset.file.save(uuid.uuid4().hex + Path(source['name']).suffix, ContentFile(content), save=False)
                written.append((asset.file.storage, asset.file.name))
                asset.save()
        for student, assigned in run.plan['students'].items():
            if assigned == number:
                root = (run.parent.root or run.parent) if run.parent and run.kind == 'correction' else None
                Attempt.objects.create(run=run, variant=variant, student_id=int(student), parent=run.parent, root=root)
    run.issued_at = timezone.now()
    run.save(update_fields=['issued_at'])
    return run


def touch_attempt(attempt):
    """Файл-версия прогресса проведения — для записей через update(), без сигналов."""
    livefiles.touch('run', attempt.run_id)
    if attempt.root_id:
        root_run = Attempt.objects.filter(pk=attempt.root_id).values_list('run_id', flat=True).first()
        if root_run and root_run != attempt.run_id:
            livefiles.touch('run', root_run)


def finish_expired(attempt, now=None):
    now = now or timezone.now()
    if attempt.ends_at and now >= attempt.ends_at and not attempt.submitted_at:
        Attempt.objects.filter(pk=attempt.pk, submitted_at__isnull=True).update(submitted_at=attempt.ends_at)
        attempt.submitted_at = attempt.ends_at
        touch_attempt(attempt)
    return attempt


@transaction.atomic
def set_deadline(run_id, deadline):
    """Меняет общее окончание проведения и пересчитывает срок начатых попыток.

    Личный срок начатой попытки — старт + длительность, но не позже общего
    окончания; при продлении ученик получает время, при сокращении работа
    завершается по новому сроку. Сданные попытки не трогаются.
    """
    run = Run.objects.select_for_update().get(pk=run_id)
    run.deadline = deadline
    run.save(update_fields=['deadline'])
    for attempt in run.attempts.select_for_update().filter(
            started_at__isnull=False, submitted_at__isnull=True):
        ends = attempt.started_at + timedelta(minutes=run.duration)
        if deadline:
            ends = min(ends, deadline)
        Attempt.objects.filter(pk=attempt.pk).update(ends_at=ends)
    livefiles.touch('run', run.pk)
    return run


@transaction.atomic
def start(attempt_id):
    attempt = Attempt.objects.select_for_update().select_related('run').get(pk=attempt_id)
    if attempt.started_at:
        return finish_expired(attempt)
    now = timezone.now()
    if attempt.run.closed_at or (attempt.run.deadline and now >= attempt.run.deadline):
        raise WorkError('Время начала работы закончилось.', 409)
    ends = now + timedelta(minutes=attempt.run.duration)
    if attempt.run.deadline:
        ends = min(ends, attempt.run.deadline)
    # Условная запись защищает начало также на SQLite, где нет row lock.
    Attempt.objects.filter(pk=attempt.pk, started_at__isnull=True).update(started_at=now, ends_at=ends)
    attempt.refresh_from_db()
    touch_attempt(attempt)
    return attempt


def editable(attempt):
    if not attempt.started_at or attempt.finished:
        raise WorkError('Работа не начата или время закончилось.', 409)


@transaction.atomic
def save_answer(attempt_id, point_id, version, values):
    from workaudit.services import lock_work
    attempt = lock_work(Attempt, attempt_id)
    editable(attempt)
    point = Point.objects.get(pk=point_id, variant_id=attempt.variant_id)
    answer, _ = Answer.objects.get_or_create(attempt=attempt, point=point)
    if answer.version != version:
        raise WorkError('Ответ изменён в другой вкладке. Перезагрузите страницу, сохранив свой текст.', 409)
    spec = parse_mask(point.snapshot['mask'])
    allowed = {s.name for s in spec.slots} if spec.is_valid else set()
    if set(values) - allowed or any(not isinstance(v, str) or len(v) > 10000 for v in values.values()):
        raise WorkError('Некорректный ответ.')
    from workaudit.services import answer_snapshot, record_revision
    snapshot_before = answer_snapshot(answer)
    from assignments.checks.formulas import (UNAVAILABLE_KEY, FormulaUnavailable,
                                             unavailable_count)
    try:
        auto, checks = check_mask(spec, values) if spec.is_valid else ('unknown', {})
    except FormulaUnavailable as error:
        # Вычислитель временно недоступен: ответ сохраняем без вердикта,
        # сверка повторится при открытии учеником своей работы.
        auto, checks = '', {UNAVAILABLE_KEY: unavailable_count({}, error)}
    else:
        # Пустые поля пригодной маски дают нулевой зачёт, а не ручную очередь.
        if spec.is_valid and (not auto or (auto == 'unknown' and 'unknown' not in checks.values())):
            auto = 'wrong'
    editable(attempt)
    changed = Answer.objects.filter(pk=answer.pk, version=version).update(
        values=values, auto_check=auto, checks=checks, check_revealed=False,
        version=version + 1, updated_at=timezone.now())
    if not changed:
        raise WorkError('Конфликт сохранения. Перезагрузите страницу.', 409)
    answer.refresh_from_db()
    record_revision(answer, snapshot_before)
    touch_attempt(attempt)
    return answer


def recheck_unavailable(attempt):
    """Досверить один ответ при открытии учеником своей работы.

    Повторов не больше UNAVAILABLE_LIMIT на один ввод: после этого ответ
    уходит в ручную проверку как unknown. Занятый вычислитель не ждём;
    сводка учителя и экспорт эту функцию не вызывают.
    """
    from assignments.checks.formulas import (UNAVAILABLE_KEY, UNAVAILABLE_LIMIT,
                                             FormulaUnavailable, unavailable_count,
                                             without_worker_wait)
    for answer in attempt.answers.filter(auto_check='').select_related('point'):
        if not any((v or '').strip() for v in (answer.values or {}).values()):
            continue
        spec = parse_mask(answer.point.snapshot['mask'])
        if not spec.is_valid:
            continue
        try:
            with without_worker_wait():
                auto, checks = check_mask(spec, answer.values)
        except FormulaUnavailable as error:
            count = unavailable_count(answer.checks, error)
            fields = {'checks': {UNAVAILABLE_KEY: count}}
            if count >= UNAVAILABLE_LIMIT:
                fields['auto_check'] = 'unknown'
            Answer.objects.filter(pk=answer.pk, version=answer.version).update(**fields)
        else:
            if not auto or (auto == 'unknown' and 'unknown' not in checks.values()):
                auto = 'wrong'
            Answer.objects.filter(pk=answer.pk, version=answer.version).update(
                auto_check=auto, checks=checks)
        # own_attempt предзагружает ответы: этот же показ и итог должны
        # использовать свежий результат, а не старый экземпляр модели.
        getattr(attempt, '_prefetched_objects_cache', {}).pop('answers', None)
        break


@transaction.atomic
def submit(attempt_id):
    from workaudit.services import lock_work
    attempt = lock_work(Attempt, attempt_id)
    finish_expired(attempt)
    if attempt.submitted_at:
        return attempt
    editable(attempt)
    attempt.submitted_at = timezone.now()
    attempt.save(update_fields=['submitted_at'])
    return attempt


def result(attempt):
    points = list(attempt.variant.points.all())
    answers = {a.point_id: a for a in attempt.answers.all()}
    done = 0
    pending = 0
    for p in points:
        answer = answers.get(p.pk)
        if answer:
            done += answer.credit
            pending += int(answer.pending)
        else:
            pending += int(not parse_mask(p.snapshot['mask']).is_valid)
    if not attempt.started_at:
        return {'done': None, 'total': len(points), 'percent': None, 'pending': pending}
    return {'done': done, 'total': len(points), 'percent': round(100 * done / len(points)) if points else 0, 'pending': pending}


def cumulative(attempt, student_view=False):
    root = attempt.root or attempt
    corrections = root.corrections.all()
    if 'corrections' not in getattr(root, '_prefetched_objects_cache', {}):
        corrections = corrections.select_related('variant', 'run').prefetch_related('answers__point')
    attempts = [root] + list(corrections)
    best = {p.root_key: 0 for p in root.variant.points.all()}
    for item in attempts:
        if student_view and (not item.finished or 'checks' not in item.disclosure):
            continue
        for answer in item.answers.all():
            key = answer.point.root_key
            if key in best:
                best[key] = max(best[key], answer.credit)
    done = sum(best.values())
    return {'done': done, 'total': len(best), 'percent': round(100 * done / len(best)) if best else 0}


def answer_display(point, answer):
    spec = parse_mask(point.snapshot['mask'])
    return filled_text(spec, answer.values) if answer and spec.is_valid else ''


@transaction.atomic
def update_recipients(run_id, students, choices):
    """Меняем только не начатые назначения, сохраняя выданные снимки."""
    run = Run.objects.select_for_update().get(pk=run_id)
    if not run.issued_at:
        raise WorkError('Проведение ещё не выдано.')
    attempts = {a.student_id: a for a in run.attempts.select_for_update().order_by('pk')}
    if not students:
        raise WorkError('Оставьте хотя бы одного получателя.')
    if run.kind != 'initial' and students != set(attempts):
        raise WorkError('Получатель повторной попытки закреплён.', 409)
    from accounts.models import Profile
    allowed = set(Profile.student_users_for(run.owner).values_list('pk', flat=True)) | set(attempts)
    if not students <= allowed:
        raise WorkError('Ученик недоступен владельцу проведения.', 403)
    variants = {v.pk: v for v in run.variants.all()}
    if any(v not in variants for v in choices.values()):
        raise WorkError('Вариант не принадлежит этому проведению.')
    for student, attempt in attempts.items():
        if (attempt.started_at or run.kind != 'initial') and (student not in students or choices[student] != attempt.variant_id):
            raise WorkError('Начавшего ученика или закреплённую попытку менять нельзя.', 409)
    if students - set(attempts) and (run.closed_at or run.deadline and run.deadline <= timezone.now()):
        raise WorkError('Срок начала прошёл: добавить получателей нельзя.', 409)
    for student in set(attempts) - students:
        attempts[student].delete()
    for student in students:
        if student in attempts:
            Attempt.objects.filter(pk=attempts[student].pk).update(variant_id=choices[student])
            touch_attempt(attempts[student])
        else:
            Attempt.objects.create(run=run, student_id=student, variant_id=choices[student])
    run.plan = {**run.plan, 'students': {str(student): variants[choices[student]].number for student in sorted(students)}}
    run.save(update_fields=['plan'])

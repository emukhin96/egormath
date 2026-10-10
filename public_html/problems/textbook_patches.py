"""Точечные правки уже залитой партии черновиков без повторной заливки.

Сверку большой книги делают на локальной копии партии. Чтобы не повторять
работу на сервере, разница между исходным состоянием (выгрузка
``export_textbook_batches`` до правок) и текущим переносится пакетом
правок. Для каждой изменённой строки пакет хранит её исходное состояние
целиком (все переносимые поля и статус) и новые значения изменённых полей.

На сервере строка меняется, только если её состояние совпадает с исходным:
поздние правки учителя не перезаписываются, такие строки попадают в отчёт.
Поле, уже равное новому значению (повторный запуск, тот же подбор маски на
сервере), считается применённым. Одобренная строка после правки
возвращается на проверку: одобрял человек другой текст.
"""
from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path

from django.db import transaction

from .models import TextbookImportBatch, TextbookTaskDraft, Topic
from .textbook_import import (TextbookImportUnavailable, normalize_answer_mask,
                              refresh_image_warnings, unmatched_image_names)
from .textbook_transfer import serialize_batch

PATCH_KIND = 'textbook-draft-patch'
PATCH_VERSION = 2
# Содержание черновика, маски и темы. Статус и отметки сверки не переносятся:
# одобряет человек на сервере.
TEXT_FIELDS = ('text_latex', 'author_answer_latex', 'author_solution_latex',
               'answer_latex', 'solution_latex', 'answer_mask')
LIST_FIELDS = ('subitems', 'warnings', 'images')
TOPIC_FIELDS = ('topic_code', 'topic_codes')
PATCH_FIELDS = TEXT_FIELDS + LIST_FIELDS + TOPIC_FIELDS
# Поля, правка которых пакетом не переносится: о них предупреждаем.
UNTRANSFERRED_FIELDS = ('source_number', 'source_path', 'collection_key',
                        'collection_title', 'topic_original',
                        'exam_item_codes', 'grade_band_codes', 'tags')


class TextbookPatchError(ValueError):
    pass


def read_batch_export(path):
    """Первая партия выгрузки (ZIP или batches.json): заголовок и черновики."""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            payload = json.loads(archive.read('batches.json'))
    else:
        payload = json.loads(path.read_text(encoding='utf-8'))
    batches = payload.get('batches') or []
    if len(batches) != 1:
        raise TextbookPatchError('В выгрузке должна быть ровно одна партия.')
    return batches[0]


def _ids_digest(external_ids):
    return hashlib.sha256('\n'.join(sorted(external_ids)).encode()).hexdigest()


def _snapshot(row):
    return {name: row.get(name) for name in PATCH_FIELDS + ('status',)}


def build_draft_patch(baseline, current):
    """Пакет правок: строки, где текущее состояние отличается от исходного.

    ``baseline`` и ``current`` — партии в виде ``serialize_batch``.
    Возвращает пакет и список непереносимых различий для предупреждения.
    """
    before_rows = {row['external_id']: row for row in baseline['drafts']}
    after_rows = {row['external_id']: row for row in current['drafts']}
    if set(before_rows) != set(after_rows):
        differ = sorted(set(before_rows) ^ set(after_rows))[:10]
        raise TextbookPatchError(
            'Набор задач не совпадает с исходной выгрузкой (переименование '
            f'ключа пакетом не переносится): {differ}')
    drafts = []
    untransferred = []
    for external_id, row in after_rows.items():
        before_row = before_rows[external_id]
        fields = {name: row.get(name) for name in PATCH_FIELDS
                  if before_row.get(name) != row.get(name)}
        if fields:
            drafts.append({'external_id': external_id,
                           'before': _snapshot(before_row),
                           'after': fields})
        untransferred.extend(
            (external_id, name) for name in UNTRANSFERRED_FIELDS
            if before_row.get(name) != row.get(name))
    patch = {
        'kind': PATCH_KIND,
        'version': PATCH_VERSION,
        'batch': {
            'title': baseline['title'],
            'profile': baseline['profile'],
            'drafts': len(before_rows),
            'ids_sha256': _ids_digest(before_rows),
        },
        'drafts': drafts,
        # Порядок книги целиком: партия, перенесённая старой выгрузкой,
        # на сервере стоит в порядке строк ключей (I.1, I.10, I.2).
        'order': [row['external_id'] for row in current['drafts']],
    }
    return patch, untransferred


def batch_rows(batch):
    return serialize_batch(batch)


def _topic_ids(codes):
    found = dict(Topic.objects.filter(code__in=[c for c in codes if c])
                 .values_list('code', 'pk'))
    missing = sorted({c for c in codes if c and c not in found})
    if missing:
        raise TextbookPatchError(f'На сервере нет тем с кодами: {missing}')
    return found


def _current_value(draft, name, codes_by_pk):
    if name == 'topic_code':
        return codes_by_pk.get(draft.topic_id, '') if draft.topic_id else ''
    if name == 'topic_codes':
        return [codes_by_pk.get(pk, '') for pk in draft.topic_ids]
    return getattr(draft, name)


MASK_CHECK_ATTEMPTS = 5


def _check_mask(value, key='answer_mask'):
    """Разбор маски с повтором: в большом пакете тысячи масок, и один
    занятый вычислитель формул не должен отменять весь пакет."""
    for attempt in range(1, MASK_CHECK_ATTEMPTS + 1):
        try:
            return normalize_answer_mask(value, key=key)
        except TextbookImportUnavailable:
            if attempt == MASK_CHECK_ATTEMPTS:
                raise
            time.sleep(2 ** (attempt - 1))


def _check_value(name, value):
    """Проверяет тип и маски, значение записывается как есть.

    Нормализацию заливки (``normalize_subitems``) не применяем: пакет несёт
    уже сверенный текст, повторная обработка могла бы его изменить.
    """
    if name in TEXT_FIELDS or name == 'topic_code':
        if not isinstance(value, str):
            raise TextbookPatchError(f'Поле {name} должно быть строкой.')
        if name == 'answer_mask':
            _check_mask(value)
        return value
    if not isinstance(value, list):
        raise TextbookPatchError(f'Поле {name} должно быть списком.')
    if name == 'subitems':
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict) or not all(
                    isinstance(v, str) for v in item.values()):
                raise TextbookPatchError(f'Подпункт {index}: ожидались строки.')
            _check_mask(item.get('answer_mask'), key=f'subitems[{index}].answer_mask')
    elif not all(isinstance(v, str) for v in value):
        raise TextbookPatchError(f'Поле {name}: ожидался список строк.')
    return value


def _check_patch_values(patch):
    """Форма пакета и разбор масок — без базы, до блокировки партии.

    Разбор масок с формулами медленный (вычислитель), поэтому он идёт вне
    транзакции: строки партии блокируются только на время записи.
    """
    if not isinstance(patch, dict) or patch.get('kind') != PATCH_KIND:
        raise TextbookPatchError('Это не пакет правок черновиков.')
    if patch.get('version') != PATCH_VERSION:
        raise TextbookPatchError(
            f'Пакет версии {patch.get("version")}, ожидалась {PATCH_VERSION}.')
    for row in patch.get('drafts') or []:
        if not isinstance(row, dict) or not isinstance(row.get('external_id'), str):
            raise TextbookPatchError('Строка пакета без external_id.')
        before, after = row.get('before'), row.get('after')
        if not isinstance(before, dict) or not isinstance(after, dict) or not after:
            raise TextbookPatchError(f'{row["external_id"]}: нет before/after.')
        unknown = (set(after) - set(PATCH_FIELDS)) | (
            set(before) - set(PATCH_FIELDS) - {'status'})
        if unknown:
            raise TextbookPatchError(
                f'{row["external_id"]}: неизвестные поля {sorted(unknown)}.')
        for name, value in after.items():
            _check_value(name, value)


def _validate_batch(batch, patch, allow_other_title):
    info = patch.get('batch') or {}
    if info.get('profile') != batch.profile:
        raise TextbookPatchError(
            f'Пакет для профиля {info.get("profile")!r}, партия — {batch.profile!r}.')
    if info.get('title') != batch.title and not allow_other_title:
        raise TextbookPatchError(
            f'Пакет для партии «{info.get("title")}», выбрана «{batch.title}». '
            'Если это та же книга под другим названием, повторите с --allow-other-title.')
    ids = list(batch.drafts.values_list('external_id', flat=True))
    if _ids_digest(ids) != info.get('ids_sha256') or len(ids) != info.get('drafts'):
        raise TextbookPatchError(
            'Набор задач партии не совпадает с исходной выгрузкой пакета.')
    order = patch.get('order')
    if order is not None and (not isinstance(order, list) or sorted(order) != sorted(ids)):
        raise TextbookPatchError('Порядок задач в пакете не совпадает с набором партии.')


def apply_draft_patch(batch, patch, *, apply=False, allow_other_title=False):
    """Применяет пакет; без ``apply`` только проверяет (откат транзакции).

    Отчёт: ``applied`` — изменённые строки, ``already`` — строки, где все
    правки уже стоят, ``reset`` — одобренные строки, возвращённые на
    проверку, ``skipped`` — строки с причиной (изменены после выгрузки,
    загружены в каталог), ``images`` — строки с несопоставленными рисунками.
    """
    _check_patch_values(patch)
    return _apply_checked_patch(batch, patch, apply=apply,
                                allow_other_title=allow_other_title)


@transaction.atomic
def _apply_checked_patch(batch, patch, *, apply, allow_other_title):
    batch = TextbookImportBatch.objects.select_for_update().get(pk=batch.pk)
    _validate_batch(batch, patch, allow_other_title)
    codes = set()
    for row in patch['drafts']:
        codes.add(row['after'].get('topic_code') or '')
        codes.update(row['after'].get('topic_codes') or [])
    topic_ids = _topic_ids(codes)
    codes_by_pk = dict(Topic.objects.exclude(code__isnull=True)
                       .values_list('pk', 'code'))
    drafts = {draft.external_id: draft
              for draft in batch.drafts.select_for_update()}
    report = {'applied': [], 'already': [], 'reset': [], 'skipped': [],
              'images': [], 'fields': 0, 'reordered': 0}
    if patch.get('order'):
        # Порядок — не содержание: ставится всем строкам, правки учителя
        # он не затрагивает.
        position = {external_id: index * 10
                    for index, external_id in enumerate(patch['order'], start=1)}
        moved = [draft for draft in drafts.values()
                 if draft.position != position[draft.external_id]]
        for draft in moved:
            draft.position = position[draft.external_id]
        TextbookTaskDraft.objects.bulk_update(moved, ['position'], batch_size=500)
        report['reordered'] = len(moved)
    for row in patch['drafts']:
        external_id = row['external_id']
        draft = drafts[external_id]
        if draft.status == TextbookTaskDraft.STATUS_IMPORTED or draft.imported_task_id:
            report['skipped'].append((external_id, 'уже загружена в каталог'))
            continue
        before, after = row['before'], row['after']
        if draft.status != before.get('status'):
            report['skipped'].append(
                (external_id, f'статус изменён после выгрузки: {draft.status}'))
            continue
        conflicts = []
        pending = {}
        for name in PATCH_FIELDS:
            current = _current_value(draft, name, codes_by_pk)
            if name in after and current == after[name]:
                continue
            if current != before.get(name):
                conflicts.append(name)
            elif name in after:
                pending[name] = after[name]
        if conflicts:
            report['skipped'].append(
                (external_id, 'изменено после выгрузки: ' + ', '.join(conflicts)))
            continue
        if not pending:
            report['already'].append(external_id)
            continue
        update = set()
        for name, value in pending.items():
            if name == 'topic_code':
                old = draft.topic_id
                draft.topic_id = topic_ids[value] if value else None
                update.add('topic')
                if 'topic_codes' not in pending:
                    draft.topic_ids = [pk for pk in draft.topic_ids if pk != old]
                    update.add('topic_ids')
            elif name == 'topic_codes':
                draft.topic_ids = [topic_ids[code] for code in value if code]
                update.add('topic_ids')
            else:
                setattr(draft, name, value)
                update.add(name)
        if draft.topic_id and draft.topic_id not in draft.topic_ids:
            draft.topic_ids = [draft.topic_id] + list(draft.topic_ids)
            update.add('topic_ids')
        if draft.status == TextbookTaskDraft.STATUS_APPROVED:
            draft.status = TextbookTaskDraft.STATUS_REVIEW
            draft.reviewed_by = None
            draft.reviewed_at = None
            update.update({'status', 'reviewed_by', 'reviewed_at'})
            report['reset'].append(external_id)
        draft.save(update_fields=sorted(update))
        report['applied'].append(external_id)
        report['fields'] += len(pending)
    # Предупреждения о рисунках считаются по файлам этой партии, а не по
    # состоянию копии, где делали сверку.
    refresh_image_warnings(batch)
    changed = set(report['applied'])
    # Независимая проверка: перечитываем записанное и сверяем с пакетом.
    codes_by_pk = dict(Topic.objects.exclude(code__isnull=True)
                       .values_list('pk', 'code'))
    rows = {row['external_id']: row for row in patch['drafts']}
    for draft in batch.drafts.filter(external_id__in=changed):
        for name, expected in rows[draft.external_id]['after'].items():
            if name == 'warnings':
                continue  # пересчитаны refresh_image_warnings
            actual = _current_value(draft, name, codes_by_pk)
            if name == 'topic_codes':
                if not set(expected) <= set(actual):
                    raise TextbookPatchError(
                        f'{draft.external_id}: темы после записи не совпали.')
            elif actual != expected:
                raise TextbookPatchError(
                    f'{draft.external_id}: поле {name} после записи не совпало.')
        missing = unmatched_image_names(draft)
        if missing:
            report['images'].append((draft.external_id, missing))
    if not apply:
        transaction.set_rollback(True)
    return report

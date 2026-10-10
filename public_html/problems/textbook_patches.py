"""Точечные правки уже залитой партии черновиков без повторной заливки.

Сверку большой книги делают на локальной копии партии. Чтобы не повторять
работу на сервере, разница между исходным состоянием (выгрузка
``export_textbook_batches`` до правок) и текущим переносится пакетом
правок: для каждого поля — прежнее и новое значение. На сервере строка
меняется, только если все её поля совпадают с прежними значениями: так
поздние правки учителя не перезаписываются, а такие строки попадают
в отчёт.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from django.db import transaction

from .models import TextbookImportBatch, TextbookTaskDraft, Topic
from .textbook_import import normalize_answer_mask
from .textbook_transfer import serialize_batch

PATCH_KIND = 'textbook-draft-patch'
PATCH_VERSION = 1
# Содержание черновика, маски и темы. Статус и отметки сверки не входят:
# одобряет человек на сервере.
TEXT_FIELDS = ('text_latex', 'author_answer_latex', 'author_solution_latex',
               'answer_latex', 'solution_latex', 'answer_mask')
LIST_FIELDS = ('subitems', 'warnings', 'images')
TOPIC_FIELDS = ('topic_code', 'topic_codes')
PATCH_FIELDS = TEXT_FIELDS + LIST_FIELDS + TOPIC_FIELDS


class TextbookPatchError(ValueError):
    pass


def read_batch_rows(path):
    """Строки черновиков первой партии выгрузки (ZIP или batches.json)."""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            payload = json.loads(archive.read('batches.json'))
    else:
        payload = json.loads(path.read_text(encoding='utf-8'))
    batches = payload.get('batches') or []
    if len(batches) != 1:
        raise TextbookPatchError('В выгрузке должна быть ровно одна партия.')
    return batches[0]['drafts']


def build_draft_patch(baseline_rows, current_rows, *, source=''):
    """Пакет правок: поля, где текущее состояние отличается от исходного."""
    baseline = {row['external_id']: row for row in baseline_rows}
    current = {row['external_id']: row for row in current_rows}
    if set(baseline) != set(current):
        missing = sorted(set(baseline) ^ set(current))[:10]
        raise TextbookPatchError(
            f'Набор задач не совпадает с исходной выгрузкой: {missing}')
    drafts = []
    for external_id, row in current.items():
        before_row = baseline[external_id]
        fields = {
            name: {'before': before_row.get(name), 'after': row.get(name)}
            for name in PATCH_FIELDS
            if before_row.get(name) != row.get(name)
        }
        if fields:
            drafts.append({'external_id': external_id, 'fields': fields})
    return {'kind': PATCH_KIND, 'version': PATCH_VERSION, 'source': source,
            'drafts': drafts}


def current_rows(batch):
    return serialize_batch(batch)['drafts']


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


def _check_value(name, value):
    """Проверяет тип и маски, значение записывается как есть.

    Нормализацию заливки (``normalize_subitems``) не применяем: пакет несёт
    уже сверенный текст, повторная обработка могла бы его изменить.
    """
    if name in TEXT_FIELDS:
        if not isinstance(value, str):
            raise TextbookPatchError(f'Поле {name} должно быть строкой.')
        if name == 'answer_mask':
            normalize_answer_mask(value)
        return value
    if not isinstance(value, list):
        raise TextbookPatchError(f'Поле {name} должно быть списком.')
    if name == 'subitems':
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict) or not all(
                    isinstance(v, str) for v in item.values()):
                raise TextbookPatchError(f'Подпункт {index}: ожидались строки.')
            normalize_answer_mask(item.get('answer_mask'),
                                  key=f'subitems[{index}].answer_mask')
    return value


@transaction.atomic
def apply_draft_patch(batch, patch, *, apply=False):
    """Применяет пакет; без ``apply`` только проверяет (откат транзакции).

    Возвращает отчёт: применённые строки, пропущенные с причиной (поле
    изменилось после выгрузки, строка загружена в каталог, строки нет).
    """
    if patch.get('kind') != PATCH_KIND or patch.get('version') != PATCH_VERSION:
        raise TextbookPatchError('Это не пакет правок черновиков версии 1.')
    unknown = {name for row in patch['drafts'] for name in row['fields']
               if name not in PATCH_FIELDS}
    if unknown:
        raise TextbookPatchError(f'Неизвестные поля пакета: {sorted(unknown)}')
    batch = TextbookImportBatch.objects.select_for_update().get(pk=batch.pk)
    codes = set()
    for row in patch['drafts']:
        for name in TOPIC_FIELDS:
            change = row['fields'].get(name)
            if change:
                after = change['after']
                codes.update(after if isinstance(after, list) else [after])
    topic_ids = _topic_ids(codes)
    codes_by_pk = dict(Topic.objects.exclude(code__isnull=True)
                       .values_list('pk', 'code'))
    drafts = {draft.external_id: draft
              for draft in batch.drafts.select_for_update()}
    report = {'applied': [], 'skipped': [], 'fields': 0}
    for row in patch['drafts']:
        external_id = row['external_id']
        draft = drafts.get(external_id)
        if draft is None:
            report['skipped'].append((external_id, 'нет такой задачи в партии'))
            continue
        if draft.status == TextbookTaskDraft.STATUS_IMPORTED or draft.imported_task_id:
            report['skipped'].append((external_id, 'уже загружена в каталог'))
            continue
        changed = [name for name, change in row['fields'].items()
                   if _current_value(draft, name, codes_by_pk) != change['before']]
        if changed:
            report['skipped'].append(
                (external_id, 'поле изменено после выгрузки: ' + ', '.join(changed)))
            continue
        for name, change in row['fields'].items():
            after = change['after']
            if name == 'topic_code':
                draft.topic_id = topic_ids[after] if after else None
            elif name == 'topic_codes':
                draft.topic_ids = [topic_ids[code] for code in after if code]
            else:
                setattr(draft, name, _check_value(name, after))
        if draft.topic_id and draft.topic_id not in draft.topic_ids:
            draft.topic_ids = [draft.topic_id] + list(draft.topic_ids)
        field_names = {'topic_code': 'topic', 'topic_codes': 'topic_ids'}
        update = {field_names.get(name, name) for name in row['fields']}
        if 'topic' in update:
            update.add('topic_ids')
        draft.save(update_fields=sorted(update))
        report['applied'].append(external_id)
        report['fields'] += len(row['fields'])
    # Независимая проверка: перечитываем записанное и сверяем с пакетом.
    applied = set(report['applied'])
    codes_by_pk = dict(Topic.objects.exclude(code__isnull=True)
                       .values_list('pk', 'code'))
    for draft in batch.drafts.filter(external_id__in=applied):
        row = next(r for r in patch['drafts'] if r['external_id'] == draft.external_id)
        for name, change in row['fields'].items():
            expected = change['after']
            if name == 'topic_codes':
                actual = [codes_by_pk.get(pk) for pk in draft.topic_ids]
                if not set(expected) <= set(actual):
                    raise TextbookPatchError(
                        f'{draft.external_id}: темы после записи не совпали.')
                continue
            if _current_value(draft, name, codes_by_pk) != expected:
                raise TextbookPatchError(
                    f'{draft.external_id}: поле {name} после записи не совпало.')
    if not apply:
        transaction.set_rollback(True)
    return report

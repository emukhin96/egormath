"""Безопасная загрузка проверяемого JSON парсера задачников.

Первый этап создаёт только черновики. Второй, после ручного одобрения,
идемпотентно создаёт задачи и backing-worksheet подборок. Рабочие поля
answer_latex/solution_latex не меняются: ими продолжает владеть редакторский
и AI-контур.
"""

import hashlib
import io
import json
import re
import zipfile
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils.text import slugify

from .models import (Source, Task, TaskImage, TaskSource, TaskSubitem,
                     TextbookImportAsset, TextbookImportBatch,
                     TextbookTaskDraft, Topic)
from .rubricator import set_task_topics
from .textbook_parser import (ZIV_LEAKED_HEADING_WARNING,
                              ZIV_LOOKS_LIKE_HEADING_WARNING,
                              ZIV_SPLIT_FROM_WARNING,
                              ZIV_UNEVEN_VARIANT_WARNING, Marker,
                              apply_imported_answer, apply_imported_math,
                              collapse_repeated_lead, strip_heading_dot,
                              draft_has_ziv_leak, finalize_draft_images,
                              reattach_leaked_following_answers,
                              _ziv_apply_variant_parity,
                              _ziv_draft_topic_title,
                              _ziv_looks_like_topic_title,
                              _ziv_topic_variant, order_letter_subitems,
                              reconstruct_imported_body,
                              rewalk_ziv_merged_body,
                              split_leaked_structural_tail,
                              strip_leading_subitem_label, task_from_block)
from .textbook_topics import apply_topic_suggestions, draft_topic_ids


MAX_BUNDLE_TASKS = 10000
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.pdf'}
IMAGE_WARNING_PREFIX = 'Требуется загрузить файлы изображений:'


def normalize_image_stem(name):
    path = Path(str(name or '').replace('\\', '/'))
    return path.stem.lower().strip()


def _is_junk_image_path(path):
    """AppleDouble / __MACOSX / скрытые файлы из ZIP с macOS."""
    parts = Path(str(path or '').replace('\\', '/')).parts
    if '__MACOSX' in parts:
        return True
    name = Path(parts[-1] if parts else '').name
    return name.startswith('.')


class TextbookImportError(ValueError):
    """Ошибка формата или конфликт, пригодный для показа редактору."""


def _required_string(row, key, *, allow_blank=False, limit=None):
    value = row.get(key)
    if not isinstance(value, str):
        raise TextbookImportError(f'Поле {key} должно быть строкой.')
    value = value.strip()
    if not allow_blank and not value:
        raise TextbookImportError(f'Поле {key} не может быть пустым.')
    if limit and len(value) > limit:
        raise TextbookImportError(
            f'Поле {key} длиннее допустимых {limit} символов.')
    return value


def _string_list(value, key):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise TextbookImportError(f'Поле {key} должно быть массивом строк.')
    return [x.strip() for x in value if x.strip()]


def normalize_subitems(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise TextbookImportError('Поле subitems должно быть массивом.')
    result = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise TextbookImportError(
                f'Подпункт {index} должен быть объектом.')
        label = str(item.get('label') or index)[:16]
        text = strip_leading_subitem_label(
            apply_imported_math(_required_string(item, 'text_latex')),
            label)
        result.append({
            'label': label,
            'text_latex': text,
            'author_answer_latex': apply_imported_answer(
                item.get('author_answer_latex') or ''),
            'author_solution_latex': apply_imported_math(
                item.get('author_solution_latex') or ''),
        })
    return order_letter_subitems(result)


def _confidence(value):
    try:
        number = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        number = Decimal('0')
    if not number.is_finite():
        return Decimal('0')
    return max(Decimal('0'), min(Decimal('1'), number))


@transaction.atomic
def create_batch_from_bundle(payload, *, user, title, source_title,
                             source_author='', source_year=None):
    """Создаёт партию и черновики; рабочий каталог задач не затрагивает."""
    if not isinstance(payload, dict) or payload.get('schema_version') != 1:
        raise TextbookImportError('Поддерживается только schema_version=1.')
    profile = payload.get('profile')
    if not isinstance(profile, str) or not profile.strip():
        raise TextbookImportError('В файле отсутствует профиль парсера.')
    rows = payload.get('tasks')
    if not isinstance(rows, list) or not rows:
        raise TextbookImportError('В файле нет задач.')
    if len(rows) > MAX_BUNDLE_TASKS:
        raise TextbookImportError(
            f'В одной партии допускается не больше {MAX_BUNDLE_TASKS} задач.')

    source_lookup = {
        'title': source_title.strip(), 'author': source_author.strip(),
        'year': source_year,
    }
    # Старые данные не гарантируют уникальность Source; выбираем первую
    # запись детерминированно вместо необработанного MultipleObjectsReturned.
    source = Source.objects.filter(**source_lookup).order_by('pk').first()
    if source is None:
        source = Source.objects.create(**source_lookup)
    batch = TextbookImportBatch.objects.create(
        title=title.strip(), profile=profile.strip(), source=source,
        created_by=user,
        diagnostics=(payload.get('diagnostics')
                     if isinstance(payload.get('diagnostics'), dict) else {}))

    seen = set()
    drafts = []
    valid_statuses = dict(TextbookTaskDraft.STATUS_CHOICES)
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise TextbookImportError(f'Задача {position} должна быть объектом.')
        external_id = _required_string(row, 'external_id', limit=190)
        if external_id in seen:
            raise TextbookImportError(
                f'Ключ {external_id} встречается в партии повторно.')
        seen.add(external_id)
        status = row.get('review_status', TextbookTaskDraft.STATUS_REVIEW)
        if status not in valid_statuses:
            status = TextbookTaskDraft.STATUS_REVIEW
        # Парсер не может сам одобрить или закрыть строку.
        if status in {
                TextbookTaskDraft.STATUS_APPROVED,
                TextbookTaskDraft.STATUS_IMPORTED}:
            status = TextbookTaskDraft.STATUS_REVIEW
        path = [
            strip_heading_dot(part)
            for part in _string_list(row.get('source_path'), 'source_path')]
        path = [part for part in path if part]
        warnings = _string_list(row.get('warnings'), 'warnings')
        images = _string_list(row.get('images'), 'images')
        subitems = normalize_subitems(row.get('subitems'))
        text_latex = collapse_repeated_lead(apply_imported_math(
            _required_string(row, 'text_latex', allow_blank=True)))
        if not text_latex and not subitems:
            raise TextbookImportError(
                f'Задача {external_id} не содержит условия или подпунктов.')
        author_answer_latex = apply_imported_answer(
            row.get('author_answer_latex') or '')
        author_solution_latex = apply_imported_math(
            row.get('author_solution_latex') or '')
        if subitems:
            author_answer_latex = ''
            author_solution_latex = ''
        drafts.append(TextbookTaskDraft(
            batch=batch,
            external_id=external_id,
            source_number=_required_string(
                row, 'source_number', allow_blank=True, limit=190)
                or external_id,
            source_path=path,
            collection_key=str(row.get('collection_key') or '')[:500],
            collection_title=strip_heading_dot(
                str(row.get('collection_title') or ''))[:190],
            topic_original=strip_heading_dot(
                str(row.get('topic_original') or ''))[:255],
            text_latex=text_latex,
            subitems=subitems,
            images=images,
            author_answer_latex=author_answer_latex,
            author_solution_latex=author_solution_latex,
            solution_source_external_id=(
                external_id if (author_answer_latex
                                or author_solution_latex
                                or any(
                                    item['author_answer_latex']
                                    or item['author_solution_latex']
                                    for item in subitems)) else ''),
            confidence=_confidence(row.get('confidence')),
            warnings=warnings,
            status=status,
        ))
    apply_topic_suggestions(drafts)
    mark_already_imported_drafts(drafts, source)
    TextbookTaskDraft.objects.bulk_create(drafts, batch_size=500)
    if batch.profile == 'ziv':
        repair_ziv_batch_leaks(batch)
        batch.refresh_from_db()
    sync_batch_draft_images(batch)
    return batch


def read_bundle(upload, max_bytes=50 * 1024 * 1024):
    raw = upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise TextbookImportError('Файл import.json больше 50 МБ.')
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TextbookImportError(f'Некорректный UTF-8 JSON: {exc}') from exc


def _read_tex(upload, max_bytes=50 * 1024 * 1024):
    raw = upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise TextbookImportError(
            f'Файл {Path(upload.name).name} больше 50 МБ.')
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise TextbookImportError(
            f'Файл {Path(upload.name).name} не является UTF-8 TEX.') from exc


def parse_tex_uploads(tasks_upload, *, profile, solutions_upload=None):
    """Преобразует загруженные TEX в тот же JSON-контракт, что CLI."""
    from .textbook_parser import bundle_from_text

    try:
        bundle = bundle_from_text(
            profile,
            _read_tex(tasks_upload),
            (_read_tex(solutions_upload) if solutions_upload else ''),
            tasks_file=Path(tasks_upload.name).name,
            solutions_file=(Path(solutions_upload.name).name
                            if solutions_upload else ''),
        )
    except ValueError as exc:
        raise TextbookImportError(str(exc)) from exc
    return asdict(bundle)


ALREADY_IMPORTED_WARNING = (
    'Ключ уже есть в базе; повторно не загружается.')
ALREADY_IMPORTED_TEXT_WARNING = (
    'Ключ уже есть в базе, условие отличается от сохранённого.')


def mark_already_imported_drafts(drafts, source):
    """Помечает строки с тем же ключом источника как уже импортированные."""
    locators = [draft.external_id for draft in drafts]
    refs = {
        ref.locator: ref
        for ref in TaskSource.objects.select_related('task').filter(
            source=source, locator__in=locators)
    }
    for draft in drafts:
        ref = refs.get(draft.external_id)
        if ref is None:
            continue
        draft.imported_task = ref.task
        draft.status = TextbookTaskDraft.STATUS_IMPORTED
        warning = (
            ALREADY_IMPORTED_TEXT_WARNING
            if draft.text_latex.strip() != ref.task.text_latex.strip()
            else ALREADY_IMPORTED_WARNING)
        if warning not in draft.warnings:
            draft.warnings = list(draft.warnings) + [warning]


def cleanup_junk_image_assets(batch):
    """Удаляет служебные файлы macOS, попавшие в партию как рисунки."""
    removed = 0
    for asset in list(batch.assets.all()):
        if not (
                _is_junk_image_path(asset.original_name)
                or _is_junk_image_path(asset.stem)):
            continue
        if asset.file:
            asset.file.delete(save=False)
        asset.delete()
        removed += 1
    return removed


def sync_batch_draft_images(batch):
    """Достаёт рисунки из LaTeX уже сохранённых черновиков."""
    drafts = list(
        batch.drafts.exclude(status=TextbookTaskDraft.STATUS_IMPORTED))
    dirty = {}
    if str(batch.profile or '') == 'ziv':
        for draft in reattach_leaked_following_answers(drafts):
            dirty[draft.pk] = draft
    for draft in drafts:
        if finalize_draft_images(draft):
            dirty[draft.pk] = draft
    dirty = list(dirty.values())
    if dirty:
        TextbookTaskDraft.objects.bulk_update(dirty, [
            'text_latex', 'author_answer_latex', 'author_solution_latex',
            'subitems', 'images',
        ])
    cleanup_junk_image_assets(batch)
    refresh_image_warnings(batch)
    return len(dirty)


def refresh_image_warnings(batch):
    """Оставляет блокирующее предупреждение только у несопоставленных рисунков."""
    resolved = set(batch.assets.values_list('stem', flat=True))
    drafts = list(batch.drafts.all())
    for draft in drafts:
        warnings = [
            item for item in draft.warnings
            if not str(item).startswith(IMAGE_WARNING_PREFIX)]
        missing = [
            name for name in draft.images
            if normalize_image_stem(name) not in resolved]
        if missing:
            warnings.append(
                IMAGE_WARNING_PREFIX + ' ' + ', '.join(missing))
        draft.warnings = warnings
    if drafts:
        TextbookTaskDraft.objects.bulk_update(drafts, ['warnings'])
    return batch


def _ziv_known_topics_from_drafts(drafts):
    known = []
    seen = set()
    for draft in drafts:
        parsed = _ziv_topic_variant(draft.external_id)
        if parsed is None:
            continue
        work, topic = parsed[0].split('/', 1)
        try:
            topic_num = int(topic)
        except ValueError:
            continue
        identity = (work, topic_num)
        if identity in seen:
            continue
        seen.add(identity)
        title = _ziv_draft_topic_title(
            draft.source_path, draft.collection_title, draft.topic_original)
        known.append((work, topic_num, title))
    return known


def _copy_subitem_author_fields(old_subitems, new_subitems):
    old_by_label = {
        str(item.get('label') or ''): item
        for item in (old_subitems or [])
        if isinstance(item, dict)
    }
    for item in new_subitems:
        prev = old_by_label.get(str(item.get('label') or ''))
        if not prev:
            continue
        if not item.get('author_answer_latex') and prev.get(
                'author_answer_latex'):
            item['author_answer_latex'] = prev['author_answer_latex']
        if not item.get('author_solution_latex') and prev.get(
                'author_solution_latex'):
            item['author_solution_latex'] = prev['author_solution_latex']
    return new_subitems


def _warnings_without(warnings, *removed):
    drop = set(removed)
    return [item for item in (warnings or []) if item not in drop]


def _append_warning(warnings, warning):
    items = list(warnings or [])
    if warning not in items:
        items.append(warning)
    return items


def refresh_ziv_variant_parity(batch):
    """Пересчитывает предупреждение о нечётных вариантах Зива по текущим строкам."""
    drafts = list(
        batch.drafts.exclude(status=TextbookTaskDraft.STATUS_SKIPPED))
    fakes = []
    for draft in drafts:
        fake = type('DraftParity', (), {})()
        fake.external_id = draft.external_id
        fake.warnings = _warnings_without(
            draft.warnings, ZIV_UNEVEN_VARIANT_WARNING)
        fakes.append(fake)
    uneven = _ziv_apply_variant_parity(fakes)
    by_id = {fake.external_id: fake.warnings for fake in fakes}
    updates = []
    for draft in drafts:
        warnings = by_id.get(draft.external_id, _warnings_without(
            draft.warnings, ZIV_UNEVEN_VARIANT_WARNING))
        if warnings != list(draft.warnings or []):
            draft.warnings = warnings
            updates.append(draft)
    if updates:
        TextbookTaskDraft.objects.bulk_update(updates, ['warnings'])
    diagnostics = dict(batch.diagnostics or {})
    diagnostics['ziv_uneven_variant_topics'] = uneven
    batch.diagnostics = diagnostics
    batch.save(update_fields=['diagnostics', 'updated_at'])
    return uneven


def ziv_variant_summary(batch):
    """Сводка длин вариантов по темам Зива для страницы партии."""
    if str(batch.profile or '') != 'ziv':
        return []
    rows = {}
    uneven_keys = {
        item.get('topic')
        for item in (batch.diagnostics or {}).get(
            'ziv_uneven_variant_topics') or []
        if isinstance(item, dict) and item.get('topic')
    }
    drafts = (batch.drafts.exclude(status=TextbookTaskDraft.STATUS_SKIPPED)
              .only('external_id', 'collection_title', 'source_path',
                    'topic_original'))
    for draft in drafts:
        parsed = _ziv_topic_variant(draft.external_id)
        if parsed is None:
            continue
        topic_key, variant = parsed
        work = ''
        if draft.source_path:
            work = str(draft.source_path[0]).strip()
        if not work:
            if topic_key.startswith('kr/'):
                work = 'Контрольные работы'
            elif topic_key.startswith('pr/'):
                work = 'Проверочные работы'
            else:
                work = 'Самостоятельные работы'
        row = rows.setdefault(topic_key, {
            'key': topic_key,
            'title': '',
            'work': work,
            'variants': {},
        })
        row['variants'][variant] = row['variants'].get(variant, 0) + 1
        title = (draft.collection_title or '').strip()
        if not title and draft.source_path and len(draft.source_path) > 1:
            title = str(draft.source_path[1]).strip()
        if not title:
            title = (draft.topic_original or '').strip()
        if title:
            row['title'] = title
        if work:
            row['work'] = work
    summary = []
    for key, row in sorted(rows.items()):
        counts = [row['variants'][name]
                  for name in sorted(row['variants'])]
        summary.append({
            'key': key,
            'work': row['work'],
            'title': row['title'] or key,
            'counts_label': ' / '.join(str(n) for n in counts),
            'total': sum(counts),
            'uneven': key in uneven_keys,
        })
    return summary


@transaction.atomic
def repair_ziv_batch_leaks(batch):
    """Срезает прилипшие заголовки и выделяет слипшиеся задачи уже залитой партии."""
    if str(batch.profile or '') != 'ziv':
        raise TextbookImportError('Пересчёт слипаний есть только у профиля ziv.')
    drafts = list(batch.drafts.order_by('external_id', 'pk'))
    existing = {draft.external_id: draft for draft in drafts}
    known_topics = _ziv_known_topics_from_drafts(drafts)
    topic_by_key = {}
    for draft in drafts:
        parsed = _ziv_topic_variant(draft.external_id)
        if parsed and draft.topic_id:
            topic_by_key.setdefault(parsed[0], draft.topic_id)
    trimmed_ids = []
    created_ids = []
    collision_ids = []
    skipped_heading_ids = []
    to_update = []
    to_create = []

    for draft in drafts:
        if not draft_has_ziv_leak(draft.text_latex, draft.subitems):
            continue
        parsed = _ziv_topic_variant(draft.external_id)
        source_topic = parsed[0] if parsed else None
        source_number = draft.external_id.rsplit('/', 1)[-1]
        old_subitems = list(draft.subitems or [])
        old_text = draft.text_latex
        extracted = rewalk_ziv_merged_body(
            draft.external_id, draft.source_path, draft.text_latex,
            draft.subitems, collection_title=draft.collection_title,
            topic_original=draft.topic_original,
            known_topics=known_topics)
        same = next(
            (task for task in extracted
             if task.external_id == draft.external_id),
            None)
        if same is None and source_topic:
            same = next(
                (task for task in extracted
                 if task.external_id.rsplit('/', 1)[-1] == source_number
                 and _ziv_topic_variant(task.external_id)
                 and _ziv_topic_variant(task.external_id)[0] == source_topic),
                None)
        if same is None:
            kept, tail = split_leaked_structural_tail(
                reconstruct_imported_body(draft.text_latex, draft.subitems))
            if not tail.strip():
                continue
            same = task_from_block(
                Marker(0, 0, draft.external_id), kept, draft.source_path)
            extracted = [same]

        new_subitems = _copy_subitem_author_fields(
            old_subitems,
            normalize_subitems([asdict(item) for item in same.subitems]))
        new_text = same.text_latex
        if not new_text and not new_subitems:
            continue
        structure_changed = (
            new_text != old_text or new_subitems != old_subitems)
        if structure_changed:
            draft.text_latex = new_text
            draft.subitems = new_subitems
            if new_subitems:
                draft.author_answer_latex = ''
                draft.author_solution_latex = ''
            draft.warnings = _append_warning(
                draft.warnings, ZIV_LEAKED_HEADING_WARNING)
            if (not new_subitems
                    and _ziv_looks_like_topic_title(new_text)):
                draft.status = TextbookTaskDraft.STATUS_SKIPPED
                draft.warnings = _append_warning(
                    draft.warnings, ZIV_LOOKS_LIKE_HEADING_WARNING)
                skipped_heading_ids.append(draft.external_id)
            elif (draft.status == TextbookTaskDraft.STATUS_APPROVED
                    and len(new_subitems) != len(old_subitems)):
                draft.status = TextbookTaskDraft.STATUS_REVIEW
            to_update.append(draft)
            trimmed_ids.append(draft.external_id)

        for task in extracted:
            if same is not None and task.external_id == same.external_id:
                continue
            if task.external_id == draft.external_id:
                continue
            other = _ziv_topic_variant(task.external_id)
            if source_topic and (other is None or other[0] != source_topic):
                continue
            try:
                task_number = int(task.external_id.rsplit('/', 1)[-1])
            except ValueError:
                continue
            if task_number > 8:
                continue
            if (not task.subitems
                    and _ziv_looks_like_topic_title(task.text_latex)):
                continue
            if task.external_id in existing:
                collision_ids.append(task.external_id)
                continue
            if not task.text_latex and not task.subitems:
                continue
            warnings = list(task.warnings)
            if ZIV_SPLIT_FROM_WARNING not in warnings:
                warnings.append(ZIV_SPLIT_FROM_WARNING)
            created = TextbookTaskDraft(
                batch=batch,
                external_id=task.external_id,
                source_number=task.source_number or task.external_id,
                source_path=task.source_path,
                collection_key=task.collection_key,
                collection_title=task.collection_title,
                topic_original=task.topic_original,
                topic_id=topic_by_key.get(other[0] if other else ''),
                topic_ids=([topic_by_key[other[0]]]
                           if other and topic_by_key.get(other[0]) else []),
                text_latex=task.text_latex,
                subitems=normalize_subitems(
                    [asdict(item) for item in task.subitems]),
                images=list(task.images or []),
                author_answer_latex='',
                author_solution_latex='',
                confidence=_confidence(task.confidence),
                warnings=warnings,
                status=TextbookTaskDraft.STATUS_REVIEW,
            )
            existing[task.external_id] = created
            to_create.append(created)
            created_ids.append(task.external_id)

    if to_update:
        TextbookTaskDraft.objects.bulk_update(to_update, [
            'text_latex', 'subitems', 'author_answer_latex',
            'author_solution_latex', 'warnings', 'status',
        ])
    if to_create:
        apply_topic_suggestions(to_create)
        TextbookTaskDraft.objects.bulk_create(to_create, batch_size=500)
    leftover = []
    for draft in batch.drafts.exclude(status=TextbookTaskDraft.STATUS_SKIPPED):
        try:
            number = int(str(draft.external_id).rsplit('/', 1)[-1])
        except ValueError:
            number = 0
        if number <= 8:
            continue
        draft.status = TextbookTaskDraft.STATUS_SKIPPED
        draft.warnings = _append_warning(
            draft.warnings, ZIV_LOOKS_LIKE_HEADING_WARNING)
        leftover.append(draft)
        skipped_heading_ids.append(draft.external_id)
    if leftover:
        TextbookTaskDraft.objects.bulk_update(
            leftover, ['status', 'warnings'])
    uneven = refresh_ziv_variant_parity(batch)
    batch.refresh_from_db()
    diagnostics = dict(batch.diagnostics or {})
    diagnostics['ziv_leak_repair'] = {
        'trimmed': trimmed_ids,
        'created': created_ids,
        'collisions': sorted(set(collision_ids)),
        'skipped_headings': skipped_heading_ids,
    }
    diagnostics['ziv_uneven_variant_topics'] = uneven
    batch.diagnostics = diagnostics
    batch.save(update_fields=['diagnostics', 'updated_at'])
    sync_batch_draft_images(batch)
    return diagnostics['ziv_leak_repair']


def attach_image_archive(batch, upload, max_bytes=80 * 1024 * 1024):
    """Распаковывает ZIP и сопоставляет файлы с именами из черновиков."""
    raw = upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise TextbookImportError('Архив изображений больше 80 МБ.')
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise TextbookImportError(
            'Нужен ZIP с PNG, JPEG или PDF рисунками.') from exc
    entries = []
    seen = {}
    collisions = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = Path(info.filename)
        if _is_junk_image_path(path):
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        stem = normalize_image_stem(path.name)
        if not stem:
            continue
        if stem in seen:
            collisions.setdefault(stem, [seen[stem]]).append(info.filename)
        else:
            seen[stem] = info.filename
        entries.append((stem, path, info))
    if collisions:
        details = '; '.join(
            f'{stem} ({", ".join(names)})'
            for stem, names in sorted(collisions.items()))
        raise TextbookImportError(
            'В архиве несколько рисунков с одним именем файла: '
            f'{details}. Оставьте один файл на имя или переименуйте.')
    if not entries:
        raise TextbookImportError(
            'В архиве нет файлов PNG, JPEG или PDF.')
    stored = 0
    for stem, path, info in entries:
        try:
            payload = archive.read(info)
        except Exception as exc:
            raise TextbookImportError(
                f'Не удалось прочитать {path.name}: {exc}') from exc
        asset, _created = TextbookImportAsset.objects.update_or_create(
            batch=batch, stem=stem,
            defaults={'original_name': path.name})
        asset.file.save(path.name, ContentFile(payload), save=True)
        stored += 1
    sync_batch_draft_images(batch)
    return stored


def unmatched_image_names(draft, resolved_stems=None):
    resolved = resolved_stems
    if resolved is None:
        resolved = set(draft.batch.assets.values_list('stem', flat=True))
    return [name for name in draft.images
            if normalize_image_stem(name) not in resolved]


def _collection_locator(path):
    raw = json.dumps(path, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]
    prefix = slugify(path[-1], allow_unicode=False)[:60] if path else 'root'
    return f'{prefix or "section"}-{digest}'


def _leaf_collection_locator(collection_key, path):
    """Отделяет стабильные ключи листьев от вычисляемых ключей разделов."""
    if collection_key:
        locator = f'key:{collection_key}'
        if len(locator) <= 500:
            return locator
        digest = hashlib.sha256(collection_key.encode('utf-8')).hexdigest()
        return f'key-sha256:{digest}'
    return _collection_locator(path)


_VARIANT_TAIL_RE = re.compile(r'(?i)^вариант\s+\d+')
_CHAPTER_HEAD_RE = re.compile(r'(?i)^глава\s+\d+')


def _collection_layout(path, collection_key):
    """Лист подборки + рубрики: варианты и параграфы внутри главы."""
    original = [str(part).strip() for part in path if str(part).strip()]
    path = list(original)
    headings = []
    key = (collection_key or '').strip()

    if path and _VARIANT_TAIL_RE.match(path[-1]):
        headings.append(path[-1])
        path = path[:-1]
        key = re.sub(r'(?i)/v\d+$', '', key)

    if len(path) >= 2 and _CHAPTER_HEAD_RE.match(path[0]):
        headings = path[1:] + headings
        path = path[:1]
        joined = '/'.join(original)
        if not key or key == joined:
            key = path[0]
        elif key.startswith(path[0] + '/'):
            key = path[0]

    return path, headings, key


def _rubrics_to_append(current, headings):
    """Какие заголовки дописать, чтобы контекст листа стал headings."""
    headings = list(headings)
    if not headings:
        return []
    if current[-len(headings):] == headings:
        return []
    if not current:
        return headings
    if current[-1] == headings[-1] and (
            len(headings) == 1 or headings[0] in current):
        return []
    if headings[0] in current:
        return [headings[-1]] if len(headings) > 1 else []
    return headings


def _next_worksheet_order(worksheet):
    return (worksheet.items.aggregate(
        max_order=Max('order'))['max_order'] or 0) + 10


def _ensure_import_rubrics(worksheet, headings):
    """Добавляет хвостовые рубрики, не дублируя уже стоящий контекст."""
    from worksheets.models import WorksheetItem

    current = list(
        worksheet.items.filter(deleted_at=None, task=None)
        .exclude(rubric='')
        .order_by('order', 'pk')
        .values_list('rubric', flat=True))
    to_add = _rubrics_to_append(current, headings)
    order = _next_worksheet_order(worksheet)
    for title in to_add:
        WorksheetItem.objects.create(
            worksheet=worksheet, rubric=title[:190], order=order)
        order += 10
    return order


def _collection_for_path(batch, path, cache, collection_key=''):
    from worksheets.models import Collection, Worksheet

    parent = None
    for depth in range(1, len(path) + 1):
        prefix = path[:depth]
        is_leaf = depth == len(path)
        locator = (_leaf_collection_locator(collection_key, prefix)
                   if is_leaf else _collection_locator(prefix))
        if locator in cache:
            collection = cache[locator]
            if is_leaf and collection.source_path != prefix:
                raise TextbookImportError(
                    f'Ключ подборки {collection_key} используется для '
                    'разных путей в одной партии.')
            parent = collection
            continue
        collection = (Collection.objects
                      .select_related('worksheet')
                      .filter(source=batch.source, locator=locator)
                      .first())
        if (collection is not None
                and collection.worksheet.owner_id != batch.created_by_id):
            raise TextbookImportError(
                f'Подборка «{prefix[-1]}» принадлежит другому редактору.')
        if collection is None:
            worksheet = Worksheet.objects.create(
                title=prefix[-1][:190], owner=batch.created_by)
            collection = Collection.objects.create(
                worksheet=worksheet, source=batch.source, parent=parent,
                locator=locator, source_path=prefix, order=depth * 10,
                is_published=is_leaf)
        elif is_leaf:
            collection_updates = []
            if collection.parent_id != (parent.pk if parent else None):
                collection.parent = parent
                collection_updates.append('parent')
            if collection.source_path != prefix:
                collection.source_path = prefix
                collection_updates.append('source_path')
            if not collection.is_published:
                collection.is_published = True
                collection_updates.append('is_published')
            if collection_updates:
                collection.save(update_fields=collection_updates)
            if collection.worksheet.title != prefix[-1][:190]:
                collection.worksheet.title = prefix[-1][:190]
                collection.worksheet.save(update_fields=['title'])
        cache[locator] = collection
        parent = collection
    return parent


def _merge_author_fields(task, draft):
    if draft.subitems:
        return
    updates = []
    for field in ('author_answer_latex', 'author_solution_latex'):
        incoming = getattr(draft, field).strip()
        existing = getattr(task, field).strip()
        if incoming and existing and incoming != existing:
            raise TextbookImportError(
                f'{draft.external_id}: авторское поле конфликтует с задачей '
                f'#{task.pk}. Проверьте сопоставление вручную.')
        if incoming and not existing:
            setattr(task, field, incoming)
            updates.append(field)
    if updates:
        task.save(update_fields=updates)


def _merge_subitem_author_fields(task, draft):
    existing = list(task.subitems.order_by('order', 'pk'))
    if len(existing) != len(draft.subitems):
        raise TextbookImportError(
            f'{draft.external_id}: число подпунктов существующей задачи '
            'отличается от импортируемого.')
    for sub, incoming in zip(existing, draft.subitems):
        incoming_text = str(incoming.get('text_latex') or '').strip()
        if sub.text_latex.strip() != incoming_text:
            raise TextbookImportError(
                f'{draft.external_id}: условие подпункта {sub.order} '
                'отличается от уже загруженного.')
        updates = []
        for field in ('author_answer_latex', 'author_solution_latex'):
            value = str(incoming.get(field) or '').strip()
            old = getattr(sub, field).strip()
            if value and old and value != old:
                raise TextbookImportError(
                    f'{draft.external_id}: конфликт авторского текста '
                    f'подпункта {sub.order}.')
            if value and not old:
                setattr(sub, field, value)
                updates.append(field)
        if updates:
            sub.save(update_fields=updates)


def _attach_task_images(task, draft, batch):
    """Дописывает недостающие рисунки, в том числе к повторно используемой задаче."""
    if not draft.images:
        return
    existing = {
        normalize_image_stem(image.filename): image
        for image in task.images.all()
    }
    used_orders = set(task.images.values_list('order', flat=True))
    assets = {
        asset.stem: asset
        for asset in batch.assets.filter(
            stem__in=[normalize_image_stem(name) for name in draft.images])
    }
    for index, name in enumerate(draft.images, start=1):
        stem = normalize_image_stem(name)
        if stem in existing:
            continue
        asset = assets.get(stem)
        if asset is None:
            continue
        order = index * 10
        while order in used_orders:
            order += 10
        used_orders.add(order)
        image = TaskImage(task=task, order=order)
        image.image.save(
            Path(asset.original_name).name, asset.file, save=True)
        existing[stem] = image


@transaction.atomic
def commit_batch(batch, *, user, draft_ids=None, require_complete=True):
    """Загружает одобренные черновики; повторный вызов безопасен.

    draft_ids — только эти одобренные строки (загрузка одной темы).
    require_complete — вся партия должна быть проверена; иначе достаточно
    выбранных строк, и партия остаётся на проверке.
    """
    from worksheets.models import WorksheetItem

    batch = (TextbookImportBatch.objects.select_for_update()
             .select_related('source', 'created_by').get(pk=batch.pk))
    if batch.created_by_id != user.pk and not user.is_superuser:
        raise TextbookImportError('Эту партию может загрузить только редактор.')
    if batch.status == TextbookImportBatch.STATUS_IMPORTED:
        return {'created': 0, 'reused': 0, 'collections': 0}
    if require_complete:
        blockers = batch.drafts.filter(status__in=[
            TextbookTaskDraft.STATUS_REVIEW,
            TextbookTaskDraft.STATUS_CONFLICT,
        ]).count()
        if blockers:
            raise TextbookImportError(
                f'Осталось непроверенных или конфликтных строк: {blockers}.')
    approved = batch.drafts.filter(status=TextbookTaskDraft.STATUS_APPROVED)
    if draft_ids is not None:
        approved = approved.filter(pk__in=draft_ids)
    if not require_complete and not approved.exists():
        raise TextbookImportError('Нет одобренных задач для загрузки.')
    missing_topics = approved.filter(topic__isnull=True).count()
    if missing_topics:
        raise TextbookImportError(
            f'У одобренных задач не выбрана тема рубрикатора: '
            f'{missing_topics}.')
    resolved_stems = set(batch.assets.values_list('stem', flat=True))
    missing_assets = sum(
        1 for draft in approved.only('images')
        if unmatched_image_names(draft, resolved_stems))
    if missing_assets:
        raise TextbookImportError(
            f'У одобренных задач не загружены изображения: '
            f'{missing_assets}.')

    created = 0
    reused = 0
    collection_cache = {}
    from worksheets.models import Collection
    initial_collection_count = Collection.objects.filter(
        source=batch.source).count()

    for draft in approved.select_related('topic').order_by('pk'):
        ref = (TaskSource.objects.select_related('task')
               .filter(source=batch.source, locator=draft.external_id).first())
        if ref:
            task = ref.task
            if task.text_latex.strip() != draft.text_latex.strip():
                raise TextbookImportError(
                    f'{draft.external_id}: ключ уже связан с другим условием.')
            _merge_subitem_author_fields(task, draft)
            reused += 1
        else:
            # Совпадение текста между изданиями — только подсказка для
            # рецензента, но не безопасное основание автоматически слить задачи.
            task = Task.objects.create(
                text_latex=draft.text_latex,
                author_answer_latex=(
                    '' if draft.subitems else draft.author_answer_latex),
                author_solution_latex=(
                    '' if draft.subitems else draft.author_solution_latex),
                stars=0, columns=0, created_by=batch.created_by)
            for index, item in enumerate(draft.subitems, start=1):
                TaskSubitem.objects.create(
                    task=task, order=index * 10,
                    text_latex=item['text_latex'],
                    author_answer_latex=item.get(
                        'author_answer_latex', ''),
                    author_solution_latex=item.get(
                        'author_solution_latex', ''))
            created += 1
            TaskSource.objects.create(
                task=task, source=batch.source,
                number=draft.source_number,
                locator=draft.external_id,
                source_path=draft.source_path)

        _attach_task_images(task, draft, batch)
        _merge_author_fields(task, draft)
        topic_ids = draft_topic_ids(draft)
        if topic_ids:
            if task.topic_links.exists():
                existing = set(task.topics.values_list('pk', flat=True))
                for topic in Topic.objects.filter(pk__in=topic_ids):
                    if topic.pk not in existing:
                        task.topics.add(topic)
            else:
                set_task_topics(task, topic_ids, draft.topic_id)

        path = [str(x).strip() for x in draft.source_path if str(x).strip()]
        if not path:
            path = [draft.collection_title.strip() or batch.title]
        path, headings, leaf_key = _collection_layout(
            path, draft.collection_key.strip())
        if not path:
            path = [draft.collection_title.strip() or batch.title]
        collection = _collection_for_path(
            batch, path, collection_cache, collection_key=leaf_key)
        if collection:
            worksheet = collection.worksheet
            if topic_ids:
                worksheet.topics.add(
                    *Topic.objects.filter(pk__in=topic_ids))
            if not worksheet.items.filter(task=task, deleted_at=None).exists():
                order = _ensure_import_rubrics(worksheet, headings)
                WorksheetItem.objects.create(
                    worksheet=worksheet, task=task, order=order)

        draft.imported_task = task
        draft.status = TextbookTaskDraft.STATUS_IMPORTED
        draft.save(update_fields=['imported_task', 'status'])

    leftover = batch.drafts.filter(status__in=[
        TextbookTaskDraft.STATUS_REVIEW,
        TextbookTaskDraft.STATUS_CONFLICT,
        TextbookTaskDraft.STATUS_APPROVED,
    ])
    if require_complete or not leftover.exists():
        batch.status = TextbookImportBatch.STATUS_IMPORTED
        batch.save(update_fields=['status', 'updated_at'])
    collection_count = (Collection.objects.filter(source=batch.source).count()
                        - initial_collection_count)
    return {
        'created': created,
        'reused': reused,
        'collections': max(0, collection_count),
    }

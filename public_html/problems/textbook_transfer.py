"""Перенос проверенных черновиков без повторного разбора формул и текста."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from django.contrib.auth import get_user_model
from django.core.files import File
from django.db import transaction
from django.db.models import Count
from django.utils.dateparse import parse_datetime

from problems.models import (ExamItem, GradeBand, Source, Tag, TaskBlock,
                             TextbookImportAsset, TextbookImportBatch,
                             TextbookTaskDraft, Topic)
from problems.textbook_import import (normalize_image_stem, normalize_answer_mask,
                                      TextbookImportError, TextbookImportUnavailable)

# 3 — добавлены редакторские поля и маска задачи; 1 и 2 читаются с пустыми.
SCHEMA_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, SCHEMA_VERSION)
DEFAULT_PROFILES = ('ziv', 'shestakov')
FIELDS = ('external_id', 'source_number', 'source_path', 'collection_key',
          'collection_title', 'topic_original', 'text_latex', 'subitems',
          'images', 'author_answer_latex', 'author_solution_latex',
          'answer_latex', 'solution_latex', 'answer_mask',
          'solution_source_external_id', 'warnings', 'status',
          'exam_item_codes', 'grade_band_codes', 'tags', 'block_position')
MAX_BYTES = 2 * 1024 ** 3


class TextbookTransferError(ValueError):
    pass


class TextbookTransferUnavailable(TextbookTransferError):
    """Временный отказ проверки до любых записей; перенос можно повторить."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def latest_batches(profiles=DEFAULT_PROFILES, min_drafts=1):
    found = []
    for profile in profiles:
        qs = TextbookImportBatch.objects.filter(profile=profile).select_related('source')
        if min_drafts > 1:
            qs = qs.annotate(n=Count('drafts')).filter(n__gte=min_drafts)
        batch = qs.order_by('-created_at', '-pk').first()
        if batch:
            found.append(batch)
    return found


def serialize_batch(batch):
    """Коды справочников переносимы между SQLite и MySQL; локальные PK — нет."""
    topics = {t.pk: t.code for t in Topic.objects.all()}
    def code(pk):
        if not pk:
            return ''
        if not topics.get(pk):
            raise TextbookTransferError(f'У темы {pk} нет переносимого кода.')
        return topics[pk]
    drafts, blocks = [], {}
    # Порядок книги (порядок создания): загрузка создаёт черновики в порядке
    # пакета, а строковый external_id ставил IX перед V и I.10 перед I.2.
    for draft in batch.drafts.select_related('block', 'reviewed_by').order_by('pk'):
        if draft.imported_task_id or draft.status == TextbookTaskDraft.STATUS_IMPORTED:
            raise TextbookTransferError('Перенос поддерживает черновики, а не задачи, уже загруженные в каталог.')
        row = {name: getattr(draft, name) for name in FIELDS}
        candidates = []
        for item in draft.topic_candidates:
            item = dict(item)
            item['code'] = item.get('code') or code(item.get('id'))
            item.pop('id', None)
            candidates.append(item)
        row.update(topic_code=code(draft.topic_id),
                   topic_codes=[code(pk) for pk in draft.topic_ids],
                   topic_candidates=candidates, confidence=str(draft.confidence),
                   reviewed_at=draft.reviewed_at.isoformat() if draft.reviewed_at else None,
                   reviewed_by=draft.reviewed_by.username if draft.reviewed_by_id else None,
                   block_key=draft.block.key if draft.block_id else '')
        if draft.block_id:
            blocks[draft.block.key] = {k: getattr(draft.block, k) for k in ('key', 'title', 'size')}
        drafts.append(row)
    assets = []
    for index, asset in enumerate(batch.assets.order_by('stem')):
        if not asset.file or not Path(asset.file.path).is_file():
            raise TextbookTransferError(f'Нет файла рисунка {asset.stem}.')
        path = Path(asset.file.path)
        assets.append(dict(stem=asset.stem, original_name=asset.original_name,
                           filename=f'{index:06d}{path.suffix.lower()}',
                           sha256=_sha(path), size=path.stat().st_size))
    return dict(title=batch.title, profile=batch.profile, status=batch.status,
                diagnostics=batch.diagnostics, drafts=drafts, assets=assets,
                blocks=sorted(blocks.values(), key=lambda b: b['key']),
                source={k: getattr(batch.source, k) for k in ('title', 'author', 'year')})


def export_batches(dest, *, profiles=DEFAULT_PROFILES, batches=None, min_drafts=1):
    """Каталог или один ZIP; существующий результат никогда не перезаписывается."""
    dest = Path(dest)
    if dest.exists():
        raise TextbookTransferError(f'Путь уже существует: {dest}')
    chosen = list(batches) if batches is not None else latest_batches(profiles, min_drafts)
    if not chosen:
        raise TextbookTransferError('Не найдены партии для переноса.')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as temp:
        root = Path(temp) / 'package'
        root.mkdir()
        payload = {'schema_version': SCHEMA_VERSION, 'batches': []}
        with transaction.atomic():
            for index, selected in enumerate(chosen):
                batch = TextbookImportBatch.objects.select_for_update().get(pk=selected.pk)
                row = serialize_batch(batch)
                row['key'] = f'batch-{index + 1}'
                target = root / 'assets' / row['key']
                target.mkdir(parents=True)
                for asset, info in zip(batch.assets.order_by('stem'), row['assets']):
                    shutil.copyfile(asset.file.path, target / info['filename'])
                payload['batches'].append(row)
        (root / 'batches.json').write_bytes(_canonical(payload))
        validate_package(root)
        if dest.suffix.lower() == '.zip':
            temporary_zip = Path(temp) / 'package.zip'
            with zipfile.ZipFile(temporary_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(root.rglob('*')):
                    if path.is_file():
                        archive.write(path, path.relative_to(root).as_posix())
            temporary_zip.rename(dest)
        else:
            root.rename(dest)
    return payload


def _safe_path(root, *parts):
    for part in parts:
        if not isinstance(part, str) or not part or PurePosixPath(part).name != part or '\\' in part or part in ('.', '..'):
            raise TextbookTransferError('Недопустимый путь в пакете.')
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise TextbookTransferError('Файл выходит за пределы пакета.')
    return path


@contextmanager
def package_root(src):
    src = Path(src)
    if src.suffix.lower() != '.zip':
        yield src if src.is_dir() else src.parent
        return
    with tempfile.TemporaryDirectory(prefix='textbook-transfer-') as temp:
        with zipfile.ZipFile(src) as archive:
            entries = archive.infolist()
            if len(entries) > 20000 or sum(e.file_size for e in entries) > MAX_BYTES:
                raise TextbookTransferError('Пакет превышает допустимый размер.')
            seen = set()
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename
                        or entry.filename in seen or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                    raise TextbookTransferError('Недопустимый путь или повтор файла в ZIP.')
                seen.add(entry.filename)
            archive.extractall(temp)
        yield Path(temp)


def validate_package(root):
    """Все проверки до первой записи: рисунки, справочники и полнота блоков."""
    from assignments.checks.formulas import without_worker_wait
    root = Path(root)
    manifest = root / 'batches.json'
    if not manifest.is_file() or manifest.stat().st_size > 64 * 1024 ** 2:
        raise TextbookTransferError('Нет допустимого batches.json.')
    payload = json.loads(manifest.read_text())
    if payload.get('schema_version') not in SUPPORTED_VERSIONS:
        raise TextbookTransferError('Неподдерживаемая версия пакета переноса.')
    if not payload.get('batches'):
        raise TextbookTransferError('Пакет пуст.')
    topics = set(Topic.objects.values_list('code', flat=True))
    exams = set(ExamItem.objects.values_list('code', flat=True))
    grades = set(GradeBand.objects.values_list('code', flat=True))
    for row in payload['batches']:
        if row['status'] not in ('review', 'ready'):
            raise TextbookTransferError('Переносить можно только партии черновиков.')
        stems, ids, positions = set(), set(), {}
        for asset in row.get('assets', []):
            path = _safe_path(root, 'assets', row['key'], asset['filename'])
            if not path.is_file():
                raise TextbookTransferError(f'Нет рисунка {asset["stem"]}.')
            if payload['schema_version'] >= 2 and (path.stat().st_size != asset['size'] or _sha(path) != asset['sha256']):
                raise TextbookTransferError(f'Неверная контрольная сумма рисунка {asset["stem"]}.')
            if asset['stem'] in stems:
                raise TextbookTransferError('Повтор имени рисунка.')
            stems.add(asset['stem'])
        for d in row['drafts']:
            if d['external_id'] in ids or d['status'] not in ('needs_review', 'approved', 'conflict', 'skipped'):
                raise TextbookTransferError('Повтор ключа задачи или недопустимый статус.')
            ids.add(d['external_id'])
            try:
                # Перенос не ждёт очередь вычислителя: при нагрузке можно
                # повторить команду; непроверенные эталоны не записываются.
                with without_worker_wait():
                    normalize_answer_mask(d.get('answer_mask'), key=d['external_id'])
                    for index, subitem in enumerate(d.get('subitems', []), 1):
                        normalize_answer_mask(subitem.get('answer_mask'),
                            key=f'{d["external_id"]}, подпункт {index}')
            except TextbookImportUnavailable as error:
                raise TextbookTransferUnavailable(
                    f'{error} Перенос отложен, данные не записаны.') from error
            except TextbookImportError as error:
                raise TextbookTransferError(str(error)) from error
            required = set(d.get('topic_codes', [])) | {d.get('topic_code', '')}
            required |= {c.get('code', '') for c in d.get('topic_candidates', [])}
            missing = (required - {''}) - topics
            missing |= set(d.get('exam_item_codes', [])) - exams
            missing |= set(d.get('grade_band_codes', [])) - grades
            if missing:
                raise TextbookTransferError('Нет кодов в справочниках: ' + ', '.join(sorted(missing)))
            absent = {normalize_image_stem(n) for n in d['images']} - stems
            if absent:
                raise TextbookTransferError(f'{d["external_id"]}: не сопоставлены рисунки {sorted(absent)}')
            if d.get('block_key'):
                positions.setdefault(d['block_key'], []).append(d['block_position'])
        blocks = {b['key']: b for b in row.get('blocks', [])}
        if set(blocks) != set(positions):
            raise TextbookTransferError('Не совпадают описания и вопросы блоков.')
        for key, block in blocks.items():
            if sorted(positions[key]) != list(range(1, block['size'] + 1)):
                raise TextbookTransferError(f'Неполный блок {key}.')
        if row['profile'] == 'ostromogilsky' and payload['schema_version'] >= 2:
            for d in row['drafts']:
                from .oge_metadata import apply_oge_metadata
                from types import SimpleNamespace
                copy = SimpleNamespace(**d)
                if apply_oge_metadata(copy, row['profile']):
                    raise TextbookTransferError(f'{d["external_id"]}: метки ОГЭ или теги не соответствуют номеру.')
                if int(d['external_id'].split('.')[0]) <= 5 and not d.get('block_key'):
                    raise TextbookTransferError('У практической задачи отсутствует общий блок.')
    return payload


def _resolve_owner(username=None):
    User = get_user_model()
    user = (User.objects.filter(username=username).first() if username else
            User.objects.filter(is_superuser=True).order_by('pk').first())
    from accounts.decorators import get_role
    if not user or not user.is_active or get_role(user) != 'teacher':
        raise TextbookTransferError('Владелец не найден или не является активным учителем.')
    return user


def _get_or_create_source(info):
    source = Source.objects.filter(**info).order_by('pk').first()
    return source or Source.objects.create(**info)


def import_batches(src, *, username=None, check_only=False):
    """Повтор пакета возвращает прежнюю партию; файлы откатываются при ошибке."""
    with package_root(src) as root:
        payload = validate_package(root)
        owner = _resolve_owner(username)
        if check_only:
            return payload
        created, saved_files = [], []
        try:
            with transaction.atomic():
                # Сериализует параллельные загрузки одного владельца.
                get_user_model().objects.select_for_update().get(pk=owner.pk)
                by_code = {t.code: t for t in Topic.objects.all()}
                for row in payload['batches']:
                    key = hashlib.sha256(_canonical(row)).hexdigest()
                    existing = TextbookImportBatch.objects.filter(transfer_key=key).first()
                    if existing:
                        if existing.created_by_id != owner.pk:
                            raise TextbookTransferError('Пакет уже загружен другим владельцем.')
                        expected_assets = {a['stem']: a for a in row['assets']}
                        for asset in existing.assets.all():
                            expected = expected_assets.get(asset.stem)
                            if not expected or not asset.file or not Path(asset.file.path).is_file() or (expected.get('sha256') and _sha(asset.file.path) != expected['sha256']):
                                raise TextbookTransferError('Рисунки прежнего переноса изменены или отсутствуют.')
                        if existing.assets.count() != len(row['assets']):
                            raise TextbookTransferError('В прежнем переносе потеряны рисунки.')
                        created.append(existing)
                        continue
                    source = _get_or_create_source(row['source'])
                    batch = TextbookImportBatch.objects.create(
                        title=row['title'], profile=row['profile'], status=row['status'],
                        source=source, created_by=owner, diagnostics=row['diagnostics'], transfer_key=key)
                    blocks = {}
                    for info in row.get('blocks', []):
                        block, _ = TaskBlock.objects.get_or_create(source=source, key=info['key'],
                            defaults={'title': info['title'], 'size': info['size']})
                        if block.title != info['title'] or block.size != info['size']:
                            raise TextbookTransferError('Общий блок конфликтует с существующими данными.')
                        blocks[info['key']] = block
                    drafts = []
                    for d in row['drafts']:
                        fields = {k: d[k] for k in FIELDS if k in d}
                        candidates = [dict(c, id=by_code[c['code']].pk) if c.get('code') else dict(c)
                                      for c in d.get('topic_candidates', [])]
                        reviewer = (owner if payload['schema_version'] == 1 and d.get('status') != 'needs_review' else None)
                        if d.get('reviewed_by'):
                            reviewer = get_user_model().objects.filter(username=d['reviewed_by']).first() or owner
                        drafts.append(TextbookTaskDraft(batch=batch, **fields,
                            topic=by_code.get(d.get('topic_code')),
                            topic_ids=[by_code[c].pk for c in d.get('topic_codes', [])],
                            topic_candidates=candidates, confidence=d['confidence'],
                            block=blocks.get(d.get('block_key')),
                            reviewed_by=reviewer,
                            reviewed_at=parse_datetime(d['reviewed_at']) if d.get('reviewed_at') else None))
                    TextbookTaskDraft.objects.bulk_create(drafts, batch_size=500)
                    for name in {tag for d in row['drafts'] for tag in d.get('tags', [])}:
                        Tag.objects.get_or_create(name=name)
                    for asset in row['assets']:
                        path = _safe_path(root, 'assets', row['key'], asset['filename'])
                        obj = TextbookImportAsset(batch=batch, stem=asset['stem'], original_name=asset['original_name'])
                        with path.open('rb') as stream:
                            obj.file.save(asset['filename'], File(stream), save=False)
                        saved_files.append((obj.file.storage, obj.file.name))
                        obj.save()
                        if asset.get('sha256') and _sha(obj.file.path) != asset['sha256']:
                            raise TextbookTransferError('Контрольная сумма записанного рисунка не совпала.')
                    if payload['schema_version'] >= 2:
                        verify_batch(batch, row)
                    created.append(batch)
        except Exception:
            for storage, name in saved_files:
                storage.delete(name)
            raise
        return created


def verify_batch(batch, expected):
    """Побайтовая сверка текста и рисунков после записи; PK и владелец переносимы."""
    actual = serialize_batch(batch)
    for field in ('title', 'profile', 'status', 'diagnostics', 'source', 'blocks'):
        if field in expected and actual[field] != expected[field]:
            raise TextbookTransferError(f'После записи изменилось поле {field}.')
    actual_drafts = {d['external_id']: d for d in actual['drafts']}
    if len(actual_drafts) != len(expected['drafts']):
        raise TextbookTransferError('После записи изменилось число черновиков.')
    for draft in expected['drafts']:
        stored = actual_drafts.get(draft['external_id'], {})
        for field, value in draft.items():
            # Имя проверявшего может отсутствовать на принимающем сервере.
            if field != 'reviewed_by' and stored.get(field) != value:
                raise TextbookTransferError(f'{draft["external_id"]}: после записи изменилось поле {field}.')
    actual_assets = {a['stem']: a for a in actual['assets']}
    if len(actual_assets) != len(expected['assets']):
        raise TextbookTransferError('После записи изменилось число рисунков.')
    for asset in expected['assets']:
        stored = actual_assets.get(asset['stem'], {})
        for field in ('original_name', 'size', 'sha256'):
            if field in asset and stored.get(field) != asset[field]:
                raise TextbookTransferError(f'{asset["stem"]}: после записи изменилось поле {field}.')

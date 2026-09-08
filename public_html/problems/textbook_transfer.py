"""Перенос партий импорта задачников между базами (SQLite → MySQL).

Темы хранятся кодами, не PK. Авторы черновиков на приёме заменяются
указанным пользователем. Связь imported_task не переносится.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count

from problems.models import (Source, TextbookImportAsset, TextbookImportBatch,
                             TextbookTaskDraft, Topic)

SCHEMA_VERSION = 1
DEFAULT_PROFILES = ('ziv', 'shestakov')


class TextbookTransferError(ValueError):
    pass


def _topic_code(topic):
    return (topic.code or '') if topic is not None else ''


def _topic_by_code():
    return {
        topic.code: topic
        for topic in Topic.objects.exclude(code__isnull=True).exclude(code='')
    }


def _remap_topic_ids(codes, by_code):
    return [by_code[code].pk for code in codes if code in by_code]


def _remap_candidates(candidates, by_code):
    remapped = []
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        code = item.get('code') or ''
        topic = by_code.get(code)
        row = dict(item)
        if topic is not None:
            row['id'] = topic.pk
            row['code'] = topic.code
            row['name'] = str(topic)
        remapped.append(row)
    return remapped


def latest_batches(profiles=DEFAULT_PROFILES, min_drafts=1):
    """По одной самой свежей партии на профиль."""
    found = []
    for profile in profiles:
        qs = (TextbookImportBatch.objects
              .filter(profile=profile)
              .select_related('source', 'created_by'))
        if min_drafts > 1:
            qs = qs.annotate(n=Count('drafts')).filter(n__gte=min_drafts)
        batch = qs.order_by('-created_at', '-pk').first()
        if batch is not None:
            found.append(batch)
    return found


def serialize_batch(batch):
    source = batch.source
    drafts = []
    for draft in batch.drafts.all().select_related('topic'):
        topic_codes = []
        if draft.topic_ids:
            topics = Topic.objects.filter(pk__in=draft.topic_ids)
            by_pk = {topic.pk: topic for topic in topics}
            for pk in draft.topic_ids:
                topic = by_pk.get(pk)
                if topic is not None and topic.code:
                    topic_codes.append(topic.code)
        elif draft.topic_id and draft.topic and draft.topic.code:
            topic_codes = [draft.topic.code]
        drafts.append({
            'external_id': draft.external_id,
            'source_number': draft.source_number,
            'source_path': draft.source_path,
            'collection_key': draft.collection_key,
            'collection_title': draft.collection_title,
            'topic_original': draft.topic_original,
            'topic_code': _topic_code(draft.topic),
            'topic_codes': topic_codes,
            'text_latex': draft.text_latex,
            'subitems': draft.subitems,
            'images': draft.images,
            'topic_candidates': draft.topic_candidates,
            'author_answer_latex': draft.author_answer_latex,
            'author_solution_latex': draft.author_solution_latex,
            'solution_source_external_id': draft.solution_source_external_id,
            'confidence': str(draft.confidence),
            'warnings': draft.warnings,
            'status': draft.status,
        })
    assets = []
    for asset in batch.assets.all():
        assets.append({
            'stem': asset.stem,
            'original_name': asset.original_name,
            'filename': Path(asset.file.name).name if asset.file else '',
        })
    return {
        'title': batch.title,
        'profile': batch.profile,
        'status': batch.status,
        'diagnostics': batch.diagnostics,
        'source': {
            'title': source.title,
            'author': source.author,
            'year': source.year,
        },
        'drafts': drafts,
        'assets': assets,
    }


def export_batches(dest, *, profiles=DEFAULT_PROFILES, batches=None,
                   min_drafts=1):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    assets_root = dest / 'assets'
    chosen = list(batches) if batches is not None else latest_batches(
        profiles, min_drafts=min_drafts)
    payload = {
        'schema_version': SCHEMA_VERSION,
        'batches': [],
    }
    for index, batch in enumerate(chosen):
        key = f'{batch.profile}-{index + 1}'
        row = serialize_batch(batch)
        row['key'] = key
        batch_dir = assets_root / key
        for asset in batch.assets.all():
            if not asset.file:
                continue
            batch_dir.mkdir(parents=True, exist_ok=True)
            src = Path(asset.file.path)
            if src.is_file():
                shutil.copy2(src, batch_dir / Path(asset.file.name).name)
        payload['batches'].append(row)
    (dest / 'batches.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def _resolve_owner(username=None):
    User = get_user_model()
    if username:
        user = User.objects.filter(username=username).first()
        if user is None:
            raise TextbookTransferError(
                f'Пользователь {username} не найден.')
        return user
    user = User.objects.filter(is_superuser=True).order_by('pk').first()
    if user is None:
        raise TextbookTransferError(
            'Нет суперпользователя: создайте его до импорта.')
    return user


def _get_or_create_source(info):
    lookup = {
        'title': (info or {}).get('title') or '',
        'author': (info or {}).get('author') or '',
        'year': (info or {}).get('year'),
    }
    source = Source.objects.filter(**lookup).order_by('pk').first()
    if source is None:
        source = Source.objects.create(**lookup)
    return source


@transaction.atomic
def import_batches(src, *, username=None):
    src = Path(src)
    payload_path = src / 'batches.json' if src.is_dir() else src
    if not payload_path.is_file():
        raise TextbookTransferError(f'Нет файла {payload_path}')
    payload = json.loads(payload_path.read_text(encoding='utf-8'))
    if payload.get('schema_version') != SCHEMA_VERSION:
        raise TextbookTransferError('Ожидается schema_version=1.')
    owner = _resolve_owner(username)
    by_code = _topic_by_code()
    root = payload_path.parent
    created = []
    for row in payload.get('batches') or []:
        source = _get_or_create_source(row.get('source'))
        batch = TextbookImportBatch.objects.create(
            title=row.get('title') or '',
            profile=row.get('profile') or '',
            source=source,
            created_by=owner,
            status=row.get('status') or TextbookImportBatch.STATUS_REVIEW,
            diagnostics=row.get('diagnostics') or {},
        )
        for draft in row.get('drafts') or []:
            codes = list(draft.get('topic_codes') or [])
            primary = draft.get('topic_code') or (codes[0] if codes else '')
            topic = by_code.get(primary)
            TextbookTaskDraft.objects.create(
                batch=batch,
                external_id=draft.get('external_id') or '',
                source_number=draft.get('source_number') or '',
                source_path=draft.get('source_path') or [],
                collection_key=draft.get('collection_key') or '',
                collection_title=draft.get('collection_title') or '',
                topic_original=draft.get('topic_original') or '',
                topic=topic,
                topic_ids=_remap_topic_ids(codes, by_code),
                text_latex=draft.get('text_latex') or '',
                subitems=draft.get('subitems') or [],
                images=draft.get('images') or [],
                topic_candidates=_remap_candidates(
                    draft.get('topic_candidates'), by_code),
                author_answer_latex=draft.get('author_answer_latex') or '',
                author_solution_latex=draft.get('author_solution_latex') or '',
                solution_source_external_id=draft.get(
                    'solution_source_external_id') or '',
                confidence=draft.get('confidence') or 0,
                warnings=draft.get('warnings') or [],
                status=draft.get('status') or TextbookTaskDraft.STATUS_REVIEW,
                imported_task=None,
                reviewed_by=owner if draft.get('status') not in (
                    '', TextbookTaskDraft.STATUS_REVIEW, None) else None,
            )
        key = row.get('key') or ''
        for asset in row.get('assets') or []:
            filename = asset.get('filename') or ''
            path = root / 'assets' / key / filename if key and filename else None
            if path is None or not path.is_file():
                continue
            obj = TextbookImportAsset(
                batch=batch,
                stem=asset.get('stem') or '',
                original_name=asset.get('original_name') or filename,
            )
            obj.file.save(filename, ContentFile(path.read_bytes()), save=True)
        created.append(batch)
    return created

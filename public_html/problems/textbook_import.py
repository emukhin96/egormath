"""Безопасная загрузка проверяемого JSON парсера задачников.

Первый этап создаёт только черновики. Второй, после ручного одобрения,
идемпотентно создаёт задачи и backing-worksheet подборок. Рабочие поля
answer_latex/solution_latex не меняются: ими продолжает владеть редакторский
и AI-контур.
"""

import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.utils.text import slugify

from .models import (Source, Task, TaskSource, TaskSubitem, TextbookImportBatch,
                     TextbookTaskDraft)
from .rubricator import set_task_topics


MAX_BUNDLE_TASKS = 10000


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
        text = _required_string(item, 'text_latex')
        result.append({
            'label': str(item.get('label') or index)[:16],
            'text_latex': text,
            'author_answer_latex': str(
                item.get('author_answer_latex') or '').strip(),
            'author_solution_latex': str(
                item.get('author_solution_latex') or '').strip(),
        })
    return result


def _confidence(value):
    try:
        number = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        number = Decimal('0')
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
        # Парсер не может сам одобрить строку: решение принимает человек.
        if status == TextbookTaskDraft.STATUS_APPROVED:
            status = TextbookTaskDraft.STATUS_REVIEW
        path = _string_list(row.get('source_path'), 'source_path')
        warnings = _string_list(row.get('warnings'), 'warnings')
        drafts.append(TextbookTaskDraft(
            batch=batch,
            external_id=external_id,
            source_number=_required_string(
                row, 'source_number', allow_blank=True, limit=190)
                or external_id,
            source_path=path,
            collection_key=str(row.get('collection_key') or '')[:500],
            collection_title=str(row.get('collection_title') or '')[:190],
            topic_original=str(row.get('topic_original') or '')[:255],
            text_latex=_required_string(row, 'text_latex'),
            subitems=normalize_subitems(row.get('subitems')),
            author_answer_latex=str(
                row.get('author_answer_latex') or '').strip(),
            author_solution_latex=str(
                row.get('author_solution_latex') or '').strip(),
            solution_source_external_id=(
                external_id if (row.get('author_answer_latex')
                                or row.get('author_solution_latex')) else ''),
            confidence=_confidence(row.get('confidence')),
            warnings=warnings,
            status=status,
        ))
    TextbookTaskDraft.objects.bulk_create(drafts, batch_size=500)
    return batch


def read_bundle(upload, max_bytes=50 * 1024 * 1024):
    raw = upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise TextbookImportError('Файл import.json больше 50 МБ.')
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TextbookImportError(f'Некорректный UTF-8 JSON: {exc}') from exc


def _collection_locator(path):
    raw = json.dumps(path, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]
    prefix = slugify(path[-1], allow_unicode=False)[:60] if path else 'root'
    return f'{prefix or "section"}-{digest}'


def _collection_for_path(batch, path, cache):
    from worksheets.models import Collection, Worksheet

    parent = None
    for depth in range(1, len(path) + 1):
        prefix = path[:depth]
        locator = _collection_locator(prefix)
        if locator in cache:
            parent = cache[locator]
            continue
        collection = (Collection.objects
                      .select_related('worksheet')
                      .filter(source=batch.source, locator=locator)
                      .first())
        if collection is None:
            worksheet = Worksheet.objects.create(
                title=prefix[-1][:190], owner=batch.created_by)
            collection = Collection.objects.create(
                worksheet=worksheet, source=batch.source, parent=parent,
                locator=locator, source_path=prefix, order=depth * 10,
                is_published=True)
        elif not collection.is_published:
            collection.is_published = True
            collection.save(update_fields=['is_published'])
        cache[locator] = collection
        parent = collection
    return parent


def _merge_author_fields(task, draft):
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


@transaction.atomic
def commit_batch(batch, *, user):
    """Загружает полностью проверенную партию; повторный вызов безопасен."""
    from worksheets.models import WorksheetItem

    batch = (TextbookImportBatch.objects.select_for_update()
             .select_related('source', 'created_by').get(pk=batch.pk))
    if batch.created_by_id != user.pk and not user.is_superuser:
        raise TextbookImportError('Эту партию может загрузить только редактор.')
    if batch.status == TextbookImportBatch.STATUS_IMPORTED:
        return {'created': 0, 'reused': 0, 'collections': 0}
    blockers = batch.drafts.filter(status__in=[
        TextbookTaskDraft.STATUS_REVIEW,
        TextbookTaskDraft.STATUS_CONFLICT,
    ]).count()
    if blockers:
        raise TextbookImportError(
            f'Осталось непроверенных или конфликтных строк: {blockers}.')
    missing_topics = batch.drafts.filter(
        status=TextbookTaskDraft.STATUS_APPROVED, topic__isnull=True).count()
    if missing_topics:
        raise TextbookImportError(
            f'У одобренных задач не выбрана тема рубрикатора: '
            f'{missing_topics}.')

    created = 0
    reused = 0
    collection_cache = {}
    from worksheets.models import Collection
    initial_collection_count = Collection.objects.filter(
        source=batch.source).count()

    for draft in batch.drafts.filter(
            status=TextbookTaskDraft.STATUS_APPROVED).select_related('topic'):
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
                author_answer_latex=draft.author_answer_latex,
                author_solution_latex=draft.author_solution_latex,
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

        _merge_author_fields(task, draft)
        if draft.topic_id:
            if task.topic_links.exists():
                task.topics.add(draft.topic)
            else:
                set_task_topics(task, [draft.topic_id], draft.topic_id)

        path = [str(x).strip() for x in draft.source_path if str(x).strip()]
        if not path:
            path = [draft.collection_title.strip() or batch.title]
        collection = _collection_for_path(batch, path, collection_cache)
        if collection:
            worksheet = collection.worksheet
            if draft.topic_id:
                worksheet.topics.add(draft.topic)
            if not worksheet.items.filter(task=task, deleted_at=None).exists():
                order = (worksheet.items.aggregate(
                    max_order=Max('order'))['max_order'] or 0) + 10
                WorksheetItem.objects.create(
                    worksheet=worksheet, task=task, order=order)

        draft.imported_task = task
        draft.save(update_fields=['imported_task'])

    batch.status = TextbookImportBatch.STATUS_IMPORTED
    batch.save(update_fields=['status', 'updated_at'])
    collection_count = (Collection.objects.filter(source=batch.source).count()
                        - initial_collection_count)
    return {
        'created': created,
        'reused': reused,
        'collections': max(0, collection_count),
    }

"""Дерево каталога подборок: источники → разделы → подборки с числом задач
и темами.

Раньше ``_collection_catalog`` в views на каждый запрос списка и карточки
подборки загружал все подборки целиком — с полными строками листков
(тексты, настройки PDF) и родителей: 3 000 подборок давали один запрос
на 0,3 с и ещё 0,3 с на распаковку (аудит быстродействия 06.11.2026).
Здесь:

* дерево строится из узких ``values()`` без зависящих от пользователя
  полей — ``CatalogNode`` с названием, счётчиком и темами — и лежит в
  файловом кэше ``taxonomy`` (общем для воркеров) одной записью;
* видимость подборок и обрезка пустых ветвей считаются для каждого
  учителя уже в Python по кэшированным узлам;
* сохранение подборки, листка-содержимого, его элементов или тем
  сбрасывает кэш (``connect_collection_catalog_signals``). ``TIMEOUT``
  кэша — 6 часов, это страховка, а не механизм обновления: массовая
  запись мимо сигналов (``bulk_create``, ``QuerySet.update()`` — как в
  ``soft_remove_item``) обязана сама вызвать
  ``invalidate_collection_catalog``; после заливки дампа или правок прямо
  в MySQL — ``manage.py clear_catalog_cache``;
* внутри транзакции (тесты, ``transaction.atomic``) кэш не читается и не
  пишется — как у каталога рубрикатора.
"""
import hashlib
import re
from dataclasses import dataclass, field

from django.core.cache import caches
from django.db import connection, connections, transaction
from django.db.models import Count

from problems.models import Source, Topic

from .models import Collection, Worksheet, WorksheetItem

CACHE_ALIAS = 'taxonomy'
CACHE_KEY = 'collection-catalog'


# --- названия ----------------------------------------------------------------

def catalog_title(title):
    """Короткое название каталога с двузначным номером задания."""
    title = title.strip()
    title = re.sub(
        r'^№\s*1[–-]5\.\s*Практические\s+(?:задачи|задания)\s*:\s*',
        '№01–05. ', title, flags=re.IGNORECASE)
    title = re.sub(
        r'^№\s*1[–-]5\.\s*Практические\s+(?:задачи|задания)\s*$',
        '№01–05', title, flags=re.IGNORECASE)
    match = re.match(r'^№\s*([1-9])([.\s])', title)
    if match:
        title = f'№0{match.group(1)}{match.group(2)}{title[match.end():]}'
    return title


def natural_key(text):
    """Числа в названии сравниваются как числа: «прототип 1.2» раньше
    «прототип 1.10», а не после «1.19», как при строковом сравнении."""
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', text) if part)


def sort_key(collection):
    """Порядок соседей: номер задания, ``order``, естественный порядок
    названия, pk. Подходит и узлу дерева, и ``Collection`` с заранее
    выставленным ``catalog_title``."""
    title = getattr(collection, 'catalog_title', None)
    if title is None:
        title = catalog_title(collection.worksheet.title)
    match = re.match(r'^№\s*(\d+)', title)
    return (int(match.group(1)) if match else 10_000,
            collection.order, natural_key(title), collection.pk)


# --- узлы и кэш --------------------------------------------------------------

@dataclass
class CatalogNode:
    """Подборка в дереве: только то, что нужно панели и списку."""
    pk: int
    parent_id: int
    source_id: int
    order: int
    is_published: bool
    owner_id: int
    catalog_title: str
    direct_items_total: int = 0
    topic_ids: list = field(default_factory=list)


def build_catalog_nodes():
    """Узлы всех подборок, темы и источники — без учёта пользователя."""
    rows = list(Collection.objects.values(
        'pk', 'parent_id', 'source_id', 'order', 'is_published',
        'worksheet_id', 'worksheet__title', 'worksheet__owner_id'))
    worksheet_ids = {row['worksheet_id'] for row in rows}
    counts = dict(
        WorksheetItem.objects.filter(deleted_at__isnull=True,
                                     worksheet_id__in=worksheet_ids)
        .values_list('worksheet_id').annotate(n=Count('pk'))
        .values_list('worksheet_id', 'n'))
    topic_ids_by_worksheet = {}
    for worksheet_id, topic_id in (Worksheet.topics.through.objects
                                   .filter(worksheet_id__in=worksheet_ids)
                                   .values_list('worksheet_id', 'topic_id')):
        topic_ids_by_worksheet.setdefault(worksheet_id, []).append(topic_id)
    used_topics = {t for ids in topic_ids_by_worksheet.values() for t in ids}
    topics = {t.pk: t for t in Topic.objects.filter(pk__in=used_topics)}
    # Источники — в порядке БД по названию (сравнение без учёта регистра,
    # как и раньше в ORDER BY source__title), а не по кодам символов
    source_order = {}
    sources = {}
    for source in Source.objects.filter(
            pk__in={row['source_id'] for row in rows}).order_by('title', 'pk'):
        source_order[source.pk] = len(source_order)
        sources[source.pk] = source
    nodes = [CatalogNode(
        pk=row['pk'], parent_id=row['parent_id'], source_id=row['source_id'],
        order=row['order'], is_published=row['is_published'],
        owner_id=row['worksheet__owner_id'],
        catalog_title=catalog_title(row['worksheet__title']),
        direct_items_total=counts.get(row['worksheet_id'], 0),
        topic_ids=topic_ids_by_worksheet.get(row['worksheet_id'], []),
    ) for row in rows]
    nodes.sort(key=lambda n: (source_order[n.source_id], n.order, n.pk))
    return {'nodes': nodes, 'topics': topics, 'sources': sources}


def _cache_key(using):
    database = str(connections[using].settings_dict.get('NAME', ''))
    return f'{CACHE_KEY}:{hashlib.sha256(database.encode()).hexdigest()[:12]}'


def catalog_nodes():
    """Узлы из общего кэша; в транзакции — всегда заново."""
    if connection.in_atomic_block:
        return build_catalog_nodes()
    cache = caches[CACHE_ALIAS]
    key = _cache_key(connection.alias)
    try:
        data = cache.get(key)
    except OSError:
        data = None
    if data is None:
        data = build_catalog_nodes()
        try:
            cache.set(key, data)
        except OSError:
            pass
    return data


def invalidate_collection_catalog(*, using=None):
    """Удалить дерево из кэша после успешной транзакции."""
    using = using or 'default'

    def drop():
        try:
            caches[CACHE_ALIAS].delete(_cache_key(using))
        except OSError:
            pass
    transaction.on_commit(drop, using=using)


# --- дерево для пользователя -------------------------------------------------

def collection_catalog(user):
    """Доступное учителю дерево без ветвей, в которых нет ни одной задачи:
    ``[{'source', 'roots', 'rows', 'item_total', 'leaf_total', 'topics'}, …]``.
    Строка дерева — ``{'collection': узел, 'depth', 'children',
    'direct_items_total', 'item_total', 'leaf_total', 'topics'}``."""
    data = catalog_nodes()
    topics_by_id = data['topics']
    ids = {node.pk for node in data['nodes']}
    by_source = {}
    for node in data['nodes']:
        node.catalog_visible = (
            user.is_superuser or node.is_published or node.owner_id == user.pk)
        by_source.setdefault(node.source_id, []).append(node)

    def topic_sort(topic):
        return (topic.order, topic.name)

    result = []
    for source_id, nodes in by_source.items():
        by_parent = {}
        for node in nodes:
            parent_id = node.parent_id if node.parent_id in ids else None
            by_parent.setdefault(parent_id, []).append(node)
        for siblings in by_parent.values():
            siblings.sort(key=sort_key)

        def walk(node, depth=0):
            children = [row for child in by_parent.get(node.pk, [])
                        if (row := walk(child, depth + 1))]
            direct_items_total = node.direct_items_total if node.catalog_visible else 0
            topics = ({pk: topics_by_id[pk] for pk in node.topic_ids if pk in topics_by_id}
                      if node.catalog_visible else {})
            for child in children:
                topics.update({topic.pk: topic for topic in child['topics']})
            item_total = direct_items_total + sum(child['item_total'] for child in children)
            if not item_total:
                return None
            return {
                'collection': node,
                'depth': depth,
                'children': children,
                'direct_items_total': direct_items_total,
                'item_total': item_total,
                'leaf_total': ((1 if direct_items_total else 0)
                               + sum(child['leaf_total'] for child in children)),
                'topics': sorted(topics.values(), key=topic_sort),
            }

        roots = [row for root in by_parent.get(None, []) if (row := walk(root))]

        def flatten(rows):
            return [item for row in rows for item in [row, *flatten(row['children'])]]

        flat_rows = flatten(roots)
        if not flat_rows:
            continue
        result.append({
            'source': data['sources'][source_id],
            'roots': roots,
            'rows': flat_rows,
            'item_total': sum(row['item_total'] for row in roots),
            'leaf_total': sum(row['leaf_total'] for row in roots),
            'topics': sorted(
                {topic.pk: topic for row in roots for topic in row['topics']}.values(),
                key=topic_sort),
        })
    return result


# --- сигналы -----------------------------------------------------------------

def _is_collection_worksheet(worksheet_id):
    return Collection.objects.filter(worksheet_id=worksheet_id).exists()


def _on_collection_changed(sender, instance, using=None, **kwargs):
    invalidate_collection_catalog(using=using)


def _on_worksheet_changed(sender, instance, using=None, **kwargs):
    # Листки учителей сохраняются постоянно; дерево трогают только листки подборок
    if _is_collection_worksheet(instance.pk):
        invalidate_collection_catalog(using=using)


def _on_item_changed(sender, instance, using=None, **kwargs):
    if _is_collection_worksheet(instance.worksheet_id):
        invalidate_collection_catalog(using=using)


def _on_topics_changed(sender, instance, using=None, **kwargs):
    if isinstance(instance, Worksheet) and _is_collection_worksheet(instance.pk):
        invalidate_collection_catalog(using=using)


def connect_collection_catalog_signals():
    """Подборка, её листок, элементы листка и темы — всё, от чего зависит
    дерево; источники и темы лежат в кэше объектами, поэтому их
    переименование и порядок тоже сбрасывают кэш (ревью #319). Массовый
    ``update()`` элементов сигналов не шлёт — такие места
    (``soft_remove_item``) зовут ``invalidate_collection_catalog`` сами."""
    from django.db.models.signals import m2m_changed, post_delete, post_save

    for model, handler in ((Collection, _on_collection_changed),
                           (Source, _on_collection_changed),
                           (Topic, _on_collection_changed),
                           (Worksheet, _on_worksheet_changed),
                           (WorksheetItem, _on_item_changed)):
        label = model._meta.label_lower
        post_save.connect(handler, sender=model,
                          dispatch_uid=f'worksheets.invalidate_collection_catalog.save.{label}')
        post_delete.connect(handler, sender=model,
                            dispatch_uid=f'worksheets.invalidate_collection_catalog.delete.{label}')
    m2m_changed.connect(_on_topics_changed, sender=Worksheet.topics.through,
                        dispatch_uid='worksheets.invalidate_collection_catalog.topics')

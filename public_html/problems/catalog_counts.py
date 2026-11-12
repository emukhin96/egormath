"""Счётчики панели каталога задач: разделы рубрикатора, классы, источники.

Числа одни и те же для всех страниц каталога одного учителя, но считались
заново на каждый запрос, причём каждый раздел — отдельным
``COUNT(DISTINCT …)`` по всем полям задачи (аудит быстродействия
06.11.2026: до 0,9 с на запрос). Здесь:

* число задач раздела — ``COUNT`` с ``EXISTS`` по связям тема–задача,
  без join и DISTINCT;
* результаты лежат в кэше ``catalog`` (файловый, общий для воркеров)
  по ключу «база, учитель, режим каталога, открытый раздел»; правка
  задачи, её тем, классов или источников сбрасывает их сразу
  (``invalidate_catalog_counts``, по сигналам из
  ``connect_catalog_counts_signals``). ``TIMEOUT`` кэша — 6 часов, это
  страховка, а не механизм обновления: любая массовая запись мимо
  сигналов (``bulk_create``, ``QuerySet.update()`` задач, тем, связей,
  элементов листков) обязана сама вызвать ``invalidate_catalog_counts``;
  после заливки дампа или правок прямо в MySQL — ``manage.py
  clear_catalog_cache``.
* внутри транзакции (тесты, ``transaction.atomic``) кэш не читается и не
  пишется — как у каталога рубрикатора.
"""
import hashlib
import uuid

from django.core.cache import caches
from django.db import connection, connections, transaction
from django.db.models import Count, Exists, OuterRef, Q

from accounts.permissions import (catalog_tasks, is_base_editor,
                                  shows_foreign_tasks)

from .content_data import CONTENT_FACET_CODE
from .models import FacetValue, Source, Task, TaskSource, TaskTopic, Topic
from .rubricator import (GRADE_LEVEL_TO_CODE, content_choices,
                         parse_grade_choice)

CACHE_ALIAS = 'catalog'
VERSION_KEY = 'catalog-counts:version'
SOURCE_LIMIT = 12


# --- кэш ---------------------------------------------------------------------

def _cache():
    return caches[CACHE_ALIAS]


def _version_key(using, user_pk=None):
    return f'{VERSION_KEY}:{using}' + (f':u{user_pk}' if user_pk else '')


def _version(using, user_pk=None):
    """Метка поколения счётчиков — общая и отдельная для учителя: сброс —
    новая метка, старые записи остаются до истечения TIMEOUT и больше не
    читаются."""
    key = _version_key(using, user_pk)
    try:
        version = _cache().get(key)
        if version is None:
            version = uuid.uuid4().hex
            _cache().set(key, version, None)
    except OSError:
        return None
    return version


def invalidate_catalog_counts(*, using=None, user_pk=None):
    """Сбросить счётчики после успешной транзакции: всем (правка задач,
    тем, источников) или одному учителю (изменился состав его листков —
    у приглашённого от него зависит база каталога, ревью #318)."""
    using = using or 'default'

    def bump():
        try:
            _cache().set(_version_key(using, user_pk), uuid.uuid4().hex, None)
        except OSError:
            pass
    transaction.on_commit(bump, using=using)


def _mode(user):
    """Режим каталога: редактор с тумблером или учитель. Входит в ключ,
    потому что от него зависит база ``catalog_tasks``."""
    if is_base_editor(user):
        return 'editor-all' if shows_foreign_tasks(user) else 'editor'
    return 'teacher'


def _key(user, suffix):
    using = connection.alias
    database = str(connections[using].settings_dict.get('NAME', ''))
    digest = hashlib.sha256(database.encode()).hexdigest()[:12]
    version = _version(using)
    own = _version(using, user.pk)
    if version is None or own is None:
        return None
    return f'catalog-counts:{digest}:{version}-{own}:{user.pk}:{_mode(user)}:{suffix}'


def _cached(user, suffix, build):
    """Значение из кэша или ``build()``; в транзакции — всегда ``build()``."""
    if connection.in_atomic_block:
        return build()
    key = _key(user, suffix)
    if key is None:
        return build()
    try:
        value = _cache().get(key)
    except OSError:
        value = None
    if value is None:
        value = build()
        try:
            _cache().set(key, value)
        except OSError:
            pass
    return value


# --- разделы рубрикатора -----------------------------------------------------

def subtree_count(catalog, topic_ids):
    """Число задач каталога хотя бы с одной темой из ``topic_ids``: задача
    с двумя темами одного раздела считается один раз без DISTINCT."""
    links = TaskTopic.objects.filter(task_id=OuterRef('pk'), topic_id__in=topic_ids)
    return catalog.filter(Exists(links)).count()


def section_counts(user, blocks, active_root=None):
    """``{id темы: число задач}`` для корневых разделов и, если открыт
    раздел ``active_root``, его подтем первого уровня."""
    def build():
        catalog = catalog_tasks(user)
        counts = {}
        for block in blocks:
            counts[block.pk] = subtree_count(catalog, block.subtree_ids)
            if active_root is not None and block.pk == active_root.pk:
                for child in block.children_topics:
                    counts[child.pk] = subtree_count(catalog, child.subtree_ids)
        return counts
    suffix = f'sections:{active_root.pk if active_root is not None else 0}'
    return _cached(user, suffix, build)


def catalog_total(user):
    """Число задач каталога учителя (счётчик в кабинете): тот же кэш и те
    же метки поколения, что у разделов и фасетов — полный COUNT по 30 тыс.
    задач не выполняется на каждое открытие кабинета."""
    return _cached(user, 'total', lambda: catalog_tasks(user).count())


# --- классы и источники ------------------------------------------------------

def grade_counts(user):
    """``{класс: число задач}`` по тому же условию, что фильтр ``?grade=N``
    (полоса классов ИЛИ старое поле grade_level)."""
    def build():
        catalog = catalog_tasks(user)
        levels_of = {level: [10, 11] if level == 10 else [level]
                     for level in GRADE_LEVEL_TO_CODE if level != 11}
        counts = catalog.aggregate(**{
            f'g{level}': Count('id', distinct=True, filter=(
                Q(grade_bands__code=GRADE_LEVEL_TO_CODE[level]) | Q(grade_level__in=levels)))
            for level, levels in levels_of.items()})
        return {level: counts[f'g{level}'] for level in levels_of}
    return _cached(user, 'grades', build)


def source_rows(user):
    """Источники каталога с числом задач, не больше ``SOURCE_LIMIT``."""
    def build():
        catalog = catalog_tasks(user)
        return [
            {'pk': row['source_id'], 'title': row['source__title'],
             'short': row['source__short_title'] or row['source__title'], 'count': row['n']}
            for row in (TaskSource.objects.filter(task__in=catalog.values('pk'))
                        .values('source_id', 'source__title', 'source__short_title')
                        .annotate(n=Count('task_id', distinct=True))
                        .order_by('-n', 'source__title')[:SOURCE_LIMIT])]
    return _cached(user, 'sources', build)


def catalog_facets(params, user):
    """Классы и источники для панели каталога — с числом задач и текущим
    выбором (``?grade``, ``?source``)."""
    labels = dict(Task.GRADE_CHOICES)
    current_grade, _ = parse_grade_choice(params.get('grade'))
    grades = []
    for level, count in sorted(grade_counts(user).items()):
        if count:
            grades.append({'value': level, 'label': labels.get(level, str(level)),
                           'count': count, 'is_current': current_grade == level})
    current_source = (params.get('source') or '').strip()
    sources = [dict(row, is_current=current_source == str(row['pk']))
               for row in source_rows(user)]
    return grades, sources


# --- содержание (фасет CONTENT) ----------------------------------------------

def content_counts(user):
    """``{id значения или группы: число задач}`` по фасету CONTENT: два
    запроса по связке задача–значение; задача с двумя значениями одной
    группы в группе считается один раз."""
    def build():
        through = Task.facet_values.through
        links = through.objects.filter(
            task__in=catalog_tasks(user).values('pk'),
            facetvalue__facet_type__code=CONTENT_FACET_CODE)
        counts = dict(links.values_list('facetvalue_id')
                      .annotate(n=Count('task_id')).values_list('facetvalue_id', 'n'))
        counts.update(links.values_list('facetvalue__parent_id')
                      .annotate(n=Count('task_id', distinct=True))
                      .values_list('facetvalue__parent_id', 'n'))
        counts.pop(None, None)
        return counts
    return _cached(user, 'content', build)


def catalog_content(params, user):
    """Группы «Содержания» для панели каталога: число задач, текущий выбор
    (``?content=КОД``); у группы с выбором раскрываются значения."""
    current = (params.get('content') or '').strip()
    counts = content_counts(user)
    groups = []
    for group in content_choices():
        total = counts.get(group['id'], 0)
        if not total:
            continue
        codes = {v['code'] for v in group['values']}
        values = []
        if current == group['code'] or current in codes:
            values = [dict(v, count=counts.get(v['id'], 0),
                           is_current=v['code'] == current)
                      for v in group['values'] if counts.get(v['id'])]
        groups.append(dict(group, count=total, values=values,
                           is_current=current == group['code']))
    return groups


# --- сигналы -----------------------------------------------------------------

def _on_task_data_changed(sender, using=None, **kwargs):
    invalidate_catalog_counts(using=using or 'default')


def _on_worksheet_item_changed(sender, instance, using=None, **kwargs):
    """Состав листка меняет базу каталога его владельца (visible_tasks):
    сбрасываем счётчики только ему. Листок уже мог быть удалён вместе с
    элементами — тогда сбрасываем всем."""
    from worksheets.models import Worksheet
    owner_id = (Worksheet.objects.filter(pk=instance.worksheet_id)
                .values_list('owner_id', flat=True).first())
    invalidate_catalog_counts(using=using or 'default', user_pk=owner_id)


def connect_catalog_counts_signals():
    """Задача, её темы, источники и классы — всё, от чего зависят числа;
    темы и источники через add()/set() идут bulk_create связки без
    post_save, поэтому ещё и m2m_changed. Элементы листков — для базы
    приглашённого учителя."""
    from django.db.models.signals import m2m_changed, post_delete, post_save

    from worksheets.models import WorksheetItem

    # Topic и Source — справочники: перенос темы в другой раздел меняет
    # поддеревья, а переименование источника — строки фасета (ревью #318)
    for model in (Task, TaskTopic, TaskSource, Topic, Source, FacetValue):
        label = model._meta.label_lower
        post_save.connect(_on_task_data_changed, sender=model,
                          dispatch_uid=f'problems.invalidate_catalog_counts.save.{label}')
        post_delete.connect(_on_task_data_changed, sender=model,
                            dispatch_uid=f'problems.invalidate_catalog_counts.delete.{label}')
    for name in ('grade_bands', 'topics', 'sources', 'facet_values'):
        m2m_changed.connect(_on_task_data_changed,
                            sender=getattr(Task, name).through,
                            dispatch_uid=f'problems.invalidate_catalog_counts.{name}')
    post_save.connect(_on_worksheet_item_changed, sender=WorksheetItem,
                      dispatch_uid='problems.invalidate_catalog_counts.save.worksheetitem')
    post_delete.connect(_on_worksheet_item_changed, sender=WorksheetItem,
                        dispatch_uid='problems.invalidate_catalog_counts.delete.worksheetitem')

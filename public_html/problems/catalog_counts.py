"""Счётчики панели каталога задач: разделы рубрикатора, классы, источники.

Числа одни и те же для всех страниц каталога одного учителя, но считались
заново на каждый запрос, причём каждый раздел — отдельным
``COUNT(DISTINCT …)`` по всем полям задачи (аудит быстродействия
06.11.2026: до 0,9 с на запрос). Здесь:

* число задач раздела — ``COUNT`` с ``EXISTS`` по связям тема–задача,
  без join и DISTINCT;
* результаты лежат в кэше ``catalog`` (файловый, общий для воркеров)
  по ключу «база, учитель, режим каталога, открытый раздел» и живут
  ``TIMEOUT`` кэша (5 минут); правка задачи, её тем, классов или
  источников сбрасывает их сразу (``invalidate_catalog_counts``, по
  сигналам из ``connect_catalog_counts_signals``). Массовые операции без
  сигналов (``bulk_create`` импорта) догоняет срок жизни кэша.
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

from .models import Task, TaskSource, TaskTopic
from .rubricator import GRADE_LEVEL_TO_CODE, parse_grade_choice

CACHE_ALIAS = 'catalog'
VERSION_KEY = 'catalog-counts:version'
SOURCE_LIMIT = 12


# --- кэш ---------------------------------------------------------------------

def _cache():
    return caches[CACHE_ALIAS]


def _version(using):
    """Метка поколения счётчиков: сброс — новая метка, старые записи
    остаются до истечения TIMEOUT и больше не читаются."""
    key = f'{VERSION_KEY}:{using}'
    try:
        version = _cache().get(key)
        if version is None:
            version = uuid.uuid4().hex
            _cache().set(key, version, None)
    except OSError:
        return None
    return version


def invalidate_catalog_counts(*, using=None):
    """Сбросить счётчики после успешной транзакции."""
    using = using or 'default'

    def bump():
        try:
            _cache().set(f'{VERSION_KEY}:{using}', uuid.uuid4().hex, None)
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
    if version is None:
        return None
    return f'catalog-counts:{digest}:{version}:{user.pk}:{_mode(user)}:{suffix}'


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


# --- сигналы -----------------------------------------------------------------

def _on_task_data_changed(sender, using=None, **kwargs):
    invalidate_catalog_counts(using=using or 'default')


def connect_catalog_counts_signals():
    """Задача, её темы, источники и классы — всё, от чего зависят числа."""
    from django.db.models.signals import m2m_changed, post_delete, post_save

    for model in (Task, TaskTopic, TaskSource):
        label = model._meta.label_lower
        post_save.connect(_on_task_data_changed, sender=model,
                          dispatch_uid=f'problems.invalidate_catalog_counts.save.{label}')
        post_delete.connect(_on_task_data_changed, sender=model,
                            dispatch_uid=f'problems.invalidate_catalog_counts.delete.{label}')
    m2m_changed.connect(_on_task_data_changed, sender=Task.grade_bands.through,
                        dispatch_uid='problems.invalidate_catalog_counts.grade_bands')

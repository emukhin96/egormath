"""Обзор «Авторских листков»: список по темам с предпросмотром и таблица.

Книжная подборка — параграфы одной книги, её страница читается как
оглавление. Авторские листки — отдельные произведения, и лента «все листки
раздела подряд» смысла не несёт. Поэтому у источника «Авторские листки»
своя страница: листки сгруппированы по главной теме рубрикатора, справа —
предпросмотр одного выбранного листка (вариант B), или оглавление по
темам-главам (вариант C).

Все метаданные списка (число задач, главная тема, прочие темы, задачи для
«Всё в корзину») собираются тремя запросами на всю страницу, без N+1:
задачи листков, основные темы этих задач и темы самих листков.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db import models
from django.utils import timezone

from problems.models import TaskTopic, Topic, topic_tree

from .authored import SECTION_PREFIX
from .corpus import SOURCE_TITLE
from .models import Collection, Worksheet, WorksheetItem

VIEWS = ('list', 'table')
SORTS = (
    ('topic', 'по теме'),
    ('date', 'по дате'),
    ('title', 'по названию'),
)
NO_TOPIC_LABEL = 'Без темы'

MONTHS = ('январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
          'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь')
MONTHS_SHORT = ('янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг',
                'сен', 'окт', 'ноя', 'дек')


def natural_key(text):
    """«Листок 2» раньше «Листок 10»: числа сравниваются как числа."""
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', text or '') if part)


def visible_q(user):
    """Условие видимости подборки — как в каталоге подборок."""
    if user.is_superuser:
        return models.Q()
    return models.Q(is_published=True) | models.Q(worksheet__owner_id=user.pk)


def _visible_children_q(user):
    if user.is_superuser:
        return models.Q(children__isnull=False)
    return (models.Q(children__is_published=True)
            | models.Q(children__worksheet__owner_id=user.pk))


def is_authored_section(collection):
    return (collection.source.title == SOURCE_TITLE
            and collection.locator.startswith(SECTION_PREFIX))


def is_authored_sheet(collection):
    return (collection.source.title == SOURCE_TITLE
            and not collection.locator.startswith(SECTION_PREFIX))


def section_short_title(title):
    """«8 класс» → «8», «10–11 класс» → «10–11»; «ОГЭ» как есть."""
    return re.sub(r'\s*класс$', '', title.strip())


@dataclass
class TopicInfo:
    topic: Topic
    label: str
    order: int


@dataclass
class Sheet:
    """Строка списка: листок-подборка с посчитанными метаданными."""
    collection: Collection
    section: Collection | None = None
    tasks_total: int = 0
    cart_task_ids: list = field(default_factory=list)
    main_topic: TopicInfo | None = None
    other_topics: list = field(default_factory=list)

    @property
    def pk(self):
        return self.collection.pk

    @property
    def title(self):
        return self.collection.worksheet.title

    @property
    def updated_at(self):
        return self.collection.worksheet.updated_at

    @property
    def month_year(self):
        moment = timezone.localtime(self.updated_at)
        return f'{MONTHS[moment.month - 1]} {moment.year}'

    @property
    def month_year_short(self):
        moment = timezone.localtime(self.updated_at)
        return f'{MONTHS_SHORT[moment.month - 1]} {moment.year}'

    @property
    def topics(self):
        """Главная тема и прочие — для чипов предпросмотра."""
        return ([self.main_topic] if self.main_topic else []) + self.other_topics


@dataclass
class Group:
    topic: TopicInfo | None
    label: str | None
    sheets: list

    @property
    def anchor(self):
        if self.topic:
            return f'topic-{self.topic.topic.pk}'
        return 'topic-none' if self.label else 'sheets'

    @property
    def tasks_total(self):
        return sum(sheet.tasks_total for sheet in self.sheets)

    @property
    def cart_task_ids(self):
        seen, result = set(), []
        for sheet in self.sheets:
            for task_id in sheet.cart_task_ids:
                if task_id not in seen:
                    seen.add(task_id)
                    result.append(task_id)
        return result


def topic_index():
    """Темы рубрикатора: порядок дерева и подпись «Раздел › тема» (1 запрос)."""
    index, roots = {}, {}
    for position, topic in enumerate(topic_tree()):
        root = roots.get(topic.parent_id, topic)
        roots[topic.pk] = root
        label = (f'{root.name} › {topic.name}' if root.pk != topic.pk
                 else topic.name)
        index[topic.pk] = TopicInfo(topic=topic, label=label, order=position)
    return index


def sections_of(source, user):
    """Разделы источника с числом видимых листков (для сегментов и панели)."""
    sections = list(
        Collection.objects.filter(
            source=source, parent__isnull=True,
            locator__startswith=SECTION_PREFIX)
        .select_related('worksheet')
        .annotate(sheets_total=models.Count(
            'children', filter=_visible_children_q(user), distinct=True))
        .order_by('order', 'pk'))
    for section in sections:
        section.short_title = section_short_title(section.worksheet.title)
    return sections


def _main_topic(task_topic_counts, sheet_topic_ids, index):
    """Тема большинства задач; при равенстве — первая из тем листка."""
    if task_topic_counts:
        best = max(task_topic_counts.values())
        tied = [pk for pk, count in task_topic_counts.items() if count == best]
        for pk in sheet_topic_ids:
            if pk in tied and pk in index:
                return pk
        tied = [pk for pk in tied if pk in index]
        if tied:
            return min(tied, key=lambda pk: index[pk].order)
    for pk in sheet_topic_ids:
        if pk in index:
            return pk
    return None


def load_sheets(source, user, section=None, pks=None):
    """Видимые листки источника (или раздела, или ``pks``) с метаданными."""
    collections = (
        Collection.objects.filter(source=source)
        .exclude(locator__startswith=SECTION_PREFIX)
        .filter(visible_q(user))
        .select_related('worksheet', 'parent__worksheet'))
    if section is not None:
        collections = collections.filter(parent=section)
    if pks is not None:
        collections = collections.filter(pk__in=pks)
    collections = list(collections)
    if not collections:
        return []
    by_worksheet = {c.worksheet_id: Sheet(collection=c, section=c.parent)
                    for c in collections}
    worksheet_ids = list(by_worksheet)

    # 1. Задачи листков: число, id для корзины, листки каждой задачи.
    sheets_of_task = {}
    items = (WorksheetItem.objects
             .filter(worksheet_id__in=worksheet_ids, deleted_at__isnull=True,
                     task__isnull=False)
             .order_by('worksheet_id', 'order', 'id')
             .values_list('worksheet_id', 'task_id', 'task__variant_of_id'))
    for worksheet_id, task_id, variant_of_id in items:
        sheet = by_worksheet[worksheet_id]
        sheet.tasks_total += 1
        if not variant_of_id and task_id not in sheet.cart_task_ids:
            sheet.cart_task_ids.append(task_id)
        sheets_of_task.setdefault(task_id, set()).add(worksheet_id)

    # 2. Основные темы задач → счётчики «тема: задач» по листкам.
    counts = {worksheet_id: {} for worksheet_id in worksheet_ids}
    links = (TaskTopic.objects
             .filter(role=TaskTopic.ROLE_PRIMARY,
                     task__worksheet_items__worksheet_id__in=worksheet_ids,
                     task__worksheet_items__deleted_at__isnull=True)
             .values_list('task_id', 'topic_id').distinct())
    for task_id, topic_id in links:
        for worksheet_id in sheets_of_task.get(task_id, ()):
            sheet_counts = counts[worksheet_id]
            sheet_counts[topic_id] = sheet_counts.get(topic_id, 0) + 1

    # 3. Темы самих листков в порядке назначения.
    sheet_topics = {worksheet_id: [] for worksheet_id in worksheet_ids}
    through = Worksheet.topics.through.objects.filter(
        worksheet_id__in=worksheet_ids).order_by('id')
    for worksheet_id, topic_id in through.values_list('worksheet_id', 'topic_id'):
        sheet_topics[worksheet_id].append(topic_id)

    index = topic_index()
    for worksheet_id, sheet in by_worksheet.items():
        main = _main_topic(counts[worksheet_id], sheet_topics[worksheet_id], index)
        sheet.main_topic = index.get(main)
        others = []
        for pk in sheet_topics[worksheet_id] + sorted(
                counts[worksheet_id], key=lambda pk: -counts[worksheet_id][pk]):
            if pk != main and pk in index and pk not in others:
                others.append(pk)
        sheet.other_topics = [index[pk] for pk in others]
    return list(by_worksheet.values())


def by_title(sheets):
    return sorted(sheets, key=lambda sheet: (natural_key(sheet.title), sheet.pk))


def by_date(sheets):
    return sorted(sheets, key=lambda sheet: (sheet.updated_at, sheet.pk),
                  reverse=True)


def group_sheets(sheets, sort='topic'):
    """Группы для показа: по главной теме или одна группа без заголовка."""
    if sort == 'date':
        return [Group(topic=None, label=None, sheets=by_date(sheets))]
    if sort == 'title':
        return [Group(topic=None, label=None, sheets=by_title(sheets))]
    groups, no_topic = {}, []
    for sheet in sheets:
        if sheet.main_topic is None:
            no_topic.append(sheet)
        else:
            groups.setdefault(sheet.main_topic.topic.pk, []).append(sheet)
    result = [
        Group(topic=rows[0].main_topic, label=rows[0].main_topic.label,
              sheets=by_title(rows))
        for rows in sorted(groups.values(),
                           key=lambda rows: rows[0].main_topic.order)]
    if no_topic:
        result.append(Group(topic=None, label=NO_TOPIC_LABEL,
                            sheets=by_title(no_topic)))
    return result

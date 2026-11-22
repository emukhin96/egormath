"""Фильтр задач внутри открытой подборки (правая панель collection_detail).

Пока подборка выбрана, пункты панели «Темы» и «Содержание» сужают задачи
ЭТОЙ подборки (?topic=, ?content=), а не уводят в общий каталог: выбор
подборки не сбрасывается. Темы и содержание берутся из самих задач
подборки (со счётчиками), а не из тем листка-содержимого.

ИЛИ внутри фасета, И между фасетами — как в каталоге
(problems.rubricator.filter_by_taxonomy).
"""
from django.db.models import Count

from problems.models import FacetValue, Task, TaskTopic, Topic
from problems.rubricator import filter_by_taxonomy
from problems.templatetags.page_tools import query_url

FILTER_PARAMS = ('topic', 'content')


def _ids(params, name):
    return [value for value in params.getlist(name) if value]


def active_filter(params):
    """Есть ли в адресе фильтр задач подборки."""
    return any(_ids(params, name) for name in FILTER_PARAMS)


def matching_task_ids(params, task_ids):
    """id задач подборки под фильтром; None — фильтра нет."""
    if not active_filter(params):
        return None
    tasks = filter_by_taxonomy(
        Task.objects.filter(pk__in=task_ids), params, topics_lookups=('topics',))
    return set(tasks.values_list('pk', flat=True))


def filter_items(items, matching):
    """Элементы подборки без задач вне фильтра.

    Рубрики остаются, только если за ними есть подходящая задача. Уровней у
    рубрик нет, поэтому рубрики подряд читаются как «глава, затем
    параграф»: последняя из них — параграф, предыдущие — заголовки выше,
    они действуют до следующей такой же пачки рубрик. Так параграф,
    перед которым выпал соседний, не теряет свою главу. Текстовые
    элементы при фильтре не показываются — они поясняют весь параграф, а
    не задачу.

    Номер задачи в подборке (``collection_number``) запоминается до
    фильтра: у задач без номера из задачника под фильтром печатается тот
    же позиционный номер, что и в полной подборке.
    """
    if matching is None:
        return items
    number = 0
    for item in items:
        if item.task_id:
            number += 1
            item.collection_number = number
    kept, emitted = [], set()
    headers, run, leaf = [], [], None
    for item in items:
        if item.is_rubric:
            run.append(item)
            continue
        if run:
            if len(run) > 1:
                headers = run[:-1]
            leaf, run = run[-1], []
        if item.task_id and item.task_id in matching:
            for rubric in (*headers, leaf):
                if rubric is not None and id(rubric) not in emitted:
                    emitted.add(id(rubric))
                    kept.append(rubric)
            kept.append(item)
    return kept


def _choice(params, obj, total, param, selected, value):
    """Пункт панели: щелчок выбирает значение (одно на фасет), повторный —
    снимает; остальные параметры адреса (who, view) сохраняются."""
    active = value in selected
    return {'obj': obj, 'total': total, 'active': active,
            'url': query_url(params, {param: None if active else value, 'task': None})}


def reset_url(params):
    return query_url(params, {name: None for name in (*FILTER_PARAMS, 'task')})


def sidebar_options(params, task_ids):
    """Пункты панели: темы и значения «Содержания» задач подборки со
    счётчиками задач (без учёта фильтра — список не прыгает при выборе)."""
    task_ids = list(task_ids)
    if not task_ids:
        return {'topics': [], 'content': []}
    selected_topics = set(_ids(params, 'topic'))
    # Счётчик темы — по её поддереву, как считает сам фильтр
    # (rubricator.expand_topic_ids): у раздела — и задачи его подтем
    tasks_by_topic = {}
    for task_id, topic_id in (TaskTopic.objects.filter(task_id__in=task_ids)
                              .values_list('task_id', 'topic_id')):
        tasks_by_topic.setdefault(topic_id, set()).add(task_id)
    by_parent = Topic.children_map() if tasks_by_topic else {}
    topic_counts = {
        topic_id: len(set().union(*(tasks_by_topic.get(pk, ())
                                    for pk in Topic.subtree_ids(topic_id, by_parent))))
        for topic_id in tasks_by_topic}
    topics = sorted(Topic.objects.filter(pk__in=topic_counts),
                    key=lambda topic: (topic.code or '', topic.name))
    through = Task.facet_values.through
    content_counts = dict(
        through.objects.filter(task_id__in=task_ids,
                               facetvalue__facet_type__code='CONTENT')
        .values_list('facetvalue_id').annotate(total=Count('task_id', distinct=True)))
    selected_content = set(_ids(params, 'content'))
    content = sorted(FacetValue.objects.filter(pk__in=content_counts)
                     .select_related('parent'),
                     key=lambda value: (value.parent.order if value.parent_id else 0,
                                        value.order, value.name))
    return {
        'topics': [_choice(params, topic, topic_counts[topic.pk], 'topic',
                           selected_topics, str(topic.pk))
                   for topic in topics],
        # ?content= — код значения, как в каталоге (rubricator.content_value_ids)
        'content': [_choice(params, value, content_counts[value.pk], 'content',
                            selected_content, value.code)
                    for value in content],
    }

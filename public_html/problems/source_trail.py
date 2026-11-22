"""Путь к задаче в подборках — хлебные крошки карточки задачи.

«Задачи › Мерзляк. Алгебра 7 › Глава 1 › § 2» — каждая часть ведёт в
каталог подборок: источник — на его страницу (?source=), подборка — на
страницу подборки, последняя — сразу на страницу с этой задачей
(?task=, worksheets.views.collection_detail).

Видимость подборок — как в каталоге: опубликованные, свои, у
суперпользователя все. Если задача ни в одной видимой подборке источника
нет, источник выводится текстом без ссылки.
"""
from django.db.models import Q
from django.urls import reverse


def _visible(user, queryset):
    if user.is_superuser:
        return queryset
    return queryset.filter(Q(is_published=True) | Q(worksheet__owner_id=user.pk))


def _ancestors(collection):
    """Цепочка от корня источника до подборки включительно."""
    chain, node, seen = [], collection, set()
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        chain.append(node)
        node = node.parent
    return list(reversed(chain))


def source_trails(user, task):
    """Список путей по источникам задачи: ``[{'ref', 'crumbs', 'url'}]``.

    ``crumbs`` — части пути ``{'title', 'url'}`` без «Задачи»; ``url`` —
    адрес подборки с этой задачей (или ``None``).
    """
    from worksheets.collection_catalog import catalog_title
    from worksheets.models import Collection

    refs = list(task.source_refs.all())
    if not refs:
        return []
    collections = _visible(user, Collection.objects.filter(
        source_id__in={ref.source_id for ref in refs},
        worksheet__items__task_id=task.pk,
        worksheet__items__deleted_at__isnull=True,
    )).select_related('worksheet', 'parent__worksheet').distinct()
    # Самая глубокая подборка источника — та, где задача стоит сама,
    # а не в общем разделе.
    best = {}
    for collection in collections:
        current = best.get(collection.source_id)
        if current is None or (len(collection.source_path or [])
                               > len(current.source_path or [])):
            best[collection.source_id] = collection
    trails = []
    for ref in refs:
        leaf = best.get(ref.source_id)
        source_url = (f'{reverse("collection_list")}?source={ref.source_id}'
                      if leaf else None)
        crumbs = [{'title': ref.source.title, 'url': source_url}]
        url = None
        if leaf:
            for node in _ancestors(leaf):
                crumbs.append({
                    'title': catalog_title(node.worksheet.title),
                    'url': reverse('collection_detail', args=[node.pk]),
                })
            url = (f'{reverse("collection_detail", args=[leaf.pk])}'
                   f'?task={task.pk}#task-{task.pk}')
            crumbs[-1]['url'] = url
        trails.append({'ref': ref, 'crumbs': crumbs, 'url': url})
    return trails

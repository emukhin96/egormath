"""Аналоги учителю (ROADMAP 11.2026, п. 2б): списки и счётчики семей.

Аналоги задачи — остальные участники её сохранённых семей
(``FamilyMember``) и семей задачи, локальной копией которой она является
(``variant_of``), как во вкладке «Связанные аналоги» при подборе. Видны
только задачи из ``catalog_tasks``: чужая личная задача не показывается и
не считается, локальные копии — тоже (у них своя карточка в листке).

Счётчики для страницы — два запроса на любой набор задач
(``analog_ids``), без запроса на каждую строку.
"""
import uuid
from collections import defaultdict

from django.db import transaction

from accounts.permissions import catalog_tasks
from problems.models import Task
from .models import Family, FamilyExclusion, FamilyMember

# Сколько аналогов показывать в списке: у прототипов банков ФИПИ бывают
# десятки задач; остальное — в подборе и по ссылке «ещё N».
LIST_LIMIT = 30


def analog_ids(user, tasks):
    """``{task.pk: [id аналогов по возрастанию]}`` для набора задач.

    ``tasks`` — уже загруженные задачи (нужны ``pk`` и ``variant_of_id``).
    Задачи без аналогов в результат не попадают.
    """
    tasks = [task for task in tasks if task is not None]
    lookup = {task.pk for task in tasks} | {task.variant_of_id for task in tasks if task.variant_of_id}
    if not lookup:
        return {}
    by_task = defaultdict(set)
    for task_id, family_id in FamilyMember.objects.filter(task_id__in=lookup).values_list('task_id', 'family_id'):
        by_task[task_id].add(family_id)
    families = set().union(*by_task.values()) if by_task else set()
    if not families:
        return {}
    members = defaultdict(set)
    rows = FamilyMember.objects.filter(
        family_id__in=families, task_id__in=catalog_tasks(user).values('pk')
    ).values_list('family_id', 'task_id')
    for family_id, task_id in rows:
        members[family_id].add(task_id)
    result = {}
    for task in tasks:
        own = by_task.get(task.pk, set()) | by_task.get(task.variant_of_id, set())
        found = set().union(*(members[f] for f in own)) if own else set()
        found -= {task.pk, task.variant_of_id}
        if found:
            result[task.pk] = sorted(found)
    return result


def attach_analog_counts(user, tasks):
    """``task.analog_count`` каждой задаче набора (каталог, конструктор)."""
    tasks = [task for task in tasks if task is not None]
    ids = analog_ids(user, tasks)
    for task in tasks:
        task.analog_count = len(ids.get(task.pk, ()))
    return ids


def analog_tasks(user, task, *, limit=LIST_LIMIT):
    """``(задачи для списка, сколько всего)`` — аналоги одной задачи с
    источниками, подпунктами и рисунками для краткого условия."""
    ids = analog_ids(user, [task]).get(task.pk, [])
    shown = ids[:limit] if limit else ids
    tasks = list(Task.objects.filter(pk__in=shown).order_by('pk').prefetch_related(
        'source_refs__source', 'subitems', 'images'))
    return tasks, len(ids)


def catalog_original(task):
    """Задача, к семьям которой относится действие редактора: у локальной
    копии — её каталожный оригинал."""
    return task.variant_of if task.variant_of_id else task


@transaction.atomic
def unlink(task, analog, user=None):
    """Отвязывает ``analog`` от всех семей, общих с ``task`` (и с её
    оригиналом, если это локальная копия). Возвращает число семей.

    Связь не возвращается синхронизацией: пара (семья, задача) остаётся
    в ``FamilyExclusion``."""
    own = set(FamilyMember.objects.filter(task_id__in={task.pk, task.variant_of_id} - {None})
              .values_list('family_id', flat=True))
    shared = FamilyMember.objects.filter(family_id__in=own, task=analog)
    families = list(shared.values_list('family_id', flat=True))
    for family_id in families:
        FamilyExclusion.objects.get_or_create(family_id=family_id, task=analog,
                                              defaults={'created_by': user})
    shared.delete()
    return len(families)


@transaction.atomic
def link(task, target, user=None):
    """Ручная связь «Связать с задачей №…»: ``target`` входит в семью
    ``task`` (первую по порядку), иначе ``task`` — в семью ``target``,
    иначе создаётся ручная семья из двух задач (origin='manual').
    Исключение пары, если редактор её раньше отвязал, снимается.
    Возвращает семью."""
    task, target = catalog_original(task), catalog_original(target)
    family = (Family.objects.filter(familymember__task=task).order_by('pk').first()
              or Family.objects.filter(familymember__task=target).order_by('pk').first())
    if family is None:
        family = Family.objects.create(key='manual:link:' + uuid.uuid4().hex,
                                       title=f'Аналоги задачи {task.pk}', origin='manual')
    for member in (task, target):
        FamilyMember.objects.get_or_create(family=family, task=member,
                                           defaults={'origin': 'manual', 'evidence': [
                                               {'linked_by': getattr(user, 'pk', None)}]})
        FamilyExclusion.objects.filter(family=family, task=member).delete()
    return family

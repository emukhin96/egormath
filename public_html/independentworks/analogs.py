"""Явные связи источников; повторный запуск сохраняет ручные семейства."""
import re
from collections import defaultdict
from django.db import transaction
from problems.models import TaskSource
from worksheets.models import Collection
from .models import Family


@transaction.atomic
def sync_families():
    groups = defaultdict(set)
    titles = {}
    for ref in TaskSource.objects.select_related('source').filter(task__variant_of__isnull=True):
        path = ref.source_path or []
        locator = ref.locator or ''
        ziv = re.fullmatch(r'(sr|kr|pr)/(\d+)/v([1-8])/(.+)', locator)
        if ziv:
            kind, topic, variant, number = ziv.groups()
            pair = (int(variant) - 1) // 2
            key = f'ziv:{ref.source_id}:{kind}:{topic}:{pair}:{number}'
            groups[key].add(ref.task_id)
            titles[key] = f'Зив · {kind}/{topic} · варианты {pair * 2 + 1}–{pair * 2 + 2} · №{number}'
            continue
        proto = next((re.search(r'прототип\s+(\d+\.\d+)', str(p), re.I) for p in path
                      if re.search(r'прототип\s+(\d+\.\d+)', str(p), re.I)), None)
        bank_path = any(re.search(r'прототип|аналог', str(p), re.I) for p in path)
        numbered = re.fullmatch(r'(\d+\.\d+)(?:\.\d+)?', locator)
        if proto or (bank_path and numbered):
            prototype = proto.group(1) if proto else numbered.group(1)
            key = f'bank:{ref.source_id}:{prototype}'
            groups[key].add(ref.task_id)
            titles[key] = f'{ref.source.title} · прототип {prototype}'
    # Старые импорты ФИПИ сохраняли отношение в иерархии подборок.
    for collection in Collection.objects.select_related('worksheet', 'parent__worksheet'):
        title = collection.worksheet.title
        parent = collection.parent
        base = collection if re.search(r'прототип\s+\d+\.\d+', title, re.I) else None
        if parent and re.search(r'аналог', title, re.I) and re.search(r'прототип\s+\d+\.\d+', parent.worksheet.title, re.I):
            base = parent
        if base:
            prototype = re.search(r'прототип\s+(\d+\.\d+)', base.worksheet.title, re.I).group(1)
            key = f'bank:{collection.source_id}:{prototype}'
            groups[key].update(collection.worksheet.items.filter(task__isnull=False, deleted_at__isnull=True).values_list('task_id', flat=True))
            titles[key] = base.worksheet.title
    total = 0
    for key, ids in groups.items():
        if len(ids) < 2:
            continue
        if len(key) > 255:
            from .services import digest
            key = 'source:' + digest(key)
        family, _ = Family.objects.get_or_create(key=key, defaults={'title': titles.get(key, 'Аналоги источника')[:255], 'origin': 'source'})
        family.tasks.add(*ids, through_defaults={'origin': 'source'})
        total += 1
    return total

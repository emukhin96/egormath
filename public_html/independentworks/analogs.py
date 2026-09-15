"""Восстановление явных связей без повторного импорта условий."""
import hashlib
import re
from collections import defaultdict

from django.db import transaction
from problems.models import TaskSource
from worksheets.models import Collection
from .models import Family, FamilyMember

ZIV = re.compile(r'(sr|kr|pr)/(\d+)/v([1-8])/(.+)')
PROTOTYPE = re.compile(r'прототип(?:а|у)?\s*[№:]?\s*(\d+(?:\.\d+)+)', re.I)
SECTION = re.compile(r'прототип|аналог', re.I)


def bank_identity(source_id, path, locator=''):
    """Рубрика без номера не определяет семейство сама по себе."""
    path = [str(p).strip() for p in path if str(p).strip()]
    explicit = [(i, PROTOTYPE.search(p)) for i, p in enumerate(path)]
    explicit = [(i, m.group(1)) for i, m in explicit if m]
    if explicit:
        index, number = explicit[-1]
    else:
        match = re.fullmatch(r'(\d+\.\d+)(?:\.\d+)?', locator or '')
        indices = [i for i, p in enumerate(path) if SECTION.search(p)]
        if not match or not indices:
            return None
        index, number = indices[0], match.group(1)
    # Номер задания банка уже входит в номер прототипа. Другие разделы
    # сохраняем: одинаковая нумерация разных глав не означает аналогию.
    scope = [re.sub(r'№\s*0*(\d+)\.?\s*', r'№\1 ', p.casefold()).strip() for p in path[:index]
             if not SECTION.search(p) and not re.fullmatch(r'№?\s*\d+\.?', p)]
    suffix = ':' + hashlib.sha256('/'.join(scope).encode()).hexdigest()[:16] if scope else ''
    key = f'bank:{source_id}:{number}{suffix}'
    if len(key) > 255:
        key = 'source:' + hashlib.sha256(key.encode()).hexdigest()
    return key, number


def discover_families():
    groups = {}
    ambiguous = []
    ziv_variants = defaultdict(lambda: defaultdict(set))

    def add(key, title, task_id, evidence):
        group = groups.setdefault(key, {'title': title[:255], 'members': defaultdict(list)})
        if evidence not in group['members'][task_id]:
            group['members'][task_id].append(evidence)

    refs = list(TaskSource.objects.select_related('source').filter(task__variant_of__isnull=True))
    ref_index = defaultdict(list)
    for ref in refs:
        ref_index[(ref.source_id, ref.task_id)].append(ref)
        path, locator = ref.source_path or [], ref.locator or ''
        match = ZIV.fullmatch(locator)
        evidence = {'source_id': ref.source_id, 'locator': locator, 'path': path}
        if match:
            kind, topic, variant, number = match.groups()
            pair = (int(variant) - 1) // 2
            key = f'ziv:{ref.source_id}:{kind}:{topic}:{pair}:{number}'
            title = f'{ref.source.title} · {kind}/{topic} · варианты {pair * 2 + 1}–{pair * 2 + 2} · №{number}'
            add(key, title, ref.task_id, evidence)
            ziv_variants[key][int(variant)].add(ref.task_id)
        elif any(SECTION.search(str(p)) for p in path):
            identity = bank_identity(ref.source_id, path, locator)
            if identity:
                key, number = identity
                add(key, f'{ref.source.title} · прототип {number}', ref.task_id, evidence)
            else:
                ambiguous.append(f'Задача #{ref.task_id}: не определён прототип ({" / ".join(path)})')

    collections = list(Collection.objects.select_related('worksheet', 'source').prefetch_related('worksheet__items__task'))
    by_id = {c.pk: c for c in collections}
    for collection in collections:
        ancestors, current, visited = [], collection, set()
        while current and current.pk not in visited:
            visited.add(current.pk)
            ancestors.insert(0, current.worksheet.title)
            current = by_id.get(current.parent_id)
        path = list(collection.source_path or ancestors)
        context = path
        for item in collection.worksheet.ordered_items():
            if item.rubric:
                # Следующая рубрика заменяет предыдущую; «Аналоги» без
                # номера не наследует произвольный соседний прототип.
                context = path + [item.rubric]
            if not item.task_id or item.task.variant_of_id:
                continue
            if not any(SECTION.search(str(p)) for p in context):
                continue
            identity = bank_identity(collection.source_id, context)
            if identity is None:
                identities = {bank_identity(collection.source_id, context, ref.locator)
                              for ref in ref_index[(collection.source_id, item.task_id)]}
                identities.discard(None)
                if len(identities) == 1:
                    identity = identities.pop()
            if not identity:
                ambiguous.append(f'Подборка #{collection.pk}, задача #{item.task_id}: неоднозначная рубрика')
                continue
            key, number = identity
            add(key, f'{collection.source.title} · прототип {number}', item.task_id,
                {'source_id': collection.source_id, 'collection_id': collection.pk,
                 'item_id': item.pk, 'path': context})

    incomplete = []
    for key, variants in ziv_variants.items():
        if len(variants) != 2:
            incomplete.append(groups[key]['title'])
            groups.pop(key)
        elif any(len(ids) != 1 for ids in variants.values()):
            ambiguous.append(groups[key]['title'] + ': несколько задач одного исходного номера')
            groups.pop(key)
    return {key: value for key, value in groups.items() if len(value['members']) > 1}, incomplete, sorted(set(ambiguous))


def sync_families(*, dry_run=False, report=False):
    groups, incomplete, ambiguous = discover_families()
    result = {'families': len(groups), 'created': 0, 'members_added': 0,
              'incomplete': incomplete, 'ambiguous': ambiguous, 'dry_run': dry_run}
    with transaction.atomic():
        for key, group in groups.items():
            family = Family.objects.filter(key=key).first()
            if family is None:
                result['created'] += 1
                if not dry_run:
                    family = Family.objects.create(key=key, title=group['title'], origin='source')
            existing = {m.task_id: m for m in family.familymember_set.all()} if family else {}
            for task_id, evidence in group['members'].items():
                member = existing.get(task_id)
                if member is None:
                    result['members_added'] += 1
                    if not dry_run:
                        FamilyMember.objects.get_or_create(family=family, task_id=task_id,
                            defaults={'origin': 'source', 'evidence': evidence})
                elif not dry_run and member.origin == 'source':
                    combined = member.evidence + [e for e in evidence if e not in member.evidence]
                    if combined != member.evidence:
                        member.evidence = combined
                        member.save(update_fields=['evidence'])
    return result if report else result['families']

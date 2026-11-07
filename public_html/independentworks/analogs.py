"""Восстановление явных связей без повторного импорта условий."""
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from django.db import transaction
from django.db.models import Prefetch
from problems.models import Source, Task, TaskSource
from worksheets.models import Collection, WorksheetItem
from .models import Family, FamilyExclusion, FamilyMember

# Ключи Зива ``(sr|kr|pr)/NN/vK/num`` для мастера «пара вариантов»
# (``preparation.ziv_rows``). Семьи строит правило ``ziv`` ниже. Номер —
# одна-две цифры: трёхзначные «sr/01/v1/001» — Феоктистов, у него не пары.
ZIV = re.compile(r'(sr|kr|pr)/(\d{1,2})/v([1-8])/(\d{1,2}[а-я]?)')

# Профили импорта, у которых при «Загрузить в каталог» сразу строятся
# семьи аналогов (``problems.textbook_import.commit_batch``): варианты
# работ по правилам ``VARIANT_RULES`` и прототипы банков ФИПИ по рубрикам
# (``bank_identity``). Новому профилю с вариантами достаточно выдавать
# локаторы по одному из правил и вписать себя сюда; новый формат
# локатора — новое правило, не пересекающееся с остальными
# (``test_analog_rules.RuleContractTests``).
ANALOG_PROFILES = frozenset({
    'ziv', 'feoktistov', 'vysotsky', 'shabunin_method', 'merzlyak_dm',
    'ostromogilsky', 'ostromogilsky_ege',
})


@dataclass(frozen=True)
class VariantRule:
    """«Один номер в вариантах одной работы — аналоги» для формата локатора.

    ``pattern`` — полный локатор с группами ``work`` (работа, вместе с темой),
    ``variant`` и ``number``. ``pairs`` — семья в паре вариантов 1–2, 3–4, …
    (авторские уровни сложности, Зив и контрольные Высоцкого), иначе —
    во всех вариантах работы. ``prefix`` — начало ключа семьи: ключи уже
    созданных семей не меняются.
    """
    name: str
    pattern: re.Pattern
    pairs: bool
    prefix: str = 'variants'
    work_title: Callable[[str], str] = str

    def variant_number(self, variant):
        """«prep» → 0, «v3» → 3, «5» → 5; без варианта — 1."""
        if not variant:
            return 1
        if variant == 'prep':
            return 0
        return int(variant.lstrip('v'))


def _feoktistov_work(work):
    kind, number = work.split('/')
    return f"{({'sr': 'СР', 'kr': 'КР', 'test': 'Тест'})[kind]} {int(number)}"


def _merzlyak_dm_work(work):
    """«ДМ» → «Упражнения», «КР3» → «КР 3»."""
    return 'Упражнения' if work == 'ДМ' else f'КР {work[2:]}'


# Порядок важен только для читаемости: форматы не пересекаются.
VARIANT_RULES = (
    # Феоктистов: «sr/01/prep/001», «kr/01/v3/002», «test/02/v1/001» —
    # подготовительный и варианты 1–3 (тесты 1–2) одной работы однотипны.
    VariantRule('feoktistov', re.compile(
        r'(?P<work>(?:sr|kr|test)/\d{2})/(?P<variant>prep|v\d)/(?P<number>\d{3})'),
        pairs=False, work_title=_feoktistov_work),
    # Зив: «sr/03/v5/2». Варианты 1–2, 3–4, 5–6, 7–8 — уровни сложности:
    # один номер в разных парах — разные приёмы, аналоги только в паре.
    # «v0» (тема и вариант не распознаны) — в отчёт, без связи.
    VariantRule('ziv', re.compile(
        r'(?P<work>(?:sr|kr|pr)/\d{1,2})/v(?P<variant>[1-9])/(?P<number>\d{1,2}[а-я]?)'),
        pairs=True, prefix='ziv'),
    # Высоцкий: самостоятельные «С1.2/3» (два варианта) и контрольные
    # «КI.3/4» (1–2 базовые, 3–4 более содержательные — разные пары).
    VariantRule('vysotsky', re.compile(
        r'(?P<work>С\d{1,2}|КI{1,3})\.(?P<variant>[1-4])/(?P<number>\d{1,2})'),
        pairs=True),
    # Шабунин, методическое пособие: «КРII.1.В5/3», включая варианты со
    # звёздочкой; у работы без вариантов «СРIX.2/1» — один вариант.
    VariantRule('shabunin_method', re.compile(
        r'(?P<work>(?:ДКР|КР|СР)[IVX]{1,4}\.\d)(?:\.В(?P<variant>\d))?/(?P<number>\d{1,2})'),
        pairs=False),
    # ДМ Мерзляка, базовый уровень (договор 07.11.2026): упражнения
    # «ДМ.В2/170» в вариантах 1–4, контрольные «КР3.В1/4».
    VariantRule('merzlyak_dm', re.compile(
        r'(?P<work>ДМ|КР\d{1,2})\.В(?P<variant>\d)/(?P<number>\d{1,4})'),
        pairs=False, work_title=_merzlyak_dm_work),
)
ZIV_UNKNOWN_VARIANT = re.compile(r'(sr|kr|pr)/\d{1,2}/v0/.+')
RULES = {rule.name: rule for rule in VARIANT_RULES}
# Прежние имена регулярок Высоцкого и Шабунина (на них ссылаются docs).
WORK_VARIANT = RULES['vysotsky'].pattern
WORK_ALL_VARIANTS = RULES['shabunin_method'].pattern


def variant_identity(source_id, locator):
    """``(ключ, подпись, номер варианта, правило, подписан ли вариант)``.

    Подпись — без названия источника. Вариант не подписан у работы без
    вариантов («СРIX.2/1»). Не вариант работы — ``None``.
    """
    for rule in VARIANT_RULES:
        match = rule.pattern.fullmatch(locator or '')
        if not match:
            continue
        work, number = match.group('work'), match.group('number')
        variant = rule.variant_number(match.group('variant'))
        shown = number.lstrip('0') or number
        if rule.pairs:
            pair = (variant - 1) // 2
            group = str(pair)
            label = f'варианты {pair * 2 + 1}–{pair * 2 + 2}'
        else:
            group, label = 'all', 'все варианты'
        # Ключ Зива — «ziv:ист:sr:03:пара:номер», как до общих правил.
        work_key = work.replace('/', ':') if rule.prefix == 'ziv' else work
        key = f'{rule.prefix}:{source_id}:{work_key}:{group}:{number}'
        labeled = match.group('variant') is not None
        return key, f'{rule.work_title(work)} · {label} · №{shown}', variant, rule, labeled
    return None


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


def task_family_keys(task_ids):
    """Признаки семей аналогов для небольшого набора задач (корзина).

    Сохранённые семьи — как вкладка «Связанные аналоги» в подборе
    (``Task.analog_families``, в т.ч. вручную созданные аналоги) — плюс
    автоопределение по ``TaskSource`` теми же правилами, что и
    ``discover_families``: варианты работ (``VARIANT_RULES``) и «прототип
    N.N» банка. Локальная копия (``variant_of``) наследует признаки
    исходной задачи, как ``compact._families``. Подборочные рубрики без
    синхронизации не просматриваем: это полный проход по каталогу.
    """
    ids = list(task_ids)
    origins = dict(Task.objects.filter(pk__in=ids, variant_of__isnull=False)
                   .values_list('pk', 'variant_of_id'))
    lookup = set(ids) | set(origins.values())
    own = defaultdict(set)
    for task_id, family_id in FamilyMember.objects.filter(task_id__in=lookup).values_list('task_id', 'family_id'):
        own[task_id].add(f'family:{family_id}')
    for ref in TaskSource.objects.filter(task_id__in=lookup):
        path, locator = ref.source_path or [], ref.locator or ''
        identity = variant_identity(ref.source_id, locator)
        if identity:
            own[ref.task_id].add(identity[0])
        elif any(SECTION.search(str(p)) for p in path):
            identity = bank_identity(ref.source_id, path, locator)
            if identity:
                own[ref.task_id].add(identity[0])
    keys = defaultdict(set)
    for pk in ids:
        found = own.get(pk, set()) | own.get(origins.get(pk), set())
        if found:
            keys[pk] = found
    return keys


def similar_groups(task_ids):
    """Задачи набора, у которых в нём же есть аналог: ``{id: номер группы}``.

    Группа — связная компонента по общим признакам семьи; номера групп
    идут в порядке первого появления задачи в ``task_ids``. Одиночки в
    результат не попадают.
    """
    ids = list(dict.fromkeys(task_ids))
    keys = task_family_keys(ids)
    parent = {pk: pk for pk in ids}

    def find(pk):
        while parent[pk] != pk:
            parent[pk] = parent[parent[pk]]
            pk = parent[pk]
        return pk

    first_with_key = {}
    for pk in ids:
        for key in sorted(keys.get(pk, ())):
            if key in first_with_key:
                parent[find(pk)] = find(first_with_key[key])
            else:
                first_with_key[key] = pk
    sizes = defaultdict(int)
    for pk in ids:
        sizes[find(pk)] += 1
    numbers, result = {}, {}
    for pk in ids:
        root = find(pk)
        if sizes[root] > 1:
            result[pk] = numbers.setdefault(root, len(numbers))
    return result


def discover_families(*, source_id=None):
    groups = {}
    ambiguous = []
    # Ключ семьи варианта работы → (пары ли, {вариант: задачи}).
    work_variants = {}
    # Семьи, где есть задача с подписанным вариантом: одиночная работа без
    # вариантов («СРIX.2/1») не неполная пара и в отчёт не идёт.
    labeled_keys = set()

    def add(key, title, task_id, evidence):
        group = groups.setdefault(key, {'title': title[:255], 'members': defaultdict(list),
                                        'source_id': evidence['source_id']})
        if evidence not in group['members'][task_id]:
            group['members'][task_id].append(evidence)

    source_filter = {'source_id': source_id} if source_id is not None else {}
    refs = list(TaskSource.objects.select_related('source').filter(task__variant_of__isnull=True, **source_filter))
    ref_index = defaultdict(list)
    for ref in refs:
        ref_index[(ref.source_id, ref.task_id)].append(ref)
        path, locator = ref.source_path or [], ref.locator or ''
        evidence = {'source_id': ref.source_id, 'locator': locator, 'path': path}
        identity = variant_identity(ref.source_id, locator)
        if identity:
            key, title, variant, rule, labeled = identity
            add(key, f'{ref.source.title} · {title}', ref.task_id, evidence)
            if labeled:
                labeled_keys.add(key)
            work_variants.setdefault(key, (rule.pairs, defaultdict(set)))[1][variant].add(ref.task_id)
        elif ZIV_UNKNOWN_VARIANT.fullmatch(locator):
            ambiguous.append(f'Задача #{ref.task_id}: вариант не распознан ({locator}), сверить с книгой')
        elif any(SECTION.search(str(p)) for p in path):
            identity = bank_identity(ref.source_id, path, locator)
            if identity:
                key, number = identity
                add(key, f'{ref.source.title} · прототип {number}', ref.task_id, evidence)
            else:
                ambiguous.append(f'Задача #{ref.task_id}: не определён прототип ({" / ".join(path)})')

    collections = list(Collection.objects.filter(**source_filter).select_related('worksheet', 'source').prefetch_related(Prefetch('worksheet__items',
        queryset=WorksheetItem.objects.filter(deleted_at__isnull=True).select_related('task').order_by('order', 'pk'),
        to_attr='analog_items')))
    by_id = {c.pk: c for c in collections}
    for collection in collections:
        ancestors, current, visited = [], collection, set()
        while current and current.pk not in visited:
            visited.add(current.pk)
            ancestors.insert(0, current.worksheet.title)
            current = by_id.get(current.parent_id)
        path = list(collection.source_path or ancestors)
        context = path
        for item in collection.worksheet.analog_items:
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
    for key, (pairs, variants) in work_variants.items():
        # Пара вариантов (Зив, Высоцкий) — ровно два; все варианты работы
        # (Феоктистов, Шабунин, ДМ Мерзляка) — не меньше двух.
        if len(variants) != 2 if pairs else len(variants) < 2:
            if key in labeled_keys:
                incomplete.append(groups[key]['title'])
            groups.pop(key)
        elif any(len(ids) != 1 for ids in variants.values()):
            ambiguous.append(groups[key]['title'] + ': несколько задач одного исходного номера')
            groups.pop(key)
    return {key: value for key, value in groups.items() if len(value['members']) > 1}, incomplete, sorted(set(ambiguous))


# Ключ семьи Феоктистова, который до общих правил строился как пара Зива.
FEOKTISTOV_KEY = re.compile(r'variants:(\d+):(sr|kr)/(\d{2}):all:(\d{3})')


def sync_families(*, dry_run=False, report=False, source_id=None):
    groups, incomplete, ambiguous = discover_families(source_id=source_id)
    result = {'families': len(groups), 'created': 0, 'members_added': 0,
              'keys_updated': 0, 'incomplete': incomplete, 'ambiguous': ambiguous, 'dry_run': dry_run}
    # По источникам: найдено семей, из них новых, новых участников.
    by_source = defaultdict(lambda: {'families': 0, 'created': 0, 'members_added': 0})
    with transaction.atomic():
        # Старые ключи: банк не различал главы; Феоктистова ловило правило
        # Зива парой v1–v2 («ziv:ист:sr:01:0:001»; v3 без пары семьи не
        # давал). Переносим только однозначное семейство; ручных участников
        # сохраняем вместе с его идентификатором.
        legacy_targets = defaultdict(list)
        for key in groups:
            if key.startswith('bank:') and key.count(':') == 3:
                legacy_targets[key.rsplit(':', 1)[0]].append(key)
            elif match := FEOKTISTOV_KEY.fullmatch(key):
                legacy_targets['ziv:{}:{}:{}:0:{}'.format(*match.groups())].append(key)
        blocked = set()
        aliases = {}
        for old_key, targets in legacy_targets.items():
            old = Family.objects.select_for_update().filter(key=old_key).first()
            if not old:
                continue
            source_ids = set(old.familymember_set.filter(origin='source').values_list('task_id', flat=True))
            target = targets[0]
            if (len(targets) != 1 or old_key in groups or old.origin != 'source'
                    or not source_ids or not source_ids <= set(groups[target]['members'])
                    or Family.objects.filter(key=target).exists()):
                blocked.update(targets)
                blocked.add(old_key)
                result['ambiguous'].append(f'{old_key}: старое семейство требует ручного уточнения')
                continue
            result['keys_updated'] += 1
            aliases[target] = old
            if not dry_run:
                old.key = target
                old.save(update_fields=['key'])
        for key, group in groups.items():
            if key in blocked:
                continue
            family = aliases.get(key) or Family.objects.filter(key=key).first()
            counts = by_source[group['source_id']]
            counts['families'] += 1
            if family is None:
                result['created'] += 1
                counts['created'] += 1
                if not dry_run:
                    family = Family.objects.create(key=key, title=group['title'], origin='source')
            existing = {m.task_id: m for m in family.familymember_set.all()} if family else {}
            # Отвязанные редактором («Отвязать» в блоке «Аналоги») по
            # локатору не возвращаются (FamilyExclusion).
            excluded = (set(FamilyExclusion.objects.filter(family=family).values_list('task_id', flat=True))
                        if family else set())
            for task_id, evidence in group['members'].items():
                if task_id in excluded:
                    continue
                member = existing.get(task_id)
                if member is None:
                    result['members_added'] += 1
                    counts['members_added'] += 1
                    if not dry_run:
                        FamilyMember.objects.get_or_create(family=family, task_id=task_id,
                            defaults={'origin': 'source', 'evidence': evidence})
                elif not dry_run and member.origin == 'source':
                    combined = member.evidence + [e for e in evidence if e not in member.evidence]
                    if combined != member.evidence:
                        member.evidence = combined
                        member.save(update_fields=['evidence'])
    titles = dict(Source.objects.filter(pk__in=by_source).values_list('pk', 'title'))
    result['by_source'] = [{'id': pk, 'title': titles.get(pk, ''), **counts}
                           for pk, counts in sorted(by_source.items())]
    return result if report else result['families']

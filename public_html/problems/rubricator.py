"""Рубрикатор: сид справочника и назначение тем/меток задачам и листкам."""

import json
from decimal import Decimal

from django.db.models import Count, Q

from .models import (ExamItem, ExamModel, FacetType, FacetValue, GradeBand,
                     Task, TaskTopic, Topic)
from .rubricator_data import (BLOCKS, EXAM_MODELS, GRADE_BANDS, LEVELS,
                              METHODS)

GRADE_LEVEL_TO_CODE = {
    5: 'GRADE_5', 6: 'GRADE_6', 7: 'GRADE_7',
    8: 'GRADE_8', 9: 'GRADE_9', 10: 'GRADE_10_11', 11: 'GRADE_10_11',
}
CODE_TO_GRADE_LEVEL = {
    'GRADE_5': 5, 'GRADE_6': 6, 'GRADE_7': 7,
    'GRADE_8': 8, 'GRADE_9': 9, 'GRADE_10_11': 10,
}
GRADE_SHORT = {
    'GRADE_5': '5', 'GRADE_6': '6', 'GRADE_7': '7',
    'GRADE_8': '8', 'GRADE_9': '9', 'GRADE_10_11': '10–11',
}


def parse_grade_choice(value):
    """Пусто → (None, True); 11 → 10; иначе int из GRADE_CHOICES."""
    raw = (value or '').strip()
    if not raw:
        return None, True
    if raw == '11':
        return 10, True
    allowed = {str(g) for g, _ in Task.GRADE_CHOICES}
    if raw not in allowed:
        return None, False
    return int(raw), True


def known_topic_codes():
    codes = set()
    for block_code, _name, sections in BLOCKS:
        codes.add(block_code)
        for section_code, _sname, topics in sections:
            codes.add(section_code)
            for topic_code, _tname in topics:
                codes.add(topic_code)
    return codes


def seed_rubricator():
    """Создаёт или обновляет дерево, классы, фасеты и экзамены по коду.

    Старые темы без кода из прежнего seed_topics удаляются: у существующих
    задач связей с ними после миграции уже нет.
    """
    known = known_topic_codes()
    Topic.objects.filter(Q(code__isnull=True) | Q(code='')).delete()
    Topic.objects.exclude(code__in=known).delete()

    created_topics = 0
    for block_i, (block_code, block_name, sections) in enumerate(BLOCKS):
        block, was = Topic.objects.update_or_create(
            code=block_code,
            defaults={'name': block_name, 'parent': None, 'order': block_i})
        created_topics += was
        for sec_i, (section_code, section_name, topics) in enumerate(sections):
            section, was = Topic.objects.update_or_create(
                code=section_code,
                defaults={'name': section_name, 'parent': block,
                          'order': sec_i})
            created_topics += was
            for top_i, (topic_code, topic_name) in enumerate(topics):
                _, was = Topic.objects.update_or_create(
                    code=topic_code,
                    defaults={'name': topic_name, 'parent': section,
                              'order': top_i})
                created_topics += was

    for code, name, order in GRADE_BANDS:
        GradeBand.objects.update_or_create(
            code=code, defaults={'name': name, 'order': order})

    level_type, _ = FacetType.objects.update_or_create(
        code='LEVEL',
        defaults={'name': 'Уровень содержания',
                  'selection_mode': FacetType.MODE_MULTIPLE, 'order': 10})
    method_type, _ = FacetType.objects.update_or_create(
        code='METHOD',
        defaults={'name': 'Метод решения',
                  'selection_mode': FacetType.MODE_MULTIPLE, 'order': 20})
    for code, name, order in LEVELS:
        FacetValue.objects.update_or_create(
            facet_type=level_type, code=code,
            defaults={'name': name, 'order': order})
    for i, (code, name) in enumerate(METHODS):
        FacetValue.objects.update_or_create(
            facet_type=method_type, code=code,
            defaults={'name': name, 'order': i})

    for model_code, exam_type, year, name, items in EXAM_MODELS:
        model, _ = ExamModel.objects.update_or_create(
            code=model_code,
            defaults={'exam_type': exam_type, 'exam_year': year, 'name': name})
        for number, item_code, item_name in items:
            ExamItem.objects.update_or_create(
                code=item_code,
                defaults={'exam_model': model, 'item_number': number,
                          'name': item_name, 'order': number})

    return created_topics


def migrate_legacy_grades():
    """Переносит Task.grade_level и Worksheet.grade в GradeBand."""
    from worksheets.models import Worksheet

    bands = {b.code: b for b in GradeBand.objects.all()}
    for task in Task.objects.exclude(grade_level=None).iterator():
        code = GRADE_LEVEL_TO_CODE.get(task.grade_level)
        band = bands.get(code)
        if band and not task.grade_bands.exists():
            task.grade_bands.add(band)
    for worksheet in Worksheet.objects.exclude(grade=None).iterator():
        code = GRADE_LEVEL_TO_CODE.get(worksheet.grade)
        band = bands.get(code)
        if band and not worksheet.grade_bands.exists():
            worksheet.grade_bands.add(band)


def getlist(params, key):
    if hasattr(params, 'getlist'):
        return params.getlist(key)
    value = params.get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def parse_int_ids(values):
    ids = []
    for value in values:
        if value in (None, ''):
            continue
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def set_task_topics(task, topic_ids, primary_id=None):
    """Назначает темы.

    primary_id — основная; пустая строка — все дополнительные, без основной;
    None — если темы есть, первая становится основной (вызовы без виджета).
    """
    ids = []
    seen = set()
    for pk in parse_int_ids(topic_ids):
        if pk not in seen:
            seen.add(pk)
            ids.append(pk)
    existing = {t.pk: t for t in Topic.objects.filter(pk__in=ids)}
    ordered = [existing[pk] for pk in ids if pk in existing]
    auto_primary = primary_id is None
    if primary_id not in (None, ''):
        try:
            primary_id = int(primary_id)
        except (TypeError, ValueError):
            primary_id = None
            auto_primary = True
    else:
        primary_id = None
    if auto_primary and primary_id not in existing and ordered:
        primary_id = ordered[0].pk
    elif primary_id not in existing:
        primary_id = None
    TaskTopic.objects.filter(task=task).delete()
    for topic in ordered:
        is_primary = topic.pk == primary_id
        TaskTopic.objects.create(
            task=task, topic=topic,
            role=(TaskTopic.ROLE_PRIMARY if is_primary
                  else TaskTopic.ROLE_SECONDARY),
            relevance=Decimal('1.00') if is_primary else Decimal('0.50'))


def sync_grade_level(task, bands):
    levels = [CODE_TO_GRADE_LEVEL[b.code]
              for b in bands if b.code in CODE_TO_GRADE_LEVEL]
    task.grade_level = min(levels) if levels else None
    task.save(update_fields=['grade_level'])


def sync_worksheet_grade(worksheet, bands):
    levels = [CODE_TO_GRADE_LEVEL[b.code]
              for b in bands if b.code in CODE_TO_GRADE_LEVEL]
    worksheet.grade = min(levels) if levels else None
    worksheet.save(update_fields=['grade', 'updated_at'])


def set_grade_bands(obj, codes, *, sync_legacy=True):
    codes = [c for c in codes if c]
    bands = list(GradeBand.objects.filter(code__in=codes))
    obj.grade_bands.set(bands)
    if sync_legacy:
        if isinstance(obj, Task):
            sync_grade_level(obj, bands)
        else:
            sync_worksheet_grade(obj, bands)
    return bands


def set_task_facets(task, value_ids):
    values = FacetValue.objects.filter(pk__in=parse_int_ids(value_ids))
    task.facet_values.set(values)


def set_task_exams(task, item_ids):
    items = ExamItem.objects.filter(pk__in=parse_int_ids(item_ids))
    task.exam_items.set(items)


def apply_task_taxonomy(task, post):
    """Читает POST виджета: темы, классы, фасеты, экзамен, сложность."""
    if post.get('topics_submitted') or 'topics' in post or 'primary_topic' in post:
        set_task_topics(
            task, post.getlist('topics'), post.get('primary_topic'))
    if post.get('grades_submitted') or 'grade_bands' in post:
        set_grade_bands(task, post.getlist('grade_bands'))
    if post.get('facets_submitted') or 'facet_values' in post:
        set_task_facets(task, post.getlist('facet_values'))
    if post.get('exams_submitted') or 'exam_items' in post:
        set_task_exams(task, post.getlist('exam_items'))
    if 'difficulty' in post:
        raw = post.get('difficulty', '').strip()
        if raw and raw.isdigit() and int(raw) in range(1, 6):
            task.difficulty = int(raw)
        else:
            task.difficulty = None
        task.save(update_fields=['difficulty'])


def apply_worksheet_taxonomy(worksheet, post):
    if post.get('topics_submitted') or 'topics' in post:
        ids = parse_int_ids(post.getlist('topics'))
        worksheet.topics.set(Topic.objects.filter(pk__in=ids))
        worksheet.save(update_fields=['updated_at'])
    if post.get('grades_submitted') or 'grade_bands' in post:
        set_grade_bands(worksheet, post.getlist('grade_bands'))


def expand_topic_ids(raw_ids):
    """Родительский узел раскрывается во всех потомков (включая себя)."""
    ids = parse_int_ids(raw_ids)
    if not ids:
        return []
    expanded = set()
    for topic in Topic.objects.filter(pk__in=ids).prefetch_related('children'):
        expanded.update(topic.descendants_ids())
    return list(expanded)


def filter_by_taxonomy(qs, params, *, topics_lookups):
    """ИЛИ внутри фасета, И между фасетами.

    topics_lookups — список Q-аргументов (имя поля), куда подставить id тем,
    например ('topics',) или ('topics', 'items__task__topics').
    """
    topic_ids = expand_topic_ids(getlist(params, 'topic'))
    if topic_ids:
        topic_q = Q()
        for lookup in topics_lookups:
            topic_q |= Q(**{f'{lookup}__in': topic_ids})
        qs = qs.filter(topic_q).distinct()

    grades = [g for g in getlist(params, 'grade') if g]
    if grades:
        codes = []
        levels = []
        for g in grades:
            if g.startswith('GRADE_'):
                codes.append(g)
                if g == 'GRADE_10_11':
                    levels.extend([10, 11])
                elif g in CODE_TO_GRADE_LEVEL:
                    levels.append(CODE_TO_GRADE_LEVEL[g])
            elif g.isdigit():
                n = int(g)
                if n in (10, 11):
                    levels.extend([10, 11])
                    codes.append('GRADE_10_11')
                else:
                    levels.append(n)
                    code = GRADE_LEVEL_TO_CODE.get(n)
                    if code:
                        codes.append(code)
        grade_q = Q()
        if codes:
            grade_q |= Q(grade_bands__code__in=codes)
        if levels:
            if qs.model is Task:
                grade_q |= Q(grade_level__in=levels)
            else:
                grade_q |= Q(grade__in=levels)
        if grade_q:
            qs = qs.filter(grade_q).distinct()

    levels = [v for v in getlist(params, 'level') if v]
    if levels and qs.model is Task:
        qs = qs.filter(facet_values__code__in=levels).distinct()

    methods = parse_int_ids(getlist(params, 'method'))
    if methods and qs.model is Task:
        qs = qs.filter(facet_values__pk__in=methods).distinct()

    exams = [v for v in getlist(params, 'exam') if v]
    if exams and qs.model is Task:
        qs = qs.filter(exam_items__code__in=exams).distinct()

    return qs


def topic_counts(lookup='tasks'):
    """Число связанных объектов у каждой темы, включая потомков."""
    raw = dict(Topic.objects.annotate(n=Count(lookup, distinct=True))
               .values_list('pk', 'n'))
    by_parent = {}
    for topic in Topic.objects.all():
        by_parent.setdefault(topic.parent_id, []).append(topic)

    totals = {}

    def walk(topic):
        total = raw.get(topic.pk, 0)
        for child in by_parent.get(topic.pk, []):
            total += walk(child)
        totals[topic.pk] = total
        return total

    for root in by_parent.get(None, []):
        walk(root)
    return totals


def taxonomy_catalog():
    """JSON-дерево и справочники фасетов для виджета на странице."""
    from .models import topic_tree

    children_of = set(
        Topic.objects.exclude(parent=None)
        .values_list('parent_id', flat=True).distinct())
    counts = topic_counts()
    topics = []
    for topic in topic_tree():
        topics.append({
            'id': topic.pk,
            'code': topic.code or '',
            'name': topic.name,
            'parent': topic.parent_id,
            'depth': topic.depth,
            'leaf': topic.pk not in children_of,
            'count': counts.get(topic.pk, 0),
        })
    grades = [
        {**row, 'short': GRADE_SHORT.get(row['code'], row['name'])}
        for row in GradeBand.objects.values('id', 'code', 'name')]
    levels = list(FacetValue.objects.filter(facet_type__code='LEVEL')
                  .values('id', 'code', 'name'))
    methods = list(FacetValue.objects.filter(facet_type__code='METHOD')
                   .values('id', 'code', 'name'))
    exams = []
    for model in ExamModel.objects.prefetch_related('items'):
        exams.append({
            'id': model.pk,
            'code': model.code,
            'name': model.name,
            'items': list(model.items.values('id', 'code', 'name',
                                             'item_number')),
        })
    return {
        'topics': topics,
        'grades': grades,
        'levels': levels,
        'methods': methods,
        'exams': exams,
    }


def task_taxonomy_state(task):
    primary = task.topic_links.filter(role=TaskTopic.ROLE_PRIMARY).first()
    return {
        'topics': list(task.topics.values_list('pk', flat=True)),
        'primary': primary.topic_id if primary else None,
        'grades': list(task.grade_bands.values_list('code', flat=True)),
        'facets': list(task.facet_values.values_list('pk', flat=True)),
        'exams': list(task.exam_items.values_list('pk', flat=True)),
        'difficulty': task.difficulty,
    }


def dumps_state(state):
    return json.dumps(state, ensure_ascii=False)


def taxonomy_page_context(state=None):
    return {
        'taxonomy_catalog': taxonomy_catalog(),
        'selected_json': dumps_state(state or {
            'topics': [], 'primary': None, 'grades': [],
            'facets': [], 'exams': [], 'difficulty': None,
        }),
    }


def filter_state_from_params(params):
    topics = parse_int_ids(getlist(params, 'topic'))
    grades = [g for g in getlist(params, 'grade') if g]
    level_codes = [v for v in getlist(params, 'level') if v]
    method_ids = parse_int_ids(getlist(params, 'method'))
    facets = list(FacetValue.objects.filter(
        Q(code__in=level_codes) | Q(pk__in=method_ids)
    ).values_list('pk', flat=True))
    exam_codes = [v for v in getlist(params, 'exam') if v]
    exams = list(ExamItem.objects.filter(code__in=exam_codes)
                 .values_list('pk', flat=True))
    return {
        'topics': topics,
        'primary': None,
        'grades': grades,
        'facets': facets,
        'exams': exams,
        'difficulty': None,
    }


def worksheet_taxonomy_state(worksheet):
    return {
        'topics': list(worksheet.topics.values_list('pk', flat=True)),
        'primary': None,
        'grades': list(worksheet.grade_bands.values_list('code', flat=True)),
        'facets': [],
        'exams': [],
        'difficulty': None,
    }

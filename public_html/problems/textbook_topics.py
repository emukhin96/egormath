"""Сопоставление пути задачника с существующим деревом рубрикатора."""

import re
from difflib import SequenceMatcher

from .models import Topic
from .rubricator import getlist, parse_int_ids


_RAW_TOPIC_ALIASES = {
    'действия с целыми числами': 'ARI.02.06',
    'действия с дробями': 'ARI.03.04',
    'действия с корнями': 'ARI.05.01',
    'числовые выражения': 'ARI.01.06',
    'буквенные выражения': 'ALG.02.01',
    'действия с многочленами': 'ALG.02.02',
    'действия с алгебраическими дробями': 'ALG.02.14',
    'действия с иррациональными выражениями': 'ALG.02.06',
    'уравнения': 'ALG.03',
    'целые алгебраические уравнения': 'ALG.03.03',
    'дробно-рациональные уравнения': 'ALG.03.05',
    'иррациональные уравнения': 'ALG.03.07',
    'неравенства': 'ALG.04',
    'целые алгебраические неравенства': 'ALG.04.03',
    'дробно-рациональные неравенства': 'ALG.04.04',
    'иррациональные неравенства': 'ALG.04.06',
    'системы уравнений': 'ALG.03.11',
    'системы целых алгебраических уравнений': 'ALG.03.02',
    'системы рациональных уравнений': 'ALG.03.11',
    'системы иррациональных уравнений': 'ALG.03.11',
    'системы неравенств': 'ALG.04.02',
    'функции и графики': 'ALG.05',
    'чтение графиков': 'ALG.05.02',
    'построение графиков': 'ALG.05.03',
    'исследование функций': 'ALG.05.14',
    'текстовые задачи': 'ALG.09',
    'задачи на движение и работу': 'ALG.09.02',
    'задачи на проценты, части, доли': 'ARI.04.04',
    'прогрессии': 'ALG.06',
    'арифметическая прогрессия': 'ALG.06.02',
    'геометрическая прогрессия': 'ALG.06.03',
    'отрезки, углы, треугольники': 'GEO.02',
    'многоугольники': 'GEO.03',
    'окружности': 'GEO.04',
    'треугольники': 'GEO.02',
    'квадратные уравнения': 'ALG.03.03',
    'линейные уравнения': 'ALG.03.01',
    'теория вероятностей и статистика': 'STA',
    'задачи по теории вероятностей и статистике': 'STA',
    # Заголовки Зива / Гольдича → темы версии 1.2 (старые коды не менялись).
    'одночлены': 'ALG.02.11',
    'деление многочленов': 'ALG.02.09',
    'деление многочленов. решение алгебраических уравнений': 'ALG.02.09',
    'квадратный трехчлен': 'ALG.02.15',
    'степень с целым показателем': 'ALG.02.16',
    'степень с рациональным показателем': 'ALG.02.16',
    'степень с целым и рациональным показателем': 'ALG.02.16',
    'корень натуральной степени': 'ALG.02.17',
    'корень n-й степени': 'ALG.02.17',
    'тригонометрические тождества': 'ALG.02.18',
    'основные тригонометрические тождества': 'ALG.02.18',
    'формулы сложения': 'ALG.02.19',
    'формулы приведения': 'ALG.02.19',
    'формулы сложения. формулы приведения': 'ALG.02.19',
    'синус и косинус двойного угла': 'ALG.02.19',
    'формулы двойного угла': 'ALG.02.19',
    'неполные квадратные уравнения': 'ALG.03.13',
    'алгебраические уравнения': 'ALG.03.14',
    'алгебраические уравнения. системы алгебраических уравнений': 'ALG.03.14',
    'уравнения, сводящиеся к алгебраическим': 'ALG.03.14',
    'уравнения, сводящиеся к апгебраическим': 'ALG.03.14',
    'системы алгебраических уравнений': 'ALG.03.15',
    'системы уравнений второй степени': 'ALG.03.15',
    'системы нелинейных уравнений': 'ALG.03.11',
    'неравенства, содержащие степени': 'ALG.04.11',
    'неравенства, содержащие степень': 'ALG.04.11',
    'неравенства и уравнения, содержащие степень': 'ALG.04.11',
    'прямая пропорциональность': 'ALG.05.15',
    'функция y = kx': 'ALG.05.15',
    'четные и нечетные функции': 'ALG.05.16',
    'четность и нечетность функции': 'ALG.05.16',
    'четность и нечетность': 'ALG.05.16',
    'радианная мера угла': 'ALG.05.17',
    'числовая окружность': 'ALG.05.17',
    'степенная функция': 'ALG.05.07',
    'область определения функции': 'ALG.05.01',
    'возрастание и убывание функции': 'ALG.05.14',
    'область определения функции. возрастание и убывание функции': 'ALG.05.01',
    'обратные тригонометрические функции': 'ALG.05.18',
    'решение задач с помощью уравнений': 'ALG.09.01',
    'производная степенной и сложной функции': 'ALG.07.09',
    'клетчатая бумага': 'GEO.06',
    'задачи на клетчатой бумаге': 'GEO.06',
    'геометрические высказывания': 'GEO.01',
    'практические задачи': 'ARI.06',
    'маршруты': 'ARI.06',
    'шины': 'ARI.06',
    'участки': 'ARI.06',
    'листы': 'ARI.06',
    'печки': 'ARI.06',
    'квартиры': 'ARI.06',
    'тарифы': 'ARI.06',
    'дроби': 'ARI.03',
    'десятичные дроби': 'ARI.03.05',
    'обыкновенные дроби': 'ARI.03.04',
    'координатная прямая': 'ARI.03.07',
    'степени и корни': 'ARI.05',
    'вероятности': 'STA.03',
    'графики функций': 'ALG.05',
    'расчеты по формулам': 'ARI.06',
    'расчёты по формулам': 'ARI.06',
    'прогрессии': 'ALG.06',
    'окружности': 'GEO.04',
    'четырехугольники': 'GEO.03',
    'четырёхугольники': 'GEO.03',
    'построение графиков': 'ALG.05.03',
    'геометрические вычисления': 'GEO.02',
    'геометрические доказательства': 'GEO.02',
    'сложная геометрия': 'GEO.02',
    'геометрические задачи повышенной сложности': 'GEO.02',
    'окружность, круг и их элементы': 'GEO.04',
    'треугольники и их элементы': 'GEO.02',
    'выражения, уравнения и неравенства': 'ALG.03',
    'геометрические задачи на вычисление': 'GEO.02',
    'построение графиков функций': 'ALG.05.03',
    'геометрические задачи на доказательство': 'GEO.02',
    'анализ геометрических высказываний': 'GEO.01',
    'алгебраические задачи': 'ALG.03',
    # Мерзляк, геометрия 9 (углублённый уровень): однородные параграфы.
    # Смешанные §§ 24–26 получают общую ветвь, а не узкую подтему.
    'синус, косинус, тангенс и котангенс угла от 0° до 180°': 'GEO.02.07',
    'теорема косинусов': 'GEO.02.07',
    'теорема синусов': 'GEO.02.07',
    'решение треугольников': 'GEO.02.07',
    'формулы для нахождения площади треугольника': 'GEO.02.08',
    'правильные многоугольники и их свойства': 'GEO.03.05',
    'длина окружности. площадь круга': 'GEO.04.06',
    'расстояние между двумя точками с данными координатами. '
    'деление отрезка в данном отношении': 'GEO.06.01',
    'уравнение фигуры': 'GEO.06.03',
    'общее уравнение прямой': 'GEO.06.02',
    'уравнение прямой с угловым коэффициентом. уравнение прямой, '
    'проходящей через две данные точки': 'GEO.06.02',
    'метод координат': 'GEO.06.06',
    'понятие вектора': 'GEO.06.04',
    'координаты вектора': 'GEO.06.05',
    'сложение и вычитание векторов': 'GEO.06.04',
    'умножение вектора на число. применение векторов к решению задач':
        'GEO.06.04',
    'скалярное произведение векторов': 'GEO.06.05',
    'преобразование (отображение) фигур': 'GEO.05.06',
    'движение. параллельный перенос': 'GEO.05.02',
    'осевая симметрия': 'GEO.05.01',
    'центральная симметрия': 'GEO.05.01',
    'поворот': 'GEO.05.02',
    'гомотетия. подобие фигур': 'GEO.05.03',
    'прямая призма. пирамида': 'GEO.09',
    'цилиндр. конус. шар': 'GEO.10',
    '1. треугольники': 'GEO.02',
    '2. четырехугольники. многоугольники': 'GEO.03',
    '3. окружность и её элементы': 'GEO.04',
    '4. декартовы координаты. векторы': 'GEO.06',
    '5. геометрические преобразования': 'GEO.05',
}

_SERVICE_RE = re.compile(
    r'(?iu)^\s*(?:§+\s*\d+[.\)]?\s*|глава\s+\d+[.\)]?\s*|'
    r'тема\s+\d+[.\)]?\s*|приложение\s+\d+[.\)]?\s*)'
)
_PUNCT_RE = re.compile(r'[«»"“”„()[\],:;]+')
# В Зиве хвост пути — «Вариант N», а тип работы не тема рубрикатора.
_SERVICE_LABEL_RE = re.compile(
    r'(?iu)^(вариант\s+\d+|'
    r'контрольные(?:\s+работы)?|'
    r'самостоятельные(?:\s+работы)?|'
    r'проверочн(?:ая|ые)\s+работ(?:а|ы)?(?:\s*№?\s*\d+)?|'
    r'прототипы|аналоги|'
    r'ответы.*|указания.*|решения.*)$'
)
CANDIDATE_REASON_LABELS = {
    'exact-alias': 'точное совпадение',
    'exact-name': 'точное совпадение',
    'exact-path': 'точное совпадение',
    'parent-alias': 'по разделу',
    'parent-name': 'по разделу',
    'fuzzy-name': 'похожее название',
}


def normalize_topic_label(value):
    text = str(value or '').replace('ё', 'е').replace('Ё', 'Е')
    text = _SERVICE_RE.sub('', text)
    text = _PUNCT_RE.sub(' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


TOPIC_ALIASES = {
    normalize_topic_label(key): code
    for key, code in _RAW_TOPIC_ALIASES.items()
}


def _label_variants(label):
    """Полный заголовок и части после точки/точки с запятой."""
    variants = [label]
    for part in re.split(r'[.;]', label):
        fragment = normalize_topic_label(part)
        if fragment and fragment not in variants:
            variants.append(fragment)
    return variants


def is_service_topic_label(value):
    """«Вариант 1» и тип работы Зива не считаются темой рубрикатора."""
    return bool(_SERVICE_LABEL_RE.match(normalize_topic_label(value)))


def _meaningful_topic_labels(parts):
    labels = []
    for part in parts:
        label = normalize_topic_label(part)
        if label and not is_service_topic_label(label) and label not in labels:
            labels.append(label)
    return labels


def _topic_index():
    topics = list(
        Topic.objects.select_related('parent')
        .exclude(code__isnull=True).exclude(code=''))
    by_code = {topic.code: topic for topic in topics if topic.code}
    by_name = {}
    for topic in topics:
        key = normalize_topic_label(topic.name)
        if key:
            by_name.setdefault(key, []).append(topic)
        parent_name = normalize_topic_label(
            topic.parent.name if topic.parent_id else '')
        if key and parent_name:
            by_name.setdefault(f'{parent_name} / {key}', []).append(topic)
    return by_code, by_name, topics


def match_topic_candidates(source_path, topic_original='', limit=3,
                           index=None):
    """До трёх кандидатов; exact-alias/имя можно назначать автоматически."""
    by_code, by_name, topics = index or _topic_index()
    raw_parts = list(source_path or []) + [topic_original]
    labels = _meaningful_topic_labels(raw_parts)
    if not labels:
        return []
    leaf_labels = set()
    for part in reversed(raw_parts):
        label = normalize_topic_label(part)
        if label and not is_service_topic_label(label):
            leaf_labels.add(label)
            break

    ranked = {}

    def keep(topic, score, reason):
        candidate = {
            'id': topic.pk,
            'code': topic.code,
            'name': str(topic),
            'score': score,
            'reason': reason,
        }
        previous = ranked.get(topic.pk)
        if previous is None or candidate['score'] > previous['score']:
            ranked[topic.pk] = candidate

    for label in labels:
        is_leaf = label in leaf_labels
        for variant in _label_variants(label):
            full_match = variant == label
            use_leaf = is_leaf and full_match
            alias_code = TOPIC_ALIASES.get(variant)
            if alias_code and alias_code in by_code:
                keep(
                    by_code[alias_code],
                    1.0 if use_leaf else 0.92,
                    'exact-alias' if use_leaf else 'parent-alias')
            for topic in by_name.get(variant, []):
                keep(
                    topic,
                    1.0 if use_leaf else 0.9,
                    'exact-name' if use_leaf else 'parent-name')
        if is_leaf and len(labels) >= 2:
            compound = f'{labels[-2]} / {label}'
            for topic in by_name.get(compound, []):
                keep(topic, 1.0, 'exact-path')

    if not any(item['score'] == 1.0 for item in ranked.values()):
        target = labels[-1]
        scored = []
        for topic in topics:
            name = normalize_topic_label(topic.name)
            if not name:
                continue
            score = SequenceMatcher(None, target, name).ratio()
            if score >= 0.86:
                scored.append((score, topic))
        scored.sort(key=lambda item: (-item[0], item[1].code or ''))
        for score, topic in scored[:limit]:
            ranked.setdefault(topic.pk, {
                'id': topic.pk,
                'code': topic.code,
                'name': str(topic),
                'score': round(score, 3),
                'reason': 'fuzzy-name',
            })

    result = sorted(
        ranked.values(),
        key=lambda item: (-item['score'], item.get('code') or ''))
    return result[:limit]


def apply_topic_suggestions(drafts):
    """Записывает кандидатов; тему ставит только exact-совпадение."""
    index = _topic_index()
    candidates_by_path = {}
    for draft in drafts:
        # У сотен задач одного параграфа одинаковые входные данные.
        # Кэш живёт только в этой партии: изменения рубрикатора не теряются.
        key = (tuple(draft.source_path or []), draft.topic_original)
        if key not in candidates_by_path:
            candidates_by_path[key] = match_topic_candidates(
                draft.source_path, draft.topic_original, index=index)
        candidates = [dict(item) for item in candidates_by_path[key]]
        draft.topic_candidates = candidates
        exact = next((
            item for item in candidates
            if item['score'] == 1.0
            and item['reason'] in {'exact-alias', 'exact-name', 'exact-path'}
        ), None)
        if exact and not draft.topic_id:
            draft.topic_id = exact['id']
        stored = parse_int_ids(draft.topic_ids or [])
        if draft.topic_id and draft.topic_id not in stored:
            draft.topic_ids = [draft.topic_id] + stored
    return drafts


def draft_topic_ids(draft):
    """Все темы черновика: JSON плюс основная, если её ещё нет в списке."""
    ids = []
    seen = set()
    for pk in parse_int_ids(draft.topic_ids or []):
        if pk not in seen:
            seen.add(pk)
            ids.append(pk)
    if draft.topic_id and draft.topic_id not in seen:
        ids.insert(0, draft.topic_id)
    return ids


def set_draft_topics(draft, topic_ids, primary_id=None, save=True):
    """Пишет список тем и основную; пустой список снимает назначение."""
    ids = []
    seen = set()
    for pk in parse_int_ids(topic_ids):
        if pk not in seen:
            seen.add(pk)
            ids.append(pk)
    existing = set(
        Topic.objects.filter(pk__in=ids).values_list('pk', flat=True))
    ids = [pk for pk in ids if pk in existing]
    if primary_id not in (None, ''):
        try:
            primary_id = int(primary_id)
        except (TypeError, ValueError):
            primary_id = None
    else:
        primary_id = None
    if primary_id not in existing:
        primary_id = ids[0] if ids else None
    if primary_id:
        ids = [primary_id] + [pk for pk in ids if pk != primary_id]
    draft.topic_id = primary_id
    draft.topic_ids = ids
    if save and draft.pk:
        draft.save(update_fields=['topic', 'topic_ids'])
    return draft


def merge_draft_topics(draft, topic_ids, primary_id=None, save=True):
    """Добавляет темы к уже выбранным, не затирая основную."""
    current = draft_topic_ids(draft)
    incoming = parse_int_ids(topic_ids)
    combined = current + [pk for pk in incoming if pk not in current]
    keep_primary = draft.topic_id if draft.topic_id in combined else primary_id
    return set_draft_topics(draft, combined, keep_primary, save=save)


def topics_from_post(post):
    """Темы и основная из POST виджета; одиночное topic= — совместимость."""
    ids = parse_int_ids(getlist(post, 'topics'))
    if not ids:
        ids = parse_int_ids(getlist(post, 'topic'))
    primary = post.get('primary_topic')
    if primary in (None, ''):
        primary = ids[0] if ids else None
    else:
        try:
            primary = int(primary)
        except (TypeError, ValueError):
            primary = ids[0] if ids else None
        if primary not in ids:
            primary = ids[0] if ids else None
    return ids, primary


def suggested_topic_for_drafts(drafts):
    """Одна тема раздела: уже у всех, либо единственный не-fuzzy кандидат."""
    rows = list(drafts)
    if not rows:
        return None
    assigned = {draft.topic_id for draft in rows if draft.topic_id}
    if len(assigned) == 1 and all(draft.topic_id for draft in rows):
        return Topic.objects.filter(pk=next(iter(assigned))).first()
    found = {}
    index = None
    for draft in rows:
        candidates = draft.topic_candidates
        if not candidates:
            if index is None:
                index = _topic_index()
            candidates = match_topic_candidates(
                draft.source_path, draft.topic_original, index=index)
        for item in candidates:
            if item.get('reason') == 'fuzzy-name':
                continue
            topic_id = item.get('id')
            if topic_id:
                found[topic_id] = found.get(topic_id, 0) + 1
    if len(found) == 1:
        return Topic.objects.filter(pk=next(iter(found))).first()
    return None


def candidate_reason_label(reason):
    return CANDIDATE_REASON_LABELS.get(reason, reason or '')

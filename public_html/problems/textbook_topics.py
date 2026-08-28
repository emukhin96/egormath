"""Сопоставление пути задачника с существующим деревом рубрикатора."""

import re
from difflib import SequenceMatcher

from .models import Topic


TOPIC_ALIASES = {
    'действия с целыми числами': 'ARI.02.06',
    'действия с дробями': 'ARI.03.04',
    'действия с корнями': 'ARI.05.01',
    'числовые выражения': 'ARI.01.06',
    'буквенные выражения': 'ALG.02.01',
    'действия с многочленами': 'ALG.02.02',
    'действия с алгебраическими дробями': 'ALG.02.05',
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
    'отрезки, углы, треугольники': 'GEO.02',
    'многоугольники': 'GEO.03',
    'окружности': 'GEO.04',
    'треугольники': 'GEO.02',
    'квадратные уравнения': 'ALG.03.03',
    'линейные уравнения': 'ALG.03.01',
    'теория вероятностей и статистика': 'STA',
    'задачи по теории вероятностей и статистике': 'STA',
}

_SERVICE_RE = re.compile(
    r'(?iu)^\s*(?:§+\s*\d+[.\)]?\s*|глава\s+\d+[.\)]?\s*|'
    r'тема\s+\d+[.\)]?\s*|приложение\s+\d+[.\)]?\s*)'
)
_PUNCT_RE = re.compile(r'[«»"“”„()[\],:;]+')


def normalize_topic_label(value):
    text = str(value or '').replace('ё', 'е').replace('Ё', 'Е')
    text = _SERVICE_RE.sub('', text)
    text = _PUNCT_RE.sub(' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def _topic_index():
    topics = list(Topic.objects.exclude(code__isnull=True).exclude(code=''))
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
    labels = []
    for part in list(source_path or []) + [topic_original]:
        label = normalize_topic_label(part)
        if label and label not in labels:
            labels.append(label)
    if not labels:
        return []
    leaf_labels = set()
    if source_path:
        leaf = normalize_topic_label(source_path[-1])
        if leaf:
            leaf_labels.add(leaf)
    original = normalize_topic_label(topic_original)
    if original:
        leaf_labels.add(original)

    ranked = {}
    for label in labels:
        is_leaf = label in leaf_labels
        alias_code = TOPIC_ALIASES.get(label)
        if alias_code and alias_code in by_code:
            topic = by_code[alias_code]
            ranked[topic.pk] = {
                'id': topic.pk,
                'code': topic.code,
                'name': str(topic),
                'score': 1.0 if is_leaf else 0.92,
                'reason': 'exact-alias' if is_leaf else 'parent-alias',
            }
        for topic in by_name.get(label, []):
            ranked.setdefault(topic.pk, {
                'id': topic.pk,
                'code': topic.code,
                'name': str(topic),
                'score': 1.0 if is_leaf else 0.9,
                'reason': 'exact-name' if is_leaf else 'parent-name',
            })
        if is_leaf and len(labels) >= 2:
            compound = f'{labels[-2]} / {label}'
            for topic in by_name.get(compound, []):
                ranked.setdefault(topic.pk, {
                    'id': topic.pk,
                    'code': topic.code,
                    'name': str(topic),
                    'score': 1.0,
                    'reason': 'exact-path',
                })

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
    for draft in drafts:
        candidates = match_topic_candidates(
            draft.source_path, draft.topic_original, index=index)
        draft.topic_candidates = candidates
        exact = next((
            item for item in candidates
            if item['score'] == 1.0
            and item['reason'] in {'exact-alias', 'exact-name', 'exact-path'}
        ), None)
        if exact and not draft.topic_id:
            draft.topic_id = exact['id']
    return drafts

"""Метки проекта ЕГЭ-2027 и безопасные тематические разделы банка."""
import re

SECTION_TOPICS = {
    1: 'GEO', 2: 'GEO.06', 3: 'GEO', 4: 'STA.03', 5: 'STA.04',
    6: 'STA.06', 7: 'ALG.03', 8: 'ALG.02', 9: 'ALG.07',
    10: 'ALG.09', 11: 'ALG.09', 12: 'ALG.05', 13: 'ALG.09.06',
    14: 'ALG.03', 15: 'GEO', 16: 'ALG.04', 17: 'ALG.07.05',
    18: 'GEO', 19: 'ALG.08', 20: 'ARI',
}


def apply_ege_metadata(draft, profile):
    """Книжный номер определяет линию, а не случайную метку из JSON."""
    if profile != 'ostromogilsky_ege':
        return False
    match = re.fullmatch(r'(\d+)\.\d+(?:\.\d+)?', draft.external_id)
    if not match or int(match[1]) not in SECTION_TOPICS:
        raise ValueError(f'{draft.external_id}: неизвестный номер задания ЕГЭ')
    number = int(match[1])
    codes = [f'EGE_PROFILE_2027_{number:02d}']
    grades = ['GRADE_10_11']
    changed = codes != draft.exam_item_codes or grades != draft.grade_band_codes
    draft.exam_item_codes, draft.grade_band_codes = codes, grades
    return changed


def apply_ege_topics(drafts):
    """Заполняет только пустую тему по однозначному широкому разделу книги."""
    from .models import Topic
    by_code = {t.code: t for t in Topic.objects.filter(code__in=SECTION_TOPICS.values())}
    for draft in drafts:
        if draft.topic_id:
            continue
        topic = by_code.get(SECTION_TOPICS.get(int(draft.external_id.split('.')[0])))
        if topic is None:
            continue
        draft.topic_id = topic.pk
        draft.topic_ids = [topic.pk]
        draft.topic_candidates = [{'id': topic.pk, 'code': topic.code, 'name': str(topic),
                                   'score': 1.0, 'reason': 'exact-alias'}]

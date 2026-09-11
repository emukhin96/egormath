"""Экзаменационные метки и содержательные теги банка ОГЭ."""
import re

PARAMETER_TAG = 'задача с параметром'
GRAPH_TAG = 'построение графика'
PROOF_TAG = 'геометрическая задача на доказательство'
TAGS_BY_NUMBER = {22: (PARAMETER_TAG, GRAPH_TAG), 24: (PROOF_TAG,)}


def apply_oge_metadata(draft, profile):
    """Дополнить метаданные, сохраняя исходные и редакторские теги."""
    codes = list(draft.exam_item_codes or [])
    if profile == 'ostromogilsky':
        match = re.fullmatch(r'([0-9]+)\.[0-9]+(?:\.[0-9]+)?', draft.external_id)
        if not match or not 1 <= int(match[1]) <= 25:
            raise ValueError(f'{draft.external_id}: неизвестный номер задания ОГЭ')
        expected = f'OGE_2026_{int(match[1]):02d}'
        codes = [c for c in codes if not c.startswith('OGE_')] + [expected]
    tags = list(draft.tags or [])
    for code in codes:
        match = re.fullmatch(r'OGE_[0-9]{4}_([0-9]{2})', code)
        if match:
            for tag in TAGS_BY_NUMBER.get(int(match[1]), ()):
                if tag not in tags:
                    tags.append(tag)
    changed = codes != draft.exam_item_codes or tags != draft.tags
    draft.exam_item_codes, draft.tags = codes, tags
    return changed

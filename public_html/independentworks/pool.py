"""Занятые задачи и подпункты в составе самостоятельной."""
from .models import Candidate
from .services import WorkError


def usage(position, task, candidates=None):
    rows = list(candidates if candidates is not None else
                Candidate.objects.filter(position__work=position.work, task=task))
    current = any(c.position_id == position.pk for c in rows)
    whole = any(not c.subitem_ids for c in rows)
    used = set(i for c in rows for i in c.subitem_ids)
    all_parts = set(s.pk for s in task.subitems.all())
    return {'blocked': current or whole or bool(rows and all_parts <= used),
            'partial': bool(rows) and not (current or whole or all_parts <= used),
            'used': used, 'rows': rows}


def validate_selection(position, task, ids, candidate=None):
    rows = list(Candidate.objects.filter(position__work=position.work, task=task))
    if candidate:
        rows = [c for c in rows if c.pk != candidate.pk]
    state = usage(position, task, rows)
    if state['blocked'] or (state['rows'] and (not ids or state['used'].intersection(ids))):
        raise WorkError('Задача или выбранные подпункты уже используются в самостоятельной. Измените существующего кандидата.')

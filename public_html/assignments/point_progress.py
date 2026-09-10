"""Статусы и история самопроверки отдельного пункта листка."""
from types import SimpleNamespace

from .models import SubmissionCheckAttempt


def point_progress(submission, owner, *, is_part=False, enabled=True, with_fragments=False):
    obj = next((p for p in submission.parts.all() if p.subitem_id == owner.pk), None) if submission and is_part else submission
    history = []
    previous = None
    if submission:
        for attempt in sorted(submission.check_history.all(), key=lambda a: (a.number, a.pk)):
            target = next((t for t in attempt.snapshot.get('targets', [])
                           if t.get('kind') == ('subitem' if is_part else 'task') and t.get('id') == owner.pk), None)
            # Общий старый результат не позволяет восстановить результат подпункта.
            if target is None:
                if is_part:
                    continue
                target = {'answer': '', 'result': attempt.result}
            if is_part and not (target.get('answer') or any(s.get('value') for s in target.get('slots', []))):
                continue
            signature = (target.get('answer'), target.get('result'), repr(target.get('slots', [])))
            # Проверка соседнего пункта не увеличивает число попыток этого.
            if is_part and target.get('answer') and signature == previous:
                continue
            previous = signature
            result = target.get('result') or 'unknown'
            history.append(SimpleNamespace(number=len(history) + 1, created_at=attempt.created_at,
                result=result, snapshot={'targets': [target]},
                get_result_display=dict(SubmissionCheckAttempt.RESULT_CHOICES).get(result, 'Не определено')))
    latest = history[-1] if history else None
    answer = obj.display_answer if obj else ''
    started = bool(answer or (submission and not is_part and submission.photos.all()))
    checked_answer = latest.snapshot['targets'][0].get('answer', '') if latest else ''
    current = bool(latest and (checked_answer == answer or not checked_answer))
    status = latest.result if enabled and latest else ('draft' if started else 'empty')
    if status not in ('ok', 'wrong', 'draft', 'empty'):
        status = 'unknown'
    labels = {'ok': 'Верно', 'wrong': 'Неверно', 'draft': 'Введено, не проверено',
              'empty': 'Не начато', 'unknown': 'Не удалось проверить'}
    return {'status': status, 'label': labels[status], 'attempt_count': len(history),
            'current_changed': bool(latest and not current), 'history': list(reversed(history)), 'answer': answer, 'obj': obj,
            'fragments': obj.mask_fragments('progress', for_teacher=True) if with_fragments and obj and obj.has_mask_values else []}

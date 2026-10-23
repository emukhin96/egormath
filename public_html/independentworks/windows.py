"""Окно «задание у ученика» на прогрессе самостоятельной (макет D_AnswerView,
22.10.2026) — то же, что «задача у ученика» карты ответов листка
(assignments/windows.py): условие, последний ответ с автосверкой, ответ и
решение, история; справа копирование в этом задании, оценка и комментарий,
переходы к соседнему ученику и к соседнему заданию."""
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from accounts.decorators import teacher_required
from assignments.checks import parse_mask
from assignments.models import Review
from assignments.windows import grade_caption, reference_fragments, task_copies
from .models import Point
from . import services as svc
from .views import enabled, own_attempt, point_rows


def _name(attempt):
    return attempt.student.get_full_name() or attempt.student.username


def _url(attempt, point):
    return reverse('independentworks:point_detail', args=[attempt.pk, point.pk])


def point_status(answer):
    """ok / wrong / draft / empty — как ячейка таблицы прогресса."""
    if answer is None or not (answer.values or answer.photos.all()):
        return 'empty'
    if answer.grade:
        return 'ok' if answer.credit == 1 else 'draft' if answer.credit else 'wrong'
    return {'ok': 'ok', 'wrong': 'wrong'}.get(answer.auto_check, 'draft')


def neighbours(attempt, point):
    """Соседние ученики того же запуска с этим же номером в своём варианте
    (варианты разные — ищем пункт по позиции и части)."""
    attempts = list(attempt.run.attempts.select_related('student', 'variant')
                    .order_by('student__last_name', 'student__username', 'pk'))
    same = dict(Point.objects.filter(variant__in=[a.variant_id for a in attempts], position=point.position,
                                     part=point.part).values_list('variant_id', 'pk'))
    attempts = [a for a in attempts if a.variant_id in same]
    index = next(n for n, a in enumerate(attempts) if a.pk == attempt.pk)
    result = {}
    for key, other in (('prev_student', attempts[index - 1] if index else None),
                       ('next_student', attempts[index + 1] if index + 1 < len(attempts) else None)):
        if other:
            result[key] = {'name': _name(other), 'url': reverse('independentworks:point_detail', args=[other.pk, same[other.variant_id]])}
    return result


@enabled
@teacher_required
def point_window(request, pk, point_id):
    attempt = own_attempt(request, pk, teacher=True)
    svc.finish_expired(attempt)
    rows = point_rows(attempt, teacher=True)
    index = next((n for n, r in enumerate(rows) if r['point'].pk == point_id), None)
    if index is None:
        raise Http404
    row = rows[index]
    row['number'] = row['point'].label  # подпись шкалы оценок (_grade_scale.html)
    point, answer = row['point'], row['answer']
    spec = parse_mask(point.snapshot['mask'])
    copies = task_copies(None, point.label, attempt=attempt)
    checks = list(answer.check_history.all()) if answer else []
    for check in checks:
        check.values_text = ', '.join(str(v) for v in check.snapshot.get('values', {}).values() if v != '')
    return render(request, 'independentworks/_point_window.html', {
        'attempt': attempt, 'row': row, 'total': len(rows),
        'student_name': _name(attempt),
        'status': point_status(answer),
        'checks': checks,
        'reference': reference_fragments(spec, f'reference_p{point.pk}') if spec.is_valid else [],
        'copies': copies, 'copied': any(c['words'] > 1 for c in copies),
        'grade_choices': [('', 'По автосверке', '↺')] + Review.grade_options(),
        'grade_caption': grade_caption(answer),
        **neighbours(attempt, point),
        **{key: {'label': rows[i]['point'].label, 'url': _url(attempt, rows[i]['point'])}
           for key, i in (('prev_task', index - 1), ('next_task', index + 1)) if 0 <= i < len(rows)},
    })

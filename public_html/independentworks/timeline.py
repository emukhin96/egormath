"""Работа ученика в самостоятельной глазами учителя — по макету D_Timeline,
как хронология ученика в листке (assignments/timeline.py): дорожка работы,
ответы с эталоном и оценкой, лента событий. Строка ответа и оценка
открывают окно «задание у ученика» (point_detail), где ставят оценку и
пишут комментарий."""
import re

from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from assignments.checks import parse_mask, render_fragments
from assignments.models import Review
from assignments.timeline import activity_events, finish_events
from workaudit.models import ActivityEvent
from workaudit.services import copied_words, copy_label
from . import services as svc
from .views import group_point_rows, point_rows

RESULTS = {'ok': 'верно', 'wrong': 'неверно'}


def reference(point):
    """Эталон маски полями с эталонными значениями (как в окне задачи).
    Эталон промежутка и множества записан LaTeX'ом — поле маски показало бы
    его сырой строкой: для них пусто, шаблон покажет текст ответа."""
    spec = parse_mask(point.snapshot['mask'])
    if not spec.is_valid or not spec.slots or any(s.kind in ('range', 'set') for s in spec.slots):
        return []
    values = {slot.name: ('|'.join(str(i) for i in range(len(slot.items))) if slot.kind == 'order' else slot.reference)
              for slot in spec.slots}
    return render_fragments(spec, f'tl_ref_{point.pk}', values=values)


def point_copies(copies, label):
    """Копирования из условия этого задания (метка «3» или «3а»)."""
    pattern = re.compile(rf'^{re.escape(str(label))}(\D|$)')
    return [c for c in copies if any(pattern.match(str(part.get('label', ''))) for part in c['event'].statements)]


def attempt_timeline(request, attempt):
    rows = group_point_rows(point_rows(attempt, teacher=True))
    activity = ActivityEvent.objects.filter(attempt=attempt)
    copies = [{'event': e, 'label': copy_label(e), 'words': copied_words(e)}
              for e in activity.filter(kind='copy').order_by('received_at')]
    pending = []
    for row in rows:
        answer = row['answer']
        mine = point_copies(copies, row['point'].label)
        photos = len(answer.photos.all()) if answer else 0
        row['answered'] = bool(answer and (answer.values or photos))
        notes = []
        if mine:
            notes.append(mine[-1]['label'])
        if photos:
            notes.append(f'фото решения: {photos}')
        if not row['answered']:
            notes.append('не решал')
        row['note'] = ', '.join(notes)
        row['copied'] = any(c['words'] > 1 for c in mine)
        row['ref'] = reference(row['point'])
        row['window_url'] = reverse('independentworks:point_detail', args=[attempt.pk, row['point'].pk])
        row['mark'] = ('ok' if row['auto'] == 'ok' else 'wrong' if row['auto'] == 'wrong' else 'draft') if row['answered'] else ''
        graded = bool(answer and answer.grade)
        row['grade_title'] = dict(Review.GRADE_CHOICES).get(answer.grade, '') if graded else ''
        row['grade_tone'] = ('' if not graded else 'good' if answer.credit >= .75 else 'half' if answer.credit >= .5 else 'bad')
        row['needs_grade'] = attempt.finished and row['pending'] and row['answered']
        if row['needs_grade']:
            pending.append(row['point'].label)

    # Лента: журнал активности, самопроверки, фото, блокировка, сдача
    events, summary = activity_events(activity)
    for row in rows:
        answer, label = row['answer'], row['point'].label
        if not answer:
            continue
        for check in answer.check_history.all():
            values = ', '.join(str(v) for v in check.snapshot.get('values', {}).values() if v != '') or '—'
            events.append({'at': check.created_at, 'kind': check.result if check.result in RESULTS else 'check',
                           'text': f'Задание {label}: {values}', 'detail': RESULTS.get(check.result, 'проверка')})
        for photo in answer.photos.all():
            events.append({'at': photo.created_at, 'kind': 'photo', 'text': f'Загрузил фото к заданию {label}', 'detail': ''})
    if attempt.locked_at:
        events.append({'at': attempt.locked_at, 'kind': 'away', 'text': 'Задания заблокированы', 'detail': 'ушёл со страницы', 'seconds': None})
    empty = [r['point'].label for r in rows if not r['answered']]
    gap = ('без ответа: ' + ', '.join(empty)) if empty else ''
    if attempt.submitted_at:
        events.append({'at': attempt.submitted_at, 'kind': 'submit', 'text': 'Сдал работу', 'detail': gap})
    elif attempt.finished:
        events.append({'at': attempt.ends_at, 'kind': 'submit', 'text': 'Время вышло', 'detail': gap})
    events, track = finish_events(events, summary, start=attempt.started_at) if attempt.started_at else ([], None)

    result = svc.result(attempt)
    cumulative = svc.cumulative(attempt)
    return render(request, 'independentworks/timeline.html', {
        'attempt': attempt, 'rows': rows, 'events': events, 'track': track, 'result': result,
        'cumulative': cumulative if attempt.root_id or attempt.corrections.exists() else None,
        'pending': pending, 'locked': bool(attempt.locked_at) and not attempt.finished,
        'student_name': attempt.student.get_full_name() or attempt.student.username,
        'copied': any(c['words'] > 1 for c in copies), 'now': timezone.now(),
    })

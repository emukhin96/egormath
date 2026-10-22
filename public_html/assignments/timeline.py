"""Хронология работы одного ученика (макет D_Timeline, 22.10.2026): дорожка
работы (на странице, вне страницы, копирование и вставка, неверные
самопроверки), таблица ответов с эталоном и оценкой, лента событий по
времени. Источники — журнал активности (workaudit.activity_timeline),
история самопроверок, фото решений и момент сдачи."""
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from accounts.decorators import teacher_required
from workaudit.models import ActivityEvent
from workaudit.services import activity_timeline, format_span
from .models import Review
from .views import _teacher_assignment
from .windows import reference_for, task_copies

RESULTS = {'ok': 'верно', 'wrong': 'неверно'}


def _percent(moment, start, total):
    return max(0, min(100, round(100 * (moment - start).total_seconds() / total, 2)))


def _duration(seconds):
    """«24 ч 09 мин», «25 мин», «меньше минуты» — длительность для шапки."""
    minutes = round(seconds / 60)
    if minutes < 1:
        return 'меньше минуты'
    if minutes < 60:
        return f'{minutes} мин'
    hours, minutes = divmod(minutes, 60)
    return f'{hours} ч {minutes:02d} мин'


def _answer_text(target):
    return target.get('readable_answer') or target.get('answer') or '—'


@teacher_required
@never_cache
def assignment_timeline(request, pk):
    from .progress import live_summary, progress_assignments, progress_groups, progress_people
    assignment = _teacher_assignment(request, pk)
    assignments = progress_assignments(type(assignment).objects.filter(pk=assignment.pk))
    assignment = assignments.get()
    hidden = {i.pk for i in assignment.hidden_items.all()}
    items = [i for i in assignment.worksheet.ordered_items().filter(task__isnull=False) if i.pk not in hidden]
    groups = progress_groups(items, assignments)
    people = progress_people(groups, assignments)
    live_summary(groups, people)
    person = people[0]

    # Таблица ответов: номер — как у ученика (без скрытых пунктов)
    rows, start = [], 0
    for group in groups:
        cells = person['cells'][start:start + len(group['columns'])]
        start += len(group['columns'])
        for cell in cells:
            obj = cell['obj']
            cell['shown'] = obj.mask_fragments(f'tl_{obj.pk}', for_teacher=True) if obj and obj.has_mask_values else None
        item, task = group['item'], group['item'].task
        review = cells[0]['review']
        submission = next((s for s in assignment.submissions.all() if s.task_id == task.pk), None)
        photos = len(submission.photos.all()) if submission else 0
        copies = task_copies(assignment, group['number'])
        answered = any(c['status'] != 'empty' for c in cells)
        notes = []
        if copies:
            notes.append(copies[-1]['label'])
        if photos:
            notes.append(f'фото решения: {photos}')
        if not answered:
            notes.append('не решал')
        rows.append({'number': group['number'], 'item': item, 'task': task, 'cells': cells, 'review': review,
                     'answered': answered, 'pending': answered and not (review and review.grade),
                     'copied': any(c['words'] > 1 for c in copies), 'note': ', '.join(notes),
                     'reference': [] if item.selected_subitems() else reference_for(task, f'tl_ref_{item.pk}'),
                     'grade_title': dict(Review.GRADE_CHOICES).get(review.grade, '') if review and review.grade else '',
                     'grade_tone': ('' if not (review and review.grade) else 'good' if review.credit >= .75
                                    else 'half' if review.credit >= .5 else 'bad'),
                     'window_url': reverse('task_attempts', args=[assignment.pk, task.pk]) + f'?item={item.pk}',
                     'task_window_url': reverse('worksheet_task_window', args=[assignment.worksheet_id, item.pk])})
    numbers = {row['task'].pk: row['number'] for row in rows}

    # Лента событий
    activity, summary = activity_timeline(ActivityEvent.objects.filter(assignment=assignment))
    events = []
    for row in activity:
        if row['kind'] == 'away':
            if row['short']:
                continue
            detail = ('не вернулся' if row.get('open_ended') else 'время ухода неизвестно') if row['seconds'] is None \
                else 'вернулся через ' + format_span(row['seconds'])
            events.append({'at': row['at'], 'kind': 'away', 'text': 'Ушёл со страницы', 'detail': detail, 'seconds': row['seconds']})
        else:
            text = row['label'][:1].upper() + row['label'][1:]
            detail = f'«{row["text"][:120]}»' if row['text'] else ''
            if row['blocked']:
                detail = (detail + ', ' if detail else '') + 'заблокировано'
            events.append({'at': row['at'], 'kind': 'clipboard', 'text': text, 'detail': detail})
    for submission in assignment.submissions.all():
        number = numbers.get(submission.task_id)
        if number is None:
            continue
        for attempt in submission.check_history.all():
            targets = attempt.snapshot.get('targets', [])
            answer = '; '.join(_answer_text(t) for t in targets) or '—'
            events.append({'at': attempt.created_at, 'kind': attempt.result if attempt.result in RESULTS else 'check',
                           'text': f'Задача {number}: {answer}', 'detail': RESULTS.get(attempt.result, 'проверка')})
        for photo in submission.photos.all():
            events.append({'at': photo.uploaded_at, 'kind': 'photo', 'text': f'Загрузил фото к задаче {number}', 'detail': ''})
    if assignment.submitted_at:
        empty = [str(r['number']) for r in rows if not r['answered']]
        events.append({'at': assignment.submitted_at, 'kind': 'submit', 'text': 'Сдал работу',
                       'detail': ('без ответа: ' + ', '.join(empty)) if empty else ''})
    events.sort(key=lambda e: e['at'])
    if events and events[0]['kind'] != 'submit':
        events.insert(0, {'at': events[0]['at'], 'kind': 'start', 'text': 'Начал работу', 'detail': ''})

    # Дорожка: от первого события до сдачи (или последнего события)
    track = None
    if events:
        begin = events[0]['at']
        end = assignment.submitted_at or max(e['at'] for e in events)
        total = max((end - begin).total_seconds(), 60)
        segments = []
        for e in events:
            if e['kind'] == 'away' and e['seconds']:
                segments.append({'kind': 'away', 'left': _percent(e['at'], begin, total),
                                 'width': max(0.6, round(100 * e['seconds'] / total, 2))})
            elif e['kind'] in ('clipboard', 'wrong'):
                segments.append({'kind': e['kind'], 'left': _percent(e['at'], begin, total)})
        ticks = [begin + (end - begin) * k / 4 for k in range(5)]
        # работа дольше суток (открыл вечером, сдал утром) — у отметок дата
        days = timezone.localtime(begin).date() != timezone.localtime(end).date()
        track = {'begin': begin, 'end': end, 'segments': segments, 'ticks': ticks, 'days': days,
                 'duration': _duration(total), 'away': _duration(summary['away_seconds']) if summary['away_seconds'] >= 60 else ''}

    result = assignment.result()
    return render(request, 'assignments/timeline.html', {
        'assignment': assignment, 'person': person, 'rows': rows, 'events': events, 'track': track,
        'summary': summary, 'result': result, 'pending': [r['number'] for r in rows if r['pending']],
        'student_name': assignment.student.get_full_name() or assignment.student.username,
        'copied': person['copied'], 'now': timezone.now(),
    })

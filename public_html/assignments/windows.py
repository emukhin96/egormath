"""Окна карты ответов (макеты D_TaskView и D_AnswerView, 22.10.2026):
«задача» — условие, маска глазами ученика, эталон и как её решает класс;
«задача у ученика» — ответ, история, копирование в этой задаче, оценка и
комментарий, переходы к соседнему ученику и к соседней задаче."""
import re
from collections import Counter

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from accounts.decorators import teacher_required
from accounts.models import StudentGroup
from worksheets.latex import subitem_label
from worksheets.models import Worksheet
from workaudit.models import ActivityEvent
from workaudit.services import copied_words, copy_label
from .checks import render_fragments
from .models import Assignment, Review


def _name(assignment):
    return assignment.student.get_full_name() or assignment.student.username


def _student_url(assignment, item):
    return reverse('task_attempts', args=[assignment.pk, item.task_id]) + f'?item={item.pk}'


def reference_for(owner, prefix='reference'):
    """Эталон маски полями «так видит ученик» с эталонными значениями
    (как предпросмотр ответа в редакторе, problems/editor.py) — фрагменты
    для _mask.html; без маски — пустой список."""
    spec = owner.mask_spec
    if spec is None or not spec.is_valid or not spec.slots:
        return []
    values = {slot.name: ('|'.join(str(i) for i in range(len(slot.items))) if slot.kind == 'order' else slot.reference)
              for slot in spec.slots}
    return render_fragments(spec, f'{prefix}_{owner.pk}', values=values)


def grade_caption(review):
    """«–+ существенное продвижение, 0%» — подпись к выбранной оценке."""
    if not review or not review.grade:
        return ''
    label = dict(Review.GRADE_CHOICES)[review.grade]
    return f'{review.grade_symbol} {label.lower()}, {round(100 * review.credit)}%'


def task_copies(assignment, number):
    """Копирования из условия этой задачи (метка условия «3» или «3а»)."""
    pattern = re.compile(rf'^{re.escape(str(number))}(\D|$)')
    rows = []
    for event in ActivityEvent.objects.filter(assignment=assignment, kind='copy').order_by('received_at'):
        if any(pattern.match(str(part.get('label', ''))) for part in event.statements):
            rows.append({'event': event, 'label': copy_label(event), 'words': copied_words(event)})
    return rows


def student_window(assignment, item, row):
    """Контекст «задачи у ученика» поверх строки _assignment_rows."""
    visible = [i for i in assignment.worksheet.ordered_items().filter(task__isnull=False)
               if i.pk not in {h.pk for h in assignment.hidden_items.all()}]
    index = next(n for n, i in enumerate(visible) if i.pk == item.pk)
    neighbours = {'prev_task': visible[index - 1] if index else None,
                  'next_task': visible[index + 1] if index + 1 < len(visible) else None}
    tasks = {key: {'number': index + (1 if key == 'next_task' else -1) + 1, 'url': _student_url(assignment, i)}
             for key, i in neighbours.items() if i}
    classmates = list(Assignment.objects.filter(worksheet=assignment.worksheet)
                      .exclude(hidden_items=item).select_related('student')
                      .order_by('student__last_name', 'student__username', 'pk'))
    position = next(n for n, a in enumerate(classmates) if a.pk == assignment.pk)
    students = {}
    if position:
        students['prev_student'] = classmates[position - 1]
    if position + 1 < len(classmates):
        students['next_student'] = classmates[position + 1]
    copies = task_copies(assignment, row['number'])
    return {
        'total': len(visible),
        'student_name': _name(assignment),
        **{key: {'number': value['number'], 'url': value['url']} for key, value in tasks.items()},
        **{key: {'name': _name(a), 'url': _student_url(a, item)} for key, a in students.items()},
        'copies': copies,
        'copied': any(c['words'] > 1 for c in copies),
        'grade_caption': grade_caption(row.get('review')),
        'task_window_url': reverse('worksheet_task_window', args=[assignment.worksheet_id, item.pk]),
    }


def class_for_item(request, worksheet_id, item_id):
    """Как класс (или группа ?group=) решает пункт листка: строки
    progress_people по одной задаче и сводка live_summary — общая основа
    окна «задача» и страницы «задача у класса»."""
    from .progress import live_summary, progress_assignments, progress_groups, progress_people
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    items = list(worksheet.ordered_items().filter(task__isnull=False))
    item = next((i for i in items if i.pk == item_id), None)
    if item is None:
        raise Http404
    number = items.index(item) + 1
    assignments = progress_assignments(Assignment.visible_to(request.user).filter(worksheet=worksheet))
    group_id = request.GET.get('group', '')
    if group_id.isdigit():
        group = get_object_or_404(StudentGroup.visible_to(request.user), pk=group_id)
        assignments = assignments.filter(student__in=group.students.all())
    assignments = assignments.order_by('student__last_name', 'student__username')
    groups = [dict(g, number=number) for g in progress_groups([item], assignments)]
    people = progress_people(groups, assignments)
    summary, stats = live_summary(groups, people)
    for person in people:
        for cell in person['cells']:
            obj = cell['obj']
            cell['shown'] = obj.mask_fragments(f'class_{obj.pk}', for_teacher=True) if obj and obj.has_mask_values else None
    return {'worksheet': worksheet, 'items': items, 'item': item, 'number': number, 'groups': groups,
            'people': people, 'summary': summary, 'stats': stats, 'group_id': group_id}


@teacher_required
@never_cache
def task_window(request, worksheet_id, item_id):
    """Окно «задача»: условие, маска «так видит ученик», эталон, решение и
    как задачу решает класс (или выбранная группа) — счётчики и ответы."""
    data = class_for_item(request, worksheet_id, item_id)
    worksheet, items, item, number = data['worksheet'], data['items'], data['item'], data['number']
    summary, stats = data['summary'], data['stats']
    answers, wrong = [], Counter()
    for person in data['people']:
        cells = [c for c in person['cells'] if not c['hidden']]
        if not cells:
            continue
        for cell in cells:
            if cell['status'] == 'wrong' and cell['answer']:
                wrong[cell['answer']] += 1
        answers.append({'person': person, 'cells': cells, 'name': _name(person['assignment'])})
    common = wrong.most_common(1)[0] if wrong and wrong.most_common(1)[0][1] > 1 else None
    first = stats[0] if stats else {'ok': 0, 'answered': 0, 'live': 0}
    subitems = item.selected_subitems()
    index = items.index(item)
    return render(request, 'assignments/_task_window.html', {
        'worksheet': worksheet, 'item': item, 'task': item.task, 'number': number, 'total': len(items),
        'subitems': [{'subitem': s, 'label': f'{number}{subitem_label(i)}', 'reference': reference_for(s, 'reference_sub')}
                     for i, s in enumerate(subitems)],
        'reference': '' if subitems else reference_for(item.task),
        'answers': answers, 'common': common, 'ok': sum(s['ok'] for s in stats),
        'answered': sum(s['answered'] for s in stats), 'live': first['live'],
        'unopened': sum(1 for a in answers if all(c['status'] == 'empty' for c in a['cells'])),
        'prev_url': reverse('worksheet_task_window', args=[worksheet.pk, items[index - 1].pk]) if index else '',
        'next_url': reverse('worksheet_task_window', args=[worksheet.pk, items[index + 1].pk]) if index + 1 < len(items) else '',
        'summary': summary,
        'class_url': reverse('assignment_item_class', args=[worksheet.pk, item.pk]),
    })


def _answer_key(answer):
    return ' '.join((answer or '').split())


def class_answer_groups(people, column, task_id, anonymous=False):
    """Ответы класса на один пункт (column — индекс колонки в cells),
    сгруппированные по одинаковому ответу (макет D_Task): верные одной
    группой, неверные по ответу — частая ошибка первой, введённые без
    проверки, «решают сейчас» (последний ответ на этой задаче в окне
    LIVE_MINUTES) и «ещё не дошли». Плюс счётчики для полосы прогресса."""
    buckets = {'ok': [], 'wrong': {}, 'draft': {}, 'live': [], 'rest': []}
    counts = Counter()
    tries = Counter()
    for index, person in enumerate(people, 1):
        cell = person['cells'][column]
        if cell['hidden']:
            continue
        row = {'person': person, 'cell': cell, 'copied': person['copied'] and not anonymous,
               'name': f'Ученик {index}' if anonymous else _name(person['assignment'])}
        status = cell['status']
        if status == 'ok':
            buckets['ok'].append(row)
            counts['ok_first' if cell['attempt_count'] <= 1 else 'ok_later'] += 1
            tries[cell['attempt_count'] or 1] += 1
        elif status in ('wrong', 'draft', 'unknown'):
            kind = 'wrong' if status == 'wrong' else 'draft'
            buckets[kind].setdefault(_answer_key(cell['answer']), []).append(row)
            counts[kind] += 1
        elif person['live_task'] == task_id:
            buckets['live'].append(row)
            counts['live'] += 1
        else:
            buckets['rest'].append(row)
            counts['rest'] += 1
    groups = []
    if buckets['ok']:
        common = Counter(_answer_key(r['cell']['answer']) for r in buckets['ok']).most_common(1)[0][0]
        sample = next(r['cell'] for r in buckets['ok'] if _answer_key(r['cell']['answer']) == common)
        groups.append({'kind': 'ok', 'verdict': 'Верно', 'sample': sample, 'rows': buckets['ok']})
    wrong = sorted(buckets['wrong'].values(), key=lambda rows: -len(rows))
    for position, rows in enumerate(wrong):
        verdict = 'Неверно, частая ошибка' if position == 0 and len(rows) > 1 else 'Неверно'
        groups.append({'kind': 'wrong', 'verdict': verdict, 'sample': rows[0]['cell'], 'rows': rows})
    for rows in sorted(buckets['draft'].values(), key=lambda rows: -len(rows)):
        groups.append({'kind': 'draft', 'verdict': 'Введено, не проверено', 'sample': rows[0]['cell'], 'rows': rows})
    if buckets['live']:
        groups.append({'kind': 'live', 'title': 'Решают сейчас', 'verdict': 'на этой задаче', 'rows': buckets['live']})
    if buckets['rest']:
        groups.append({'kind': 'rest', 'title': 'Ещё не дошли', 'verdict': 'ответа на эту задачу нет', 'rows': buckets['rest']})
    total = sum(counts.values())
    bar = [{'key': key, 'label': label, 'count': counts[key], 'percent': round(100 * counts[key] / total, 2) if total else 0}
           for key, label in [('ok_first', 'Верно с первой'), ('ok_later', 'Верно не сразу'), ('wrong', 'Неверно'),
                              ('draft', 'Не проверено'), ('live', 'Решают сейчас'), ('rest', 'Не дошли')]
           if counts[key] or key not in ('draft',)]
    return {'answer_groups': groups, 'bar': bar, 'total': total,
            'tries': sorted(tries.items()), 'answered': counts['ok_first'] + counts['ok_later'] + counts['wrong']}


@teacher_required
@never_cache
def task_class(request, worksheet_id, item_id):
    """Страница «задача у класса» (макет D_Task): условие и эталон, прогресс
    по задаче и ответы класса группами; ?anon=1 — «показать классу без
    имён» (для проектора), ?point= — подпункт. Сводка и группы обновляются
    опросом (?fragment=1, teacher_progress.js)."""
    data = class_for_item(request, worksheet_id, item_id)
    worksheet, items, item, number = data['worksheet'], data['items'], data['item'], data['number']
    columns = data['groups'][0]['columns'] if data['groups'] else []
    point = request.GET.get('point', '0')
    column = int(point) if point.isdigit() and int(point) < len(columns) else 0
    anonymous = request.GET.get('anon') == '1'
    context = {
        'worksheet': worksheet, 'item': item, 'task': item.task, 'number': number, 'items': items,
        'columns': columns, 'column': column, 'anonymous': anonymous, 'group_id': data['group_id'],
        'people_total': len(data['people']),
        **(class_answer_groups(data['people'], column, item.task_id, anonymous) if columns else
           {'answer_groups': [], 'bar': [], 'total': 0, 'tries': [], 'answered': 0}),
    }
    if request.GET.get('fragment'):
        return render(request, 'assignments/_task_class_body.html', context)
    owner = columns[column]['owner'] if columns else item.task
    context.update({
        'strip': [{'number': n, 'url': reverse('assignment_item_class', args=[worksheet.pk, i.pk]), 'current': i.pk == item.pk}
                  for n, i in enumerate(items, 1)],
        'reference': reference_for(owner),
        'subitems': item.selected_subitems(),
        'task_window_url': reverse('worksheet_task_window', args=[worksheet.pk, item.pk]),
    })
    return render(request, 'assignments/task_class.html', context)

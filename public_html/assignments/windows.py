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


@teacher_required
@never_cache
def task_window(request, worksheet_id, item_id):
    """Окно «задача»: условие, маска «так видит ученик», эталон, решение и
    как задачу решает класс (или выбранная группа) — счётчики и ответы."""
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
    answers, wrong = [], Counter()
    for person in people:
        cells = [c for c in person['cells'] if not c['hidden']]
        if not cells:
            continue
        for cell in cells:
            obj = cell['obj']
            cell['shown'] = obj.mask_fragments(f'class_{obj.pk}', for_teacher=True) if obj and obj.has_mask_values else None
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
    })

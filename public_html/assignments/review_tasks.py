"""Проверка листка по задачам (макет D_Review, 22.10.2026): вкладки
«Задачи | Ученики», очередь задач с ответами без оценки, одна задача у всех
— ответы группами по одинаковому ответу, оценка группе («Всем N») и каждому.

Зачёт по-прежнему только из оценки учителя (Review.grade, Assignment.result):
автосверка «верно» оценку не ставит, а подсказывает «+» группе верных."""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from accounts.models import StudentGroup
from worksheets.models import Worksheet
from .models import Assignment, Review, Submission
from .windows import _name, reference_for


def _answer_key(answer):
    return ' '.join((answer or '').split())


def review_data(user, worksheet, group_id=''):
    """Строки progress_people по всему листку и разбивка по задачам:
    {item.pk: {'item', 'number', 'start', 'end', 'rows': [...]}}, где строка
    — ученик с ответом на задачу (поле, подпункт или фото)."""
    from .progress import live_summary, progress_assignments, progress_groups, progress_people
    assignments = progress_assignments(Assignment.visible_to(user).filter(worksheet=worksheet))
    if group_id.isdigit():
        group = get_object_or_404(StudentGroup.visible_to(user), pk=group_id)
        assignments = assignments.filter(student__in=group.students.all())
    assignments = assignments.order_by('student__last_name', 'student__username')
    items = list(worksheet.ordered_items().filter(task__isnull=False))
    groups = progress_groups(items, assignments)
    people = progress_people(groups, assignments)
    live_summary(groups, people)  # метка «•» и «сейчас» у учеников
    tasks, start = {}, 0
    for person in people:
        person['visible_tasks'] = 0  # задач, а не подпунктов (вкладка «Ученики», ревью #281)
    for group in groups:
        end = start + len(group['columns'])
        rows = []
        for person in people:
            cells = person['cells'][start:end]
            if not all(c['hidden'] for c in cells):
                person['visible_tasks'] += 1
            if all(c['hidden'] for c in cells) or all(c['status'] == 'empty' for c in cells):
                continue
            for cell in cells:
                obj = cell['obj']
                cell['shown'] = obj.mask_fragments(f'rv_{obj.pk}', for_teacher=True) if obj and obj.has_mask_values else None
            review = cells[0]['review']
            rows.append({'person': person, 'cells': cells, 'review': review, 'grade': review.grade if review else '',
                         'name': _name(person['assignment']), 'copied': person['copied'],
                         'grade_url': reverse('grade_task', args=[person['assignment'].pk, group['item'].task_id])})
        tasks[group['item'].pk] = {'item': group['item'], 'number': group['number'], 'rows': rows,
                                   'pending': sum(1 for r in rows if not r['grade'])}
        start = end
    return {'assignments': assignments, 'people': people, 'tasks': tasks}


def answer_groups(rows):
    """Ответы на задачу группами по одинаковому ответу: неверные (самая
    частая первой), без автосверки (фото, развёрнутый ответ), верные."""
    buckets = {}
    for row in rows:
        statuses = {c['status'] for c in row['cells'] if not c['hidden']}
        # Пустые подпункты вид группы не решают: верно на 1а и пусто на 1б —
        # «верно, не все подпункты», а не «автосверки нет» (ревью #281)
        answered = statuses - {'empty'}
        kind = 'ok' if answered == {'ok'} else 'wrong' if 'wrong' in answered else 'draft'
        partial = 'empty' in statuses
        key = (kind, partial, tuple(_answer_key(c['answer']) for c in row['cells']))
        buckets.setdefault(key, []).append(row)
    groups = []
    order = {'wrong': 0, 'draft': 1, 'ok': 2}
    for position, ((kind, partial, key), members) in enumerate(sorted(buckets.items(), key=lambda kv: (order[kv[0][0]], kv[0][1], -len(kv[1])))):
        if kind == 'wrong':
            first_wrong = position == 0 and len(members) > 1
            verdict = 'Неверно по автосверке, частая ошибка' if first_wrong else 'Неверно по автосверке'
        elif kind == 'ok':
            verdict = 'Верно по автосверке, не все подпункты' if partial else 'Верно по автосверке'
        else:
            verdict = 'Автосверки нет: фото или развёрнутый ответ' if not any(key) else 'Автосверки нет'
        grades = {r['grade'] for r in members}
        groups.append({'kind': kind, 'verdict': verdict, 'rows': members, 'sample': members[0]['cells'],
                       'has_answer': any(key), 'grade': grades.pop() if len(grades) == 1 else '',
                       'suggested': '+' if kind == 'ok' and not partial else '',
                       'members': ','.join(str(r['person']['assignment'].pk) for r in members)})
    return groups


@teacher_required
@never_cache
def review_tasks(request, worksheet_id):
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    group_id = request.GET.get('group', '')
    data = review_data(request.user, worksheet, group_id)
    tasks = list(data['tasks'].values())
    answers = sum(len(t['rows']) for t in tasks)
    graded = answers - sum(t['pending'] for t in tasks)
    context = {'worksheet': worksheet, 'group_id': group_id, 'tasks': tasks, 'answers': answers, 'graded': graded,
               'auto_ok': sum(1 for t in tasks for r in t['rows'] if all(c['status'] == 'ok' for c in r['cells'] if not c['hidden'])),
               'view': 'students' if request.GET.get('view') == 'students' else 'tasks',
               'grade_choices': Review.grade_options(),
               'credits': [(symbol, label, round(100 * Review.CREDITS.get(value, 0))) for value, label, symbol in Review.grade_options()]}
    if context['view'] == 'students':
        students = []
        for person in data['people']:
            mine = [r for t in tasks for r in t['rows'] if r['person'] is person]
            students.append({'person': person, 'name': _name(person['assignment']), 'answered': len(mine),
                             'graded': sum(1 for r in mine if r['grade']), 'total': person['visible_tasks']})
        context['students'] = students
        return render(request, 'assignments/review_tasks.html', context)
    item_id = request.GET.get('item', '')
    queue = [t for t in tasks if t['pending']]
    current = next((t for t in tasks if str(t['item'].pk) == item_id), None) or (queue[0] if queue else tasks[0] if tasks else None)
    if current:
        later = [t for t in queue if t['number'] > current['number']] or [t for t in queue if t is not current]
        task = current['item'].task
        subitems = current['item'].selected_subitems()
        context.update({
            'current': current, 'task': task, 'subitems': subitems,
            'reference': reference_for(task) if not subitems else [],
            'groups': answer_groups(current['rows']),
            'next': later[0] if later else None,
            'auto_done': [t['number'] for t in tasks if t['rows'] and not t['pending']],
            'group_grade_url': reverse('assignment_review_group_grade', args=[worksheet.pk, current['item'].pk]),
            'task_window_url': reverse('worksheet_task_window', args=[worksheet.pk, current['item'].pk]),
        })
    return render(request, 'assignments/review_tasks.html', context)


@teacher_required
@require_POST
def review_group_grade(request, worksheet_id, item_id):
    """«Всем N»: одна оценка всем ученикам группы ответов на задачу. Берутся
    только назначения этого листка, доступные учителю, где пункт не скрыт."""
    worksheet = get_object_or_404(Worksheet.visible_to(request.user), pk=worksheet_id)
    item = get_object_or_404(worksheet.items.filter(task__isnull=False, deleted_at__isnull=True), pk=item_id)
    grade = request.POST.get('grade', '')
    if grade not in dict(Review.GRADE_CHOICES):
        return JsonResponse({'ok': False, 'message': 'Неизвестная оценка'}, status=400)
    ids = [int(pk) for pk in request.POST.get('assignments', '').split(',') if pk.strip().isdigit()]
    assignments = (Assignment.visible_to(request.user).filter(worksheet=worksheet, pk__in=ids)
                   .exclude(hidden_items=item))
    urls = []
    for assignment in assignments:
        submission, _ = Submission.objects.get_or_create(assignment=assignment, task_id=item.task_id)
        Review.objects.update_or_create(submission=submission, defaults={
            'grade': grade, 'done': grade in ('+', '.+'), 'reviewer': request.user})
        urls.append(reverse('grade_task', args=[assignment.pk, item.task_id]))
    return JsonResponse({'ok': True, 'grade': grade, 'urls': urls,
                         'message': f'Оценка {Review.SYMBOLS.get(grade, grade)} поставлена: {len(urls)}'})

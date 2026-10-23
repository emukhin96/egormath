"""Журнал оценивания (макет D_Journal, 22.10.2026): ученики группы × работы
периода. В ячейке — отметка и процент выполнения (Assignment.result: зачёт
только из оценок учителя), рамка — сдано после срока или не сдано к сроку;
одна работа разворачивается по задачам (оценка, автосверка ✓ₙ, «?» — ждёт
оценки). Справа — средний процент, отметка по порогам и опоздания."""
import io
from datetime import date, datetime, time

from django.db.models import Min
from django.http import FileResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from accounts.decorators import teacher_required
from accounts.models import StudentGroup
from workaudit.services import copy_marks
from .models import Assignment, Review

# Отметка по среднему проценту выполнения: от 85 — «5», от 65 — «4», от 45 — «3»
MARK_THRESHOLDS = ((85, '5'), (65, '4'), (45, '3'))
PERIODS = {'month': 'Этот месяц', 'prev_month': 'Прошлый месяц', 'quarter': 'Четверть',
           'half': 'Полугодие', 'all': 'Всё время'}


def mark_for(percent):
    if percent is None:
        return ''
    return next((mark for threshold, mark in MARK_THRESHOLDS if percent >= threshold), '2')


def period_bounds(period, today=None):
    """Начало и конец периода (даты включительно) по школьному календарю:
    четверти — сентябрь–октябрь, ноябрь–декабрь, январь–март, апрель–август;
    полугодия — сентябрь–декабрь и январь–август. «Всё время» — (None, None)."""
    today = today or timezone.localdate()
    y, m = today.year, today.month
    if period == 'all':
        return None, None
    if period == 'prev_month':
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        return date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)
    if period == 'quarter':
        for first, last in ((9, 11), (11, 13), (1, 4), (4, 9)):
            if first <= m < last:
                start_year = y
                end = date(y + (last > 12), (last - 1) % 12 + 1, 1)
                return date(start_year, first, 1), end
    if period == 'half':
        return (date(y, 9, 1), date(y + 1, 1, 1)) if m >= 9 else (date(y, 1, 1), date(y, 9, 1))
    return date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)


def _aware(day):
    return timezone.make_aware(datetime.combine(day, time.min)) if day else None


def journal_data(user, group_id='', period='month', open_id=''):
    assignments = (Assignment.visible_to(user).select_related('student', 'worksheet')
                   .prefetch_related('hidden_items', 'submissions__review'))
    group = None
    if group_id.isdigit():
        group = get_object_or_404(StudentGroup.visible_to(user), pk=group_id)
        assignments = assignments.filter(student__in=group.students.all())
    start, end = period_bounds(period)
    if start:
        assignments = assignments.filter(assigned_at__gte=_aware(start), assigned_at__lt=_aware(end))
    assignments = list(assignments)
    sheets = {}
    for a in assignments:
        sheets.setdefault(a.worksheet_id, a.worksheet)
    first = dict(Assignment.objects.filter(pk__in=[a.pk for a in assignments]).values('worksheet_id')
                 .annotate(first=Min('assigned_at')).values_list('worksheet_id', 'first'))
    works = sorted(sheets.values(), key=lambda w: (first.get(w.pk), w.pk))
    items = {w.pk: list(w.items.filter(task__isnull=False, deleted_at__isnull=True).order_by('order', 'pk')) for w in works}
    now = timezone.now()
    marks = copy_marks('assignment', assignments)

    # Раскрытая работа — по задачам, данные как в карте ответов
    opened = next((w for w in works if str(w.pk) == open_id), None)
    task_cells = {}
    if opened:
        from .progress import progress_assignments, progress_groups, progress_people
        opened_qs = progress_assignments(Assignment.objects.filter(pk__in=[a.pk for a in assignments if a.worksheet_id == opened.pk]))
        groups = progress_groups(list(opened.ordered_items().filter(task__isnull=False)), opened_qs)
        for person in progress_people(groups, opened_qs):
            cells, start_col = [], 0
            for g in groups:
                part = person['cells'][start_col:start_col + len(g['columns'])]
                start_col += len(g['columns'])
                visible = [c for c in part if not c['hidden']]
                review = part[0]['review']
                if not visible:
                    cells.append({'kind': 'hidden', 'sym': ''})
                elif review and review.grade:
                    credit = review.credit
                    cells.append({'kind': 'good' if credit >= .75 else 'half' if credit >= .5 else 'zero' if review.grade == '0' else 'bad',
                                  'sym': review.grade_symbol, 'title': dict(Review.GRADE_CHOICES)[review.grade], 'cell': part[0]})
                elif all(c['status'] == 'ok' for c in visible):
                    tries = max(c['attempt_count'] for c in visible)
                    cells.append({'kind': 'auto', 'sym': '✓', 'sub': tries if tries > 1 else '', 'title': 'Автосверка: верно', 'cell': part[0]})
                elif any(c['status'] != 'empty' for c in visible):
                    cells.append({'kind': 'pending', 'sym': '?', 'title': 'Ждёт оценки', 'cell': part[0]})
                else:
                    cells.append({'kind': 'empty', 'sym': '—', 'title': 'Нет ответа', 'cell': part[0]})
            task_cells[person['assignment'].pk] = cells
        opened_numbers = [g['number'] for g in groups]
        opened_items = [g['item'] for g in groups]
    else:
        opened_numbers, opened_items = [], []

    students = {}
    for a in assignments:
        row = students.setdefault(a.student_id, {'student': a.student, 'works': {}, 'copied': False})
        row['works'][a.worksheet_id] = a
        row['copied'] = row['copied'] or a.pk in marks
    rows = []
    for row in sorted(students.values(), key=lambda r: (r['student'].last_name, r['student'].first_name, r['student'].username)):
        cells, percents, late = [], [], 0
        for w in works:
            a = row['works'].get(w.pk)
            if a is None:
                cells.append({'work': w, 'kind': 'none'})
                continue
            hidden = {i.pk for i in a.hidden_items.all()}
            task_ids = [i.task_id for i in items[w.pk] if i.pk not in hidden]
            scores = {s.task_id: s.review.credit for s in a.submissions.all() if getattr(s, 'review', None)}
            done = sum(scores.get(t, 0) for t in task_ids)
            percent = round(100 * done / len(task_ids)) if task_ids else 0
            submitted = a.status in (Assignment.STATUS_SUBMITTED, Assignment.STATUS_REVIEWED)
            # Опоздание: у сданной — сдана после срока; у несданной (выдана или
            # возвращена на доработку, где submitted_at остаётся от прошлой
            # сдачи) — срок прошёл (ревью #283)
            if submitted:
                is_late = bool(a.due_at and a.submitted_at and a.submitted_at > a.due_at)
            else:
                is_late = bool(a.due_at and now > a.due_at)
            late += is_late
            missing = not submitted and is_late
            # Отметка и вклад в средний — только у проверенной работы: процент
            # идёт из оценок учителя, у сданной без проверки он занижен (ревью #283)
            reviewed = a.status == Assignment.STATUS_REVIEWED
            kind = 'missing' if missing else 'done' if reviewed else 'pending' if submitted else 'open'
            cell = {'work': w, 'assignment': a, 'late': is_late, 'percent': percent if reviewed else None,
                    'kind': kind, 'tasks': task_cells.get(a.pk), 'mark': mark_for(percent) if reviewed else ''}
            if reviewed:
                percents.append(percent)
            cells.append(cell)
        average = round(sum(percents) / len(percents)) if percents else None
        rows.append({'student': row['student'], 'name': row['student'].get_full_name() or row['student'].username,
                     'copied': row['copied'], 'cells': cells, 'average': average, 'mark': mark_for(average), 'late': late})
    return {'group': group, 'works': works, 'rows': rows, 'opened': opened, 'opened_numbers': opened_numbers,
            'opened_columns': list(zip(opened_numbers, opened_items)), 'start': start, 'end': end}


@teacher_required
@never_cache
def journal(request):
    group_id = request.GET.get('group', '')
    period = request.GET.get('period') if request.GET.get('period') in PERIODS else 'month'
    data = journal_data(request.user, group_id, period, request.GET.get('open', ''))
    if request.GET.get('format') == 'xlsx':
        return journal_xlsx(data, period)
    return render(request, 'assignments/journal.html', {
        **data, 'groups': StudentGroup.visible_to(request.user), 'group_id': group_id,
        'period': period, 'periods': PERIODS, 'period_label': PERIODS[period], 'percent_only': request.GET.get('show') == 'pct',
        'thresholds': [t for t, _ in MARK_THRESHOLDS], 'grade_choices': Review.grade_options()})


def journal_xlsx(data, period):
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = 'Журнал'
    sheet.append(['Ученик'] + [w.title for w in data['works']] + ['Средний %', 'Отметка', 'Опоздания'])
    for row in data['rows']:
        values = []
        for cell in row['cells']:
            if cell['kind'] == 'none':
                values.append(None)
            elif cell['kind'] == 'missing':
                values.append('не сдано')
            elif cell['kind'] == 'open':
                values.append('не сдано, срок не прошёл')
            elif cell['kind'] == 'pending':
                values.append('ждёт проверки' + (', после срока' if cell['late'] else ''))
            else:
                values.append(f"{cell['mark']}, {cell['percent']}%" + (', после срока' if cell['late'] else ''))
        sheet.append([row['name']] + values + [row['average'], row['mark'], row['late']])
    # Строки — только текст: название листка или имя, начинающееся с «=»,
    # не должно стать формулой в Excel (как в independentworks.export, ревью #283)
    for row in sheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'
    sheet.freeze_panes = 'B2'
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 22
    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)
    return FileResponse(stream, as_attachment=True, filename=f'journal-{period}.xlsx')

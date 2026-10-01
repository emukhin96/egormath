"""Отметка «уже задавалась»: сбор истории по заданиям и самостоятельным."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StudentGroup
from problems.models import Task
from problems.tests import make_student, make_teacher
from worksheets.models import Worksheet, WorksheetItem
from worksheets.tests import make_worksheet

from .models import Assignment
from .task_usage import (
    SESSION_KEY, _group_members, attach_usage, task_usage, usage_events)


class TaskUsageTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.student2 = make_student(self.teacher, 'student2')
        self.worksheet = make_worksheet(self.teacher)
        self.items = list(self.worksheet.ordered_items())
        self.tasks = [item.task for item in self.items]
        self.group = StudentGroup.objects.create(
            teacher=self.teacher, name='8 класс')
        self.group.students.add(self.student)
        self.client.login(username='teacher1', password='pass12345')

    def assign(self, student, worksheet=None):
        return Assignment.objects.create(
            worksheet=worksheet or self.worksheet, student=student,
            assigned_by=self.teacher)

    def test_assignment_history_and_hidden_items(self):
        assignment = self.assign(self.student)
        assignment.hidden_items.add(self.items[1])
        usage = task_usage(self.teacher, self.tasks)
        self.assertEqual([row.student for row in usage[self.tasks[0].pk]],
                         [self.student])
        self.assertEqual(usage[self.tasks[1].pk], [])

    def test_audience_filters_students(self):
        self.assign(self.student)
        self.assign(self.student2)
        self.assertEqual(
            len(task_usage(self.teacher, self.tasks)[self.tasks[0].pk]), 2)
        only = task_usage(self.teacher, self.tasks,
                          student_ids={self.student2.pk})
        self.assertEqual([row.student for row in only[self.tasks[0].pk]],
                         [self.student2])
        self.assertEqual(
            task_usage(self.teacher, self.tasks, student_ids=set()),
            {task.pk: [] for task in self.tasks})

    def test_local_copy_counts_for_original(self):
        original = self.tasks[0]
        copy = Task.objects.create(
            text_latex=original.text_latex, variant_of=original,
            created_by=self.teacher)
        other = Worksheet.objects.create(
            title='Копия', owner=self.teacher)
        WorksheetItem.objects.create(worksheet=other, task=copy, order=10)
        self.assign(self.student2, worksheet=other)
        usage = task_usage(self.teacher, [original])
        self.assertEqual([row.student for row in usage[original.pk]],
                         [self.student2])
        # И наоборот: у копии история оригинала.
        usage = task_usage(self.teacher, [copy])
        self.assertIn(original.pk, usage)

    def test_foreign_teacher_history_is_invisible(self):
        other = make_teacher('teacher2')
        foreign_student = make_student(other, 'student3')
        foreign_sheet = Worksheet.objects.create(title='Чужой', owner=other)
        WorksheetItem.objects.create(
            worksheet=foreign_sheet, task=self.tasks[0], order=10)
        Assignment.objects.create(
            worksheet=foreign_sheet, student=foreign_student, assigned_by=other)
        usage = task_usage(self.teacher, self.tasks)
        self.assertEqual(usage[self.tasks[0].pk], [])

    def test_independent_work_points(self):
        from independentworks.models import Attempt, Point, Run, Variant, Work
        work = Work.objects.create(owner=self.teacher, title='СР')
        run = Run.objects.create(
            work=work, title='СР 1', owner=self.teacher, fingerprint='x',
            issued_at=timezone.now())
        variant = Variant.objects.create(run=run, number=1, signature='s')
        task = self.tasks[0]
        Point.objects.create(
            variant=variant, position=1, label='1',
            source_key=f't{task.pk}', root_key=f't{task.pk}',
            candidate_key=f't{task.pk}:')
        Point.objects.create(
            variant=variant, position=2, part=1, label='2а',
            source_key=f't{self.tasks[1].pk}:s{self.teacher.pk}',
            root_key='x', candidate_key='x')
        Attempt.objects.create(run=run, variant=variant, student=self.student)
        usage = task_usage(self.teacher, self.tasks)
        rows = usage[task.pk]
        self.assertEqual([(r.student, r.kind, r.title) for r in rows],
                         [(self.student, 'independent', 'СР 1')])
        self.assertEqual(
            [r.student for r in usage[self.tasks[1].pk]], [self.student])
        # Другой ученик работу не получал.
        self.assertEqual(
            task_usage(self.teacher, self.tasks,
                       student_ids={self.student2.pk})[task.pk], [])

    def test_independent_points_with_local_copy_count_for_original(self):
        from independentworks.models import Attempt, Point, Run, Variant, Work
        original = self.tasks[0]
        copy = Task.objects.create(
            text_latex=original.text_latex, variant_of=original,
            created_by=self.teacher)
        work = Work.objects.create(owner=self.teacher, title='СР')
        run = Run.objects.create(
            work=work, title='СР с аналогом', owner=self.teacher,
            fingerprint='x', issued_at=timezone.now())
        variant = Variant.objects.create(run=run, number=1, signature='s')
        Point.objects.create(
            variant=variant, position=1, label='1',
            source_key=f't{copy.pk}', root_key='r', candidate_key='c')
        Attempt.objects.create(run=run, variant=variant, student=self.student2)
        for asked in ([original], [copy]):
            usage = task_usage(self.teacher, asked)
            self.assertEqual(
                [(r.student, r.title) for r in usage[original.pk]],
                [(self.student2, 'СР с аналогом')])

    def test_catalog_shows_badge_and_remembers_audience(self):
        self.assign(self.student)
        response = self.client.get(reverse('task_list'))
        self.assertContains(response, 'задавалась · 1 уч.')
        # Выбор группы запоминается в сессии и применяется на подборе.
        response = self.client.get(
            reverse('task_list'), {'who': f'group:{self.group.pk}'})
        self.assertContains(response, 'задавалась 1 из 1')
        self.assertEqual(self.client.session[SESSION_KEY],
                         {'group': self.group.pk})
        response = self.client.get(reverse('task_list'))
        self.assertContains(response, 'задавалась 1 из 1')
        # Ученик без выдач — бейджа нет.
        response = self.client.get(
            reverse('task_list'), {'who': f'student:{self.student2.pk}'})
        self.assertNotContains(response, 'задавалась')
        # Пустой выбор сбрасывает память.
        self.client.get(reverse('task_list'), {'who': ''})
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_attach_usage_marks_tasks(self):
        self.assign(self.student)
        request = self.client.get(reverse('task_list')).wsgi_request
        attach_usage(request, self.tasks)
        self.assertEqual(self.tasks[0].usage['students_total'], 1)
        self.assertIsNone(self.tasks[0].usage['audience_total'])


class UsageEventsTests(TestCase):
    """Список «исп.»: выдача группе — одной строкой с названием группы."""

    def setUp(self):
        self.teacher = make_teacher()
        self.students = [make_student(self.teacher, f'student{i}')
                         for i in range(1, 5)]
        for i, student in enumerate(self.students, start=1):
            student.first_name, student.last_name = f'Ученик{i}', ''
            student.save()
        self.worksheet = make_worksheet(self.teacher)
        self.task = self.worksheet.ordered_items()[0].task
        self.group = StudentGroup.objects.create(
            teacher=self.teacher, name='8А')
        self.group.students.add(*self.students[:3])

    def events(self):
        rows = task_usage(self.teacher, [self.task])[self.task.pk]
        return usage_events(rows, _group_members(self.teacher))

    def assign(self, student, *, groups=()):
        assignment = Assignment.objects.create(
            worksheet=self.worksheet, student=student,
            assigned_by=self.teacher, recipient_origin_known=True)
        assignment.source_groups.set(groups)
        return assignment

    def test_group_assignment_is_one_line(self):
        for student in self.students[:3]:
            self.assign(student, groups=[self.group])
        self.assign(self.students[3])
        [event] = self.events()
        self.assertEqual(event.groups, [self.group])
        self.assertEqual(event.students, [self.students[3]])

    def test_source_group_wins_over_current_membership(self):
        # В группу добавили ученика уже после выдачи — выдача всё равно
        # групповая.
        for student in self.students[:3]:
            self.assign(student, groups=[self.group])
        self.group.students.add(self.students[3])
        [event] = self.events()
        self.assertEqual((event.groups, event.students), ([self.group], []))

    def test_late_addition_via_group_is_by_name(self):
        # Группа получила листок раньше, новичку его довыдали через группу
        # сегодня — сегодняшняя строка не выглядит выдачей всей группе.
        earlier = [self.assign(student, groups=[self.group])
                   for student in self.students[:3]]
        Assignment.objects.filter(pk__in=[a.pk for a in earlier]).update(
            assigned_at=timezone.now() - timezone.timedelta(days=3))
        self.group.students.add(self.students[3])
        self.assign(self.students[3], groups=[self.group])
        events = self.events()
        self.assertEqual([(e.groups, e.students) for e in events],
                         [([], [self.students[3]]), ([self.group], [])])

    def test_single_student_audience_is_by_name(self):
        for student in self.students[:3]:
            self.assign(student, groups=[self.group])
        rows = task_usage(self.teacher, [self.task],
                          student_ids={self.students[0].pk})[self.task.pk]
        [event] = usage_events(rows, _group_members(self.teacher))
        self.assertEqual((event.groups, event.students),
                         ([], [self.students[0]]))

    def test_group_with_hidden_task_falls_back_to_names(self):
        # Листок выдан группе, но у одного ученика задача скрыта — строка
        # «8А» ввела бы в заблуждение, поэтому получившие — по именам.
        assignments = [self.assign(student, groups=[self.group])
                       for student in self.students[:3]]
        item = self.worksheet.ordered_items()[0]
        assignments[2].hidden_items.add(item)
        [event] = self.events()
        self.assertEqual(event.groups, [])
        self.assertEqual(event.students, self.students[:2])
        # Остальные задачи листка группа получила целиком.
        other = self.worksheet.ordered_items()[1].task
        rows = task_usage(self.teacher, [other])[other.pk]
        [other_event] = usage_events(rows, _group_members(self.teacher))
        self.assertEqual(other_event.groups, [self.group])
        # Аудитория «один ученик» не прячет скрытие у другого ученика группы.
        rows = task_usage(self.teacher, [item.task],
                          student_ids={self.students[0].pk})[item.task.pk]
        [event] = usage_events(rows, _group_members(self.teacher))
        self.assertEqual((event.groups, event.students),
                         ([], [self.students[0]]))

    def test_full_group_without_origin_is_inferred(self):
        # Самостоятельная группу не хранит: весь состав группы получил
        # работу — показываем группой, остальных по именам.
        from independentworks.models import Attempt, Point, Run, Variant, Work
        work = Work.objects.create(owner=self.teacher, title='СР')
        run = Run.objects.create(
            work=work, title='СР 1', owner=self.teacher, fingerprint='x',
            issued_at=timezone.now())
        variant = Variant.objects.create(run=run, number=1, signature='s')
        Point.objects.create(
            variant=variant, position=1, label='1',
            source_key=f't{self.task.pk}', root_key='r', candidate_key='c')
        for student in self.students:
            Attempt.objects.create(run=run, variant=variant, student=student)
        [event] = self.events()
        self.assertEqual(event.kind, 'independent')
        self.assertEqual(event.groups, [self.group])
        self.assertEqual(event.students, [self.students[3]])

    def test_partial_group_stays_by_names(self):
        for student in self.students[:2]:
            self.assign(student)
        [event] = self.events()
        self.assertEqual(event.groups, [])
        self.assertEqual(event.students, self.students[:2])

    def test_different_days_are_separate_lines(self):
        for student in self.students[:3]:
            self.assign(student, groups=[self.group])
        late = self.assign(self.students[3])
        Assignment.objects.filter(pk=late.pk).update(
            assigned_at=timezone.now() - timezone.timedelta(days=3))
        events = self.events()
        self.assertEqual([(e.groups, e.students) for e in events],
                         [([self.group], []), ([], [self.students[3]])])

    def test_long_list_of_names_is_shortened(self):
        many = [make_student(self.teacher, f'extra{i}') for i in range(7)]
        for student in many:
            self.assign(student)
        [event] = self.events()
        self.assertEqual(len(event.shown_students), 5)
        self.assertEqual(event.more_students, 2)

    def test_badge_lists_group_once(self):
        for student in self.students[:3]:
            self.assign(student, groups=[self.group])
        self.client.login(username='teacher1', password='pass12345')
        html = self.client.get(reverse('task_list')).content.decode()
        lists = [part.split('</ul>')[0]
                 for part in html.split('<ul class="usage-list">')[1:]]
        self.assertTrue(lists)
        # В каждом бейдже группа одной строкой, без учеников по именам.
        for usage_list in lists:
            self.assertEqual(usage_list.count('<li'), 1)
            self.assertIn('<span class="usage-group">8А</span> — ', usage_list)
            self.assertNotIn('Ученик1', usage_list)

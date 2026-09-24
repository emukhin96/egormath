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
from .task_usage import SESSION_KEY, attach_usage, task_usage


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

"""Массовые действия над выданными работами из общего списка."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from problems.tests import make_student, make_teacher
from worksheets.tests import make_worksheet

from .bulk import parse_keys
from .models import Assignment


class AssignmentBulkTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.student2 = make_student(self.teacher, 'student2')
        self.sheet_a = make_worksheet(self.teacher, title='Листок А')
        self.sheet_b = make_worksheet(self.teacher, title='Листок Б')
        for sheet in (self.sheet_a, self.sheet_b):
            for student in (self.student, self.student2):
                Assignment.objects.create(
                    worksheet=sheet, student=student, assigned_by=self.teacher)
        self.client.login(username='teacher1', password='pass12345')

    def post(self, action, ids, **extra):
        return self.client.post(reverse('assignment_bulk'), {
            'ids': ids, 'action': action, **extra})

    def test_parse_keys(self):
        self.assertEqual(parse_keys(['ordinary-3', 'independent-7', 'x', '']),
                         ([3], [7]))

    def test_list_has_checkboxes_links_and_recipients(self):
        response = self.client.get(reverse('assignment_list'))
        self.assertContains(response, 'assignment-bulk-form')
        self.assertContains(response, f'value="ordinary-{self.sheet_a.pk}"')
        self.assertContains(response, reverse('worksheet_detail', args=[self.sheet_a.pk]))
        self.assertContains(response, 'Петя Ученик/ов (выдано)')

    def test_delete_removes_assignments_of_selected(self):
        response = self.post('delete', [f'ordinary-{self.sheet_a.pk}'])
        self.assertRedirects(response, reverse('assignment_list'))
        self.assertFalse(Assignment.objects.filter(worksheet=self.sheet_a).exists())
        self.assertEqual(Assignment.objects.filter(worksheet=self.sheet_b).count(), 2)

    def test_apply_status_and_due(self):
        Assignment.objects.filter(worksheet=self.sheet_a, student=self.student).update(
            status=Assignment.STATUS_SUBMITTED, submitted_at=timezone.now())
        response = self.post('apply', [f'ordinary-{self.sheet_a.pk}'],
                             status='reviewed', due_action='set',
                             due_at='2026-10-01T12:30')
        self.assertEqual(response.status_code, 302)
        reviewed = Assignment.objects.get(worksheet=self.sheet_a, student=self.student)
        untouched = Assignment.objects.get(worksheet=self.sheet_a, student=self.student2)
        self.assertEqual(reviewed.status, Assignment.STATUS_REVIEWED)
        # Не отправленную работу проверенной не отметить, но срок задан.
        self.assertEqual(untouched.status, Assignment.STATUS_ASSIGNED)
        for a in (reviewed, untouched):
            self.assertEqual(timezone.localtime(a.due_at).strftime('%Y-%m-%d %H:%M'),
                             '2026-10-01 12:30')
        self.post('apply', [f'ordinary-{self.sheet_a.pk}'], due_action='clear')
        self.assertIsNone(Assignment.objects.get(pk=reviewed.pk).due_at)
        # Ничего не выбрано — ошибка, данные не тронуты.
        self.post('apply', [f'ordinary-{self.sheet_b.pk}'])
        self.assertEqual(Assignment.objects.get(
            worksheet=self.sheet_b, student=self.student).status,
            Assignment.STATUS_ASSIGNED)

    def test_cart_collects_tasks_of_selected_works(self):
        response = self.post('cart', [f'ordinary-{self.sheet_a.pk}',
                                      f'ordinary-{self.sheet_b.pk}'])
        self.assertEqual(response.status_code, 302)
        expected = [item.task_id for sheet in (self.sheet_a, self.sheet_b)
                    for item in sheet.ordered_items()]
        self.assertEqual(self.client.session['cart_tasks'], expected)

    def test_independent_from_single_worksheet(self):
        from independentworks.models import Work
        response = self.post('independent', [f'ordinary-{self.sheet_a.pk}'])
        work = Work.objects.get(source_worksheet=self.sheet_a)
        self.assertRedirects(response, reverse('independentworks:edit', args=[work.pk]))
        response = self.post('independent', [f'ordinary-{self.sheet_a.pk}',
                                             f'ordinary-{self.sheet_b.pk}'])
        self.assertEqual(Work.objects.count(), 1)

    def test_foreign_worksheets_are_ignored(self):
        other = make_teacher('teacher2')
        foreign_student = make_student(other, 'student3')
        foreign = make_worksheet(other, title='Чужой')
        Assignment.objects.create(worksheet=foreign, student=foreign_student,
                                  assigned_by=other)
        self.post('delete', [f'ordinary-{foreign.pk}'])
        self.assertTrue(Assignment.objects.filter(worksheet=foreign).exists())


class IndependentBulkTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.client.login(username='teacher1', password='pass12345')
        from independentworks.models import Attempt, Point, Run, Variant, Work
        self.work = Work.objects.create(owner=self.teacher, title='СР')
        self.run = Run.objects.create(
            work=self.work, title='СР 1', owner=self.teacher, fingerprint='x',
            issued_at=timezone.now())
        variant = Variant.objects.create(run=self.run, number=1, signature='s')
        self.sheet = make_worksheet(self.teacher)
        self.task = self.sheet.ordered_items()[0].task
        Point.objects.create(
            variant=variant, position=1, label='1',
            source_key=f't{self.task.pk}', root_key='r', candidate_key='c')
        Attempt.objects.create(run=self.run, variant=variant, student=self.student)

    def post(self, action, **extra):
        return self.client.post(reverse('assignment_bulk'), {
            'ids': [f'independent-{self.run.pk}'], 'action': action,
            'kind': 'independent', **extra})

    def test_deadline_cart_and_delete(self):
        from independentworks.models import Run
        response = self.post('apply', due_action='set', due_at='2026-10-02T09:00',
                             status='reviewed')
        self.assertRedirects(response, reverse('independentworks:catalog'))
        self.run.refresh_from_db()
        self.assertEqual(timezone.localtime(self.run.deadline).strftime('%d.%m %H:%M'),
                         '02.10 09:00')
        self.post('cart')
        self.assertEqual(self.client.session['cart_tasks'], [self.task.pk])
        self.post('delete')
        self.assertFalse(Run.objects.filter(pk=self.run.pk).exists())

    def test_run_with_followup_is_protected(self):
        from independentworks.models import Attempt, Run
        attempt = Attempt.objects.get(run=self.run)
        Run.objects.create(
            work=self.work, title='Работа над ошибками', owner=self.teacher,
            fingerprint='y', kind='correction', parent=attempt)
        from django.contrib.messages import get_messages
        response = self.post('delete')
        self.assertTrue(Run.objects.filter(pk=self.run.pk).exists())
        texts = [m.message for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('сначала снимите работу над ошибками' in t for t in texts), texts)

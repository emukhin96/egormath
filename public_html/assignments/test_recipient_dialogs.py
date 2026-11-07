"""Диалог получателей в списке заданий собирается JS по требованию.

Страница не рендерит <dialog> на каждую работу со строкой на каждого
ученика: в HTML один <template>, данные групп — JSON #recipient-dialogs
(``recipient_dialogs_data``). Формы по-прежнему шлют те же поля
(``students``, ``status_<id>``, ``variant_<id>``) на те же адреса.
"""
import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from independentworks import services as iw
from independentworks.models import Candidate, Position, Work
from problems.models import Source, Task
from problems.tests import make_student, make_teacher
from worksheets.models import Collection, Worksheet, WorksheetItem

from .models import Assignment


def dialogs_data(response):
    html = response.content.decode()
    start = html.index('<script id="recipient-dialogs" type="application/json">')
    start = html.index('>', start) + 1
    return json.loads(html[start:html.index('</script>', start)])


class RecipientDialogDataTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.student2 = make_student(self.teacher, 'student2')
        self.student3 = make_student(self.teacher, 'student3')
        self.sheet = Worksheet.objects.create(title='Домашка 1', owner=self.teacher)
        self.sheet2 = Worksheet.objects.create(title='Домашка 2', owner=self.teacher)
        self.client.login(username='teacher1', password='pass12345')

    def test_list_renders_one_template_and_compact_data(self):
        Assignment.objects.create(worksheet=self.sheet, student=self.student,
                                  assigned_by=self.teacher,
                                  status=Assignment.STATUS_SUBMITTED,
                                  submitted_at=timezone.now())
        Assignment.objects.create(worksheet=self.sheet2, student=self.student2,
                                  assigned_by=self.teacher)
        response = self.client.get(reverse('assignment_list'))
        html = response.content.decode()
        self.assertEqual(html.count('<template id="assignment-recipient-dialog">'), 1)
        self.assertEqual(html.count('<dialog'), 1)
        self.assertNotIn('<select name="status_', html)
        self.assertNotIn('id="assignment-group-ordinary-', html)
        # Кнопки открытия и форма с подтверждением снятия — на месте
        self.assertContains(response, f'data-dialog-open="assignment-group-ordinary-{self.sheet.pk}"')
        self.assertContains(response, 'data-assignment-group-form')
        self.assertContains(response, 'assignment_recipients.js')

        data = dialogs_data(response)
        self.assertEqual(data['statuses'], [list(pair) for pair in Assignment.STATUS_CHOICES])
        self.assertEqual(set(data['students']), {str(s.pk) for s in (self.student, self.student2, self.student3)})
        group = data['groups'][f'ordinary-{self.sheet.pk}']
        self.assertEqual(group['kind'], 'ordinary')
        self.assertEqual(group['title'], 'Домашка 1')
        self.assertEqual(group['action'], reverse('assignment_group_update', args=[self.sheet.pk]))
        rows = {row[0]: row[1:] for row in group['rows']}
        # Отправленную работу можно отметить проверенной, невыданных — нет
        self.assertEqual(rows[self.student.pk], [Assignment.STATUS_SUBMITTED, True])
        self.assertEqual(rows[self.student2.pk], [None, False])
        self.assertEqual(rows[self.student3.pk], [None, False])
        group2 = data['groups'][f'ordinary-{self.sheet2.pk}']
        self.assertEqual({row[0]: row[1] for row in group2['rows']}[self.student2.pk], Assignment.STATUS_ASSIGNED)

    def test_action_keeps_filters(self):
        Assignment.objects.create(worksheet=self.sheet, student=self.student,
                                  assigned_by=self.teacher)
        response = self.client.get(reverse('assignment_list') + '?status=assigned&q=Дом')
        group = dialogs_data(response)['groups'][f'ordinary-{self.sheet.pk}']
        self.assertEqual(group['action'], reverse('assignment_group_update', args=[self.sheet.pk]) + '?status=assigned&q=%D0%94%D0%BE%D0%BC')

    def test_collection_rows_only_existing_students(self):
        task = Task.objects.create(text_latex='$2+2$', answer_latex='4', created_by=self.teacher)
        WorksheetItem.objects.create(worksheet=self.sheet, task=task, order=10)
        Collection.objects.create(worksheet=self.sheet, source=Source.objects.create(title='Задачник'),
                                  locator='p1', is_published=True)
        Assignment.objects.create(worksheet=self.sheet, student=self.student,
                                  assigned_by=self.teacher)
        response = self.client.get(reverse('assignment_list'))
        self.assertContains(response, 'новых учеников добавить нельзя')
        group = dialogs_data(response)['groups'][f'ordinary-{self.sheet.pk}']
        self.assertEqual(group['kind'], 'collection')
        self.assertEqual([row[0] for row in group['rows']], [self.student.pk])

    def test_student_names_are_json_escaped(self):
        self.student.first_name = '<b>Иван</b> & Co'
        self.student.save()
        Assignment.objects.create(worksheet=self.sheet, student=self.student,
                                  assigned_by=self.teacher)
        response = self.client.get(reverse('assignment_list'))
        self.assertNotContains(response, '<b>Иван</b>')
        self.assertEqual(dialogs_data(response)['students'][str(self.student.pk)], f'<b>Иван</b> & Co {self.student.last_name}'.strip())

    def test_same_form_fields_still_update_assignments(self):
        existing = Assignment.objects.create(worksheet=self.sheet, student=self.student,
                                             assigned_by=self.teacher)
        response = self.client.post(
            reverse('assignment_group_update', args=[self.sheet.pk]) + '?kind=ordinary', {
                'students': [self.student.pk, self.student2.pk],
                f'status_{self.student.pk}': Assignment.STATUS_RETURNED,
                f'status_{self.student2.pk}': Assignment.STATUS_ASSIGNED,
            })
        self.assertRedirects(response, reverse('assignment_list') + '?kind=ordinary')
        existing.refresh_from_db()
        self.assertEqual(existing.status, Assignment.STATUS_RETURNED)
        self.assertTrue(Assignment.objects.filter(worksheet=self.sheet, student=self.student2,
                                                  status=Assignment.STATUS_ASSIGNED).exists())
        data = dialogs_data(self.client.get(reverse('assignment_list')))
        rows = {row[0]: row[1] for row in data['groups'][f'ordinary-{self.sheet.pk}']['rows']}
        self.assertEqual(rows[self.student.pk], Assignment.STATUS_RETURNED)
        self.assertEqual(rows[self.student2.pk], Assignment.STATUS_ASSIGNED)
        self.assertIsNone(rows[self.student3.pk])


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class IndependentRecipientDialogTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('teacher')
        Profile.objects.create(user=self.teacher, role='teacher', base_editor=True)
        self.student = User.objects.create_user('student', first_name='Пётр', last_name='Первый')
        Profile.objects.create(user=self.student, teacher=self.teacher, role='student')
        self.extra = User.objects.create_user('extra')
        Profile.objects.create(user=self.extra, teacher=self.teacher, role='student')
        work = Work.objects.create(owner=self.teacher, title='Уравнения')
        position = Position.objects.create(work=work)
        task = Task.objects.create(text_latex='$2+2$', answer_latex='4', answer_mask='{{number: 4}}')
        Candidate.objects.create(position=position, task=task)
        run = iw.prepare(work, self.teacher, [self.student.pk])
        iw.issue(run.pk)
        self.attempt = run.attempts.get()
        self.client.force_login(self.teacher)

    def test_independent_group_rows_variants_and_locked(self):
        response = self.client.get(reverse('assignment_list') + '?kind=independent')
        html = response.content.decode()
        self.assertNotIn('<select name="variant_', html)
        self.assertEqual(html.count('<dialog'), 1)
        run = self.attempt.run
        self.assertContains(response, f'data-dialog-open="assignment-group-independent-{run.pk}"')
        group = dialogs_data(response)['groups'][f'independent-{run.pk}']
        self.assertEqual(group['kind'], 'independent')
        self.assertEqual(group['action'], reverse('independentworks:recipients', args=[run.pk]) + '?kind=independent')
        self.assertEqual(group['variants'], [[v.pk, v.number] for v in run.variants.all()])
        rows = {row[0]: row[1:] for row in group['rows']}
        self.assertEqual(rows[self.student.pk], [self.attempt.variant_id, False, ''])
        self.assertEqual(rows[self.extra.pk], [None, False, ''])
        self.assertEqual(dialogs_data(response)['students'][str(self.student.pk)], 'Пётр Первый')

        iw.start(self.attempt.pk)
        group = dialogs_data(self.client.get(reverse('assignment_list')))['groups'][f'independent-{run.pk}']
        rows = {row[0]: row[1:] for row in group['rows']}
        self.assertEqual(rows[self.student.pk], [self.attempt.variant_id, True, 'Выполняется'])

    def test_same_form_fields_still_update_recipients(self):
        run = self.attempt.run
        response = self.client.post(reverse('independentworks:recipients', args=[run.pk]) + '?kind=independent',
                                    {'students': [self.student.pk, self.extra.pk],
                                     f'variant_{self.student.pk}': self.attempt.variant_id,
                                     f'variant_{self.extra.pk}': self.attempt.variant_id})
        self.assertRedirects(response, reverse('assignment_list') + '?kind=independent')
        self.assertEqual(set(run.attempts.values_list('student_id', flat=True)), {self.student.pk, self.extra.pk})

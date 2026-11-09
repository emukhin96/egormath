"""Фильтр «Листок» в списке заданий — только листки с выданными работами.

Раньше селект содержал все листки учителя (у редактора — тысячи, с книжными
подборками, ~265 КБ HTML на копии прода). Теперь ``worksheet_filter_options``
отдаёт листки, по которым есть выдачи (``Assignment.visible_to``), а для
самостоятельных — исходные листки выданных проведений; выбранный в URL
листок остаётся в списке текущим, даже если выдач по нему нет.
"""
import re

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile
from independentworks import services as iw
from independentworks.models import Candidate, Position, Work
from problems.models import Task
from problems.tests import make_student, make_teacher
from worksheets.models import Worksheet

from .models import Assignment
from .views import worksheet_filter_options


def option_ids(response):
    """id листков в селекте фильтра, в порядке вывода."""
    html = response.content.decode()
    start = html.index('<select name="worksheet" id="assignment-worksheet">')
    select = html[start:html.index('</select>', start)]
    return [int(v) for v in re.findall(r'<option value="(\d+)"', select)]


class WorksheetFilterOptionsTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.issued = Worksheet.objects.create(title='Выданный', owner=self.teacher)
        self.idle = Worksheet.objects.create(title='Без выдач', owner=self.teacher)
        self.other_teacher = make_teacher('teacher2', base_editor=False)
        self.foreign = Worksheet.objects.create(title='Чужой', owner=self.other_teacher)
        Assignment.objects.create(worksheet=self.issued, student=self.student,
                                  assigned_by=self.teacher)
        self.client.login(username='teacher1', password='pass12345')

    def test_options_limited_to_worksheets_with_assignments(self):
        response = self.client.get(reverse('assignment_list'))
        self.assertEqual(option_ids(response), [self.issued.pk])
        self.assertNotContains(response, 'Без выдач')
        self.assertNotContains(response, 'Чужой')

    def test_selected_worksheet_stays_in_list_even_without_assignments(self):
        response = self.client.get(reverse('assignment_list'), {'worksheet': self.idle.pk})
        self.assertCountEqual(option_ids(response), [self.issued.pk, self.idle.pk])
        self.assertContains(response, f'<option value="{self.idle.pk}" selected>Без выдач</option>')
        self.assertContains(response, 'Сбросить')

    def test_foreign_selected_worksheet_is_not_revealed(self):
        response = self.client.get(reverse('assignment_list'), {'worksheet': self.foreign.pk})
        self.assertEqual(option_ids(response), [self.issued.pk])
        self.assertNotContains(response, 'Чужой')

    def test_filter_applies_together_with_student_and_status(self):
        second = make_student(self.teacher, 'student2')
        sheet2 = Worksheet.objects.create(title='Второй', owner=self.teacher)
        Assignment.objects.create(worksheet=sheet2, student=second, assigned_by=self.teacher,
                                  status=Assignment.STATUS_SUBMITTED)
        response = self.client.get(reverse('assignment_list'), {
            'worksheet': self.issued.pk, 'student': self.student.pk, 'status': 'assigned'})
        self.assertEqual([g['worksheet_id'] for g in response.context['worksheet_groups']],
                         [self.issued.pk])
        self.assertCountEqual(option_ids(response), [self.issued.pk, sheet2.pk])
        response = self.client.get(reverse('assignment_list'), {
            'worksheet': self.issued.pk, 'student': second.pk})
        self.assertEqual(response.context['worksheet_groups'], [])

    def test_superuser_sees_all_teachers_issued_worksheets_once(self):
        root = User.objects.create_superuser('root', 'root@example.com', 'pass12345')
        Profile.objects.create(user=root, role=Profile.ROLE_TEACHER, base_editor=True)
        other_student = make_student(self.other_teacher, 'student3')
        Assignment.objects.create(worksheet=self.foreign, student=other_student,
                                  assigned_by=self.other_teacher)
        Assignment.objects.create(worksheet=self.foreign, student=self.student,
                                  assigned_by=self.other_teacher)
        self.client.login(username='root', password='pass12345')
        response = self.client.get(reverse('assignment_list'))
        self.assertCountEqual(option_ids(response), [self.issued.pk, self.foreign.pk])
        # Фильтр по владельцу сужает и список листков
        response = self.client.get(reverse('assignment_list'), {'owner': self.other_teacher.pk})
        self.assertEqual(option_ids(response), [self.foreign.pk])

    def test_helper_runs_one_query(self):
        with self.assertNumQueries(1):
            options = worksheet_filter_options(self.teacher, 'ordinary', str(self.idle.pk))
        self.assertCountEqual([o['pk'] for o in options], [self.issued.pk, self.idle.pk])


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class IndependentWorksheetFilterTests(TestCase):
    """Вид «Самостоятельные»: листки — исходные листки выданных проведений."""

    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.source = Worksheet.objects.create(title='Исходный листок', owner=self.teacher)
        self.unused = Worksheet.objects.create(title='Листок без самостоятельных', owner=self.teacher)
        Assignment.objects.create(worksheet=self.unused, student=self.student,
                                  assigned_by=self.teacher)
        task = Task.objects.create(text_latex='Два плюс два?', answer_mask='{{number: 4}}')
        work = Work.objects.create(owner=self.teacher, title='Самостоятельная',
                                   source_worksheet=self.source)
        Candidate.objects.create(position=Position.objects.create(work=work), task=task)
        self.run = iw.prepare(work, self.teacher, [self.student.pk])
        iw.issue(self.run.pk)
        draft_work = Work.objects.create(owner=self.teacher, title='Черновик',
                                         source_worksheet=self.unused)
        Candidate.objects.create(position=Position.objects.create(work=draft_work), task=task)
        iw.prepare(draft_work, self.teacher, [self.student.pk])  # не выдано
        self.client.login(username='teacher1', password='pass12345')

    def test_independent_view_lists_source_worksheets_of_issued_runs(self):
        response = self.client.get(reverse('assignment_list'), {'kind': 'independent'})
        self.assertEqual(option_ids(response), [self.source.pk])
        self.assertEqual([g['key'] for g in response.context['worksheet_groups']],
                         [f'independent-{self.run.pk}'])

    def test_independent_filter_by_source_worksheet(self):
        response = self.client.get(reverse('assignment_list'),
                                   {'kind': 'independent', 'worksheet': self.source.pk})
        self.assertEqual([g['key'] for g in response.context['worksheet_groups']],
                         [f'independent-{self.run.pk}'])
        response = self.client.get(reverse('assignment_list'),
                                   {'kind': 'independent', 'worksheet': self.unused.pk})
        self.assertEqual(response.context['worksheet_groups'], [])
        self.assertContains(
            response, f'<option value="{self.unused.pk}" selected>Листок без самостоятельных</option>')

    def test_students_of_owner_loaded_once_per_owner(self):
        work = Work.objects.create(owner=self.teacher, title='Ещё одна', source_worksheet=self.source)
        Candidate.objects.create(position=Position.objects.create(work=work),
                                 task=Task.objects.get())
        iw.issue(iw.prepare(work, self.teacher, [self.student.pk]).pk)
        self.client.get(reverse('assignment_list'), {'kind': 'independent'})
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('assignment_list'), {'kind': 'independent'})
        self.assertEqual(len(response.context['worksheet_groups']), 2)
        students_queries = [q['sql'] for q in ctx.captured_queries
                            if 'accounts_profile' in q['sql'] and 'auth_user' in q['sql']
                            and 'role' in q['sql']]
        variants_queries = [q['sql'] for q in ctx.captured_queries
                            if 'FROM `independentworks_variant`' in q['sql']
                            or 'FROM "independentworks_variant"' in q['sql']]
        self.assertLessEqual(len(students_queries), 2, students_queries)
        self.assertLessEqual(len(variants_queries), 2, variants_queries)

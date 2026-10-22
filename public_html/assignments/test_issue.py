"""Мастер выдачи листка по макету E_Issue (assignments/views._issue_context):
листки карточками с историей, данные для итога «Выдать N ученикам»,
автосверка радиокнопками, в том числе зафиксированная после первой выдачи."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import StudentGroup
from problems.models import Task
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet
from .models import Assignment


class IssueWizardTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.sheet = make_worksheet(self.teacher)
        WorksheetItem.objects.filter(worksheet=self.sheet).delete()
        for n in (1, 2, 3):
            WorksheetItem.objects.create(worksheet=self.sheet, task=Task.objects.create(text_latex=f'Задача {n}'), order=n)
        self.anna = make_student(self.teacher, username='anna')
        self.oleg = make_student(self.teacher, username='oleg')
        self.group = StudentGroup.objects.create(teacher=self.teacher, name='9 А')
        self.group.students.add(self.anna, self.oleg)
        Assignment.objects.create(worksheet=self.sheet, student=self.anna, assigned_by=self.teacher,
                                  check_visibility=Assignment.CHECK_TEACHER)
        self.url = reverse('assignment_create')
        self.client.force_login(self.teacher)

    def test_cards_and_summary_data(self):
        response = self.client.get(self.url, {'worksheet': self.sheet.pk})
        self.assertContains(response, 'class="is-sheet"')
        self.assertContains(response, 'data-tasks="3" checked')
        self.assertContains(response, 'выдан 1 ученику')
        self.assertContains(response, 'Выдать задание')
        data = response.context['issue_data']
        self.assertEqual(data['members'][str(self.group.pk)], [self.anna.pk, self.oleg.pk])
        self.assertEqual(data['assigned'], [self.anna.pk])
        self.assertNotContains(response, '·')

    def test_locked_check_visibility(self):
        response = self.client.get(self.url, {'worksheet': self.sheet.pk})
        self.assertTrue(response.context['check_locked'])
        self.assertEqual(response.context['check_value'], Assignment.CHECK_TEACHER)
        self.assertContains(response, f'value="{Assignment.CHECK_TEACHER}" checked disabled')
        fresh = self.client.get(self.url)
        self.assertFalse(fresh.context['check_locked'])
        self.assertEqual([value for value, _, _ in fresh.context['check_options']][0], Assignment.CHECK_LIVE)

    def test_issue_skips_repeat(self):
        response = self.client.post(self.url, {'worksheet': self.sheet.pk, 'groups': [self.group.pk],
                                               'allow_photos': 'on', 'swap_numbers': 'on'})
        self.assertRedirects(response, reverse('assignment_list'))
        oleg = Assignment.objects.get(student=self.oleg)
        self.assertTrue(oleg.swap_numbers)
        self.assertEqual(oleg.check_visibility, Assignment.CHECK_TEACHER)
        self.assertEqual(Assignment.objects.filter(student=self.anna).count(), 1)

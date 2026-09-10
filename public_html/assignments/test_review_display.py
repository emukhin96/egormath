"""Эталоны и решения на странице проверки работы."""
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from problems.models import Task, TaskSubitem
from problems.tests import make_teacher, make_student
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet
from .models import Assignment, Submission, SubmissionPart


class ReviewDisplayTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        student = make_student(self.teacher)
        worksheet = make_worksheet(self.teacher)
        self.task = Task.objects.create(text_latex='Условие')
        WorksheetItem.objects.create(worksheet=worksheet, task=self.task, order=1)
        self.assignment = Assignment.objects.create(
            worksheet=worksheet, student=student, assigned_by=self.teacher)
        self.client.force_login(self.teacher)

    def test_subitem_reference_and_author_solution(self):
        part = TaskSubitem.objects.create(
            task=self.task, order=1, text_latex='Подпункт',
            answer_mask='{{number: 8}}', author_answer_latex='8',
            solution_latex='Редакторское решение',
            author_solution_latex='Авторское решение')
        submission = Submission.objects.create(assignment=self.assignment, task=self.task)
        SubmissionPart.objects.create(
            submission=submission, subitem=part, answer_json={'s1': '7'},
            check_json={'s1': 'wrong'}, auto_check='wrong')
        response = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '(эталон')
        self.assertContains(response, 'Авторское решение')
        self.assertNotContains(response, 'Редакторское решение')
        html = response.content.decode()
        self.assertLess(html.index('✗ неверно'), html.index('Эталон:'))
        self.assertContains(response, 'class="mask-value" data-status="wrong"')
        live = self.client.get(reverse('assignment_live', args=[self.assignment.pk]))
        fragment = next(iter(live.json()['rows'].values()))
        self.assertIn('Эталон:', fragment)
        self.assertIn('review-answer-row', fragment)

    def test_no_empty_solution_disclosure(self):
        response = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertNotContains(response, 'Эталонное решение')

    def test_empty_value_never_has_correct_underline(self):
        html = render_to_string('assignments/_mask.html', {
            'fragments': [{'kind': 'number', 'display': '', 'check': 'ok'}],
            'editable': False})
        self.assertIn('class="mask-value" data-status=""', html)
        html = render_to_string('assignments/_mask.html', {
            'fragments': [{'kind': 'number', 'display': '8', 'check': 'ok'}],
            'editable': False})
        self.assertIn('class="mask-value" data-status="ok"', html)

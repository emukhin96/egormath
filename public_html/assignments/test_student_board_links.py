"""Доски ученика — в любой момент проверки его работы: кнопка в шапке
«Проверки работы» и хронологии, даже если по задаче доски ещё нет."""
from django.test import TestCase, override_settings
from django.urls import reverse

from problems.models import Task
from problems.tests import make_student, make_teacher
from worksheets.models import Worksheet, WorksheetItem
from .models import Assignment


class StudentBoardLinkTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('teacher')
        self.worksheet = Worksheet.objects.create(title='Дроби', owner=self.teacher)
        task = Task.objects.create(text_latex='Сократите $\\frac{6}{8}$.', created_by=self.teacher)
        WorksheetItem.objects.create(worksheet=self.worksheet, task=task, order=10)
        self.assignment = Assignment.objects.create(
            worksheet=self.worksheet, student=make_student(self.teacher), assigned_by=self.teacher)
        self.client.force_login(self.teacher)
        self.boards = (f'{reverse("worksheet_boards", args=[self.worksheet.pk])}'
                       f'?open={self.assignment.pk}')

    def test_review_and_timeline_link_to_student_boards(self):
        for name in ('review_assignment', 'assignment_timeline'):
            response = self.client.get(reverse(name, args=[self.assignment.pk]))
            self.assertContains(response, f'href="{self.boards}"', msg_prefix=name)
        review = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertContains(review, reverse('assignment_timeline', args=[self.assignment.pk]))

    @override_settings(CANVAS_ENABLED=False)
    def test_no_link_without_boards(self):
        response = self.client.get(reverse('review_assignment', args=[self.assignment.pk]))
        self.assertNotContains(response, self.boards)

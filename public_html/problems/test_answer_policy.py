"""Режим развёрнутого ответа сохраняет маски и отключает их для ученика."""
from django.test import TestCase
from django.urls import reverse

from assignments.models import Assignment, Submission
from worksheets.models import Worksheet, WorksheetItem
from .models import Task
from .tests import make_teacher, make_student, formset_management


class AnswerPolicyTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.client.force_login(self.teacher)
        self.task = Task.objects.create(created_by=self.teacher, text_latex='Задача',
                                        answer_mask='{{number: 8}}')
        self.ws = Worksheet.objects.create(owner=self.teacher, title='Листок')
        self.item = WorksheetItem.objects.create(worksheet=self.ws, task=self.task)
        self.url = reverse('task_manage', args=[self.task.pk])

    def test_toggle_preserves_mask_and_restores_short_answer(self):
        self.assertTrue(self.task.short_answer_available())
        for value in ['on', '']:
            response = self.client.post(self.url, {'block': 'answer_policy', 'full_answer_only': value})
            self.assertEqual(response.status_code, 200, response.content)
            self.task.refresh_from_db()
            self.assertEqual(self.task.full_answer_only, bool(value))
            self.assertEqual(self.task.short_answer_available(), not bool(value))
            self.assertEqual(self.task.answer_mask, '{{number: 8}}')

    def test_local_policy_and_duplicate(self):
        sub = self.task.subitems.create(order=1, text_latex='Подпункт', answer_mask='{{number: 2}}')
        url = self.url + f'?worksheet={self.ws.pk}&item={self.item.pk}'
        response = self.client.post(url, {'block': 'answer_policy', 'full_answer_only': 'on', 'scope': 'local'})
        self.assertEqual(response.status_code, 200, response.content)
        self.item.refresh_from_db()
        self.task.refresh_from_db()
        self.assertFalse(self.task.full_answer_only)
        copy = self.item.task
        self.assertTrue(copy.full_answer_only)
        self.assertFalse(copy.short_answer_available())
        self.assertEqual(copy.subitems.get().answer_mask, sub.answer_mask)
        self.assertTrue(copy.make_variant(self.teacher, standalone=True).full_answer_only)

    def test_create_full_answer_task(self):
        response = self.client.post(reverse('task_create'), {
            'text_latex': 'Новая развёрнутая', 'stars': 0, 'columns': 1,
            'answer_policy_submitted': '1', 'full_answer_only': 'on',
            **formset_management('source_refs'), **formset_management('images'),
            **formset_management('subitems')})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Task.objects.get(text_latex='Новая развёрнутая').full_answer_only)

    def test_student_cannot_save_or_check_disabled_mask(self):
        self.task.full_answer_only = True
        self.task.save()
        assignment = Assignment.objects.create(worksheet=self.ws, student=self.student, assigned_by=self.teacher)
        submission = Submission.objects.create(assignment=assignment, task=self.task, answer_json={'s1': '7'})
        self.client.force_login(self.student)
        response = self.client.get(reverse('assignment_detail', args=[assignment.pk]))
        self.assertNotContains(response, f'name="task{self.task.pk}_s1"')
        self.assertContains(response, 'Краткий ответ для этой задачи не предусмотрен')
        data = {f'task{self.task.pk}_s1': '8'}
        self.client.post(reverse('save_answers', args=[assignment.pk]), data)
        response = self.client.post(reverse('check_task', args=[assignment.pk, self.task.pk]), data,
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        submission.refresh_from_db()
        self.assertEqual(submission.answer_json, {'s1': '7'})
        self.assertFalse(submission.check_history.exists())
        self.assertTrue(submission.mask_spec.is_valid)

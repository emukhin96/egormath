"""Удаление из карточки использует ограничения массового удаления."""
from django.test import TestCase
from django.urls import reverse

from worksheets.models import Worksheet, WorksheetItem
from .models import Task
from .tests import make_teacher, make_student


class TaskDeleteTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.task = Task.objects.create(text_latex='Удаление', created_by=self.teacher)
        self.url = reverse('task_delete', args=[self.task.pk])
        self.client.force_login(self.teacher)

    def test_delete_unused_and_post_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertContains(self.client.get(reverse('task_detail', args=[self.task.pk])), 'Удалить задачу')
        self.assertRedirects(self.client.post(self.url), reverse('task_list'))
        self.assertFalse(Task.objects.filter(pk=self.task.pk).exists())

    def test_used_task_is_preserved(self):
        ws = Worksheet.objects.create(owner=self.teacher, title='Листок')
        WorksheetItem.objects.create(worksheet=ws, task=self.task)
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, 'Задача не удалена')
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())
        self.client.post(reverse('task_bulk_update'), {'ids': [self.task.pk], 'delete': '1'})
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_student_cannot_delete(self):
        self.client.force_login(make_student(self.teacher))
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

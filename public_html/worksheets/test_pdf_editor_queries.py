"""Редактор PDF собирает три варианта листка по одному набору элементов
(аудит быстродействия 06.11.2026: 17 повторных запросов подпунктов)."""
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from problems.models import Task, TaskSubitem

from .models import Worksheet
from .tests import make_item, make_teacher


class PdfEditorQueriesTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = Worksheet.objects.create(title='Тест', owner=self.teacher)
        for i in range(3):
            task = Task.objects.create(text_latex=f'Задача {i}', answer_latex='1')
            TaskSubitem.objects.create(task=task, order=10, text_latex='$2+2$;')
            make_item(self.worksheet, task)
        self.client.login(username=self.teacher.username, password='pass12345')

    def test_items_loaded_once_for_three_variants(self):
        with mock.patch.object(Worksheet, 'ordered_items',
                               wraps=self.worksheet.ordered_items, autospec=False) as spy:
            response = self.client.get(
                reverse('worksheet_pdf_editor', args=[self.worksheet.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(len(response.context['variants']), 3)
        for variant in response.context['variants']:
            self.assertIn('Задача 2', variant['tex'])

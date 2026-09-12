"""Проверка новых форматов через формы учителя и API пробного ответа."""
from django.test import TestCase
from django.urls import reverse
from problems.tests import make_teacher
from problems.models import Task
from problems.editor import mask_data


class StrictMaskViewsTests(TestCase):
    def setUp(self):
        self.user = make_teacher()
        self.client.force_login(self.user)

    def test_preview_uses_strict_verdict_and_math_keyboard(self):
        for kind, value in [('digits', '234,00'), ('decimal', '1/2'),
                            ('ratio', '0,5'), ('proportion', '0,5')]:
            response = self.client.post(reverse('task_mask_preview'), {
                'mask': '{{%s: %s}}' % (
                    kind, '234' if kind == 'digits' else
                    '-0,5' if kind == 'decimal' else '1:2'),
                'prefix': 'preview', 'preview_s1': value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['overall'], 'wrong')
            self.assertIn('<math-field', response.json()['html'])
            self.assertIn(f'data-mask-format="{kind}"', response.json()['html'])
            self.assertIn('type="hidden"', response.json()['html'])

    def test_oge_metadata_reaches_drafting(self):
        task = Task.objects.create(text_latex='Задача', author_answer_latex='234')
        from problems.models import ExamItem
        task.exam_items.add(ExamItem.objects.get(code='OGE_2026_11'))
        data = mask_data(task)[0]
        response = self.client.post(reverse('task_mask_draft'), {
            'answer': data['author'], 'exam_codes': data['exam_codes']})
        self.assertEqual(response.json()['mask'], '{{digits: 234}}')

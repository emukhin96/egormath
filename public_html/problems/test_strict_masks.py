"""Проверка новых форматов через формы учителя и API пробного ответа."""
from django.test import TestCase
from django.urls import reverse
from problems.tests import make_teacher
from problems.models import Task
from problems.editor import mask_data
from unittest.mock import patch
from assignments.checks import formulas


class StrictMaskViewsTests(TestCase):
    def setUp(self):
        self.user = make_teacher()
        self.client.force_login(self.user)

    def test_preview_uses_strict_verdict_and_math_keyboard(self):
        for kind, value in [('digits', '234,00'), ('decimal', '1/2'),
                            ('ratio', '0,5'), ('proportion', '0,5')]:
            mask = '{{%s: %s}}' % (
                kind, '234' if kind == 'digits' else
                '-0,5' if kind == 'decimal' else '1:2')
            response = self.client.post(reverse('task_mask_check'), {
                'mask': mask, 'prefix': 'preview', 'preview_s1': value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['checks']['preview'], 'wrong')
            response = self.client.post(reverse('task_mask_preview'),
                                        {'mask': mask, 'prefix': 'preview'})
            self.assertEqual(response.status_code, 200)
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

    def test_formula_preview_rejects_unverified_reference_without_hiding_saved_mask(self):
        formulas._reference_response.cache_clear()
        with patch.object(formulas, '_run_worker', return_value={'unavailable': True}):
            response = self.client.post(reverse('task_mask_preview'), {
                'mask': '{{expression: a+53}}'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['ok'])
        self.assertIn('повторите сохранение', ' '.join(response.json()['errors']))
        response = self.client.post(reverse('task_mask_check'), {
            'mask': '{{expression: a+53}}', 'preview_s1': '53+a'})
        self.assertTrue(response.json()['ok'])
        self.assertEqual(response.json()['checks']['preview'], 'ok')

    def test_admin_validates_task_inline_and_draft_references(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from problems.admin import TaskSubitemInline
        from problems.models import TextbookTaskDraft
        request = RequestFactory().get('/admin/')
        request.user = self.user
        forms_to_check = [
            admin.site._registry[Task].get_form(request, fields=['answer_mask']),
            TaskSubitemInline(Task, admin.site).get_formset(
                request, fields=['answer_mask']).form,
            admin.site._registry[TextbookTaskDraft].get_form(request, fields=['answer_mask']),
        ]
        formulas._reference_response.cache_clear()
        with patch.object(formulas, '_run_worker', return_value={'error': 'неверный эталон'}):
            for form_class in forms_to_check:
                form = form_class({'answer_mask': '{{expression: 1/0}}'})
                self.assertFalse(form.is_valid())
                self.assertIn('неверный эталон', str(form.errors['answer_mask']))
        draft_form = admin.site._registry[TextbookTaskDraft].get_form(request, fields=['subitems'])
        for value in ('{{expression: 1/0}}', '{{expression: a+59}}'):
            with patch.object(formulas, '_run_worker', return_value={'unavailable': True}):
                form = draft_form({'subitems': '[{"answer_mask": "' + value + '"}]'})
                self.assertFalse(form.is_valid())
                self.assertIn('subitems', form.errors)
        formulas._reference_response.cache_clear()

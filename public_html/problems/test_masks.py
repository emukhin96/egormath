"""Маска ответа в форме задачи: валидация, превью, заготовка, метки."""
from django.test import TestCase
from django.urls import reverse

from .forms import TaskForm, TaskSubitemFormSet
from .models import Task, TaskSubitem
from .tests import formset_management, make_teacher


def task_form_data(**extra):
    data = {
        'text_latex': 'Условие', 'columns': 0,
        'answer_latex': '10', 'solution_latex': '',
        'stars': 1, 'answer_type': 'text',
        **formset_management('source_refs'),
        **formset_management('subitems'),
        **formset_management('images'),
    }
    data.update(extra)
    return data


class MaskFormTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.login(username='teacher1', password='pass12345')

    def test_valid_mask_saved(self):
        response = self.client.post(reverse('task_create'), task_form_data(
            answer_mask='Ответ: {{number: 10}} см'))
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get()
        self.assertEqual(task.answer_mask, 'Ответ: {{number: 10}} см')
        self.assertTrue(task.has_mask)

    def test_invalid_mask_rejected_with_message(self):
        form = TaskForm(data=task_form_data(answer_mask='{{number: abc}}'))
        self.assertFalse(form.is_valid())
        self.assertIn('не разобран как число',
                      ' '.join(form.errors['answer_mask']))
        form = TaskForm(data=task_form_data(answer_mask='{{choice: a|b}}'))
        self.assertFalse(form.is_valid())
        self.assertIn('звёздочкой', ' '.join(form.errors['answer_mask']))

    def test_answer_mode_defaults_when_missing(self):
        form = TaskForm(data=task_form_data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('answer_mode', form.fields)
        self.assertNotIn('answer_type', form.fields)

    def test_subitem_mask_validated(self):
        task = Task.objects.create(text_latex='T', created_by=self.teacher)
        data = {
            **formset_management('subitems', total=1),
            'subitems-0-order': 10, 'subitems-0-text_latex': 'а',
            'subitems-0-answer_latex': '2', 'subitems-0-solution_latex': '',
            'subitems-0-answer_mask': '{{range: abc}}',
        }
        fs = TaskSubitemFormSet(data, instance=task)
        self.assertFalse(fs.is_valid())
        self.assertIn('промежуток', str(fs.errors))
        data['subitems-0-answer_mask'] = '{{set: -2; 1}}'
        fs = TaskSubitemFormSet(data, instance=task)
        self.assertTrue(fs.is_valid(), fs.errors)
        fs.save()
        sub = TaskSubitem.objects.get()
        self.assertTrue(sub.has_mask)
        self.assertTrue(task.short_answer_available())
        self.assertEqual(task.mask_status, 'mask')

    def test_form_page_has_mask_ui(self):
        response = self.client.get(reverse('task_create'))
        self.assertContains(response, 'Маска ответа для ученика')
        self.assertContains(response, 'id="mask-preview"')
        self.assertContains(response, 'data-mask-draft')
        self.assertContains(response, '{{compare: &gt;}}')
        self.assertContains(response, 'mask_editor.js')

    def test_local_variant_copies_subitem_mask(self):
        from worksheets.models import Worksheet, WorksheetItem
        task = Task.objects.create(
            text_latex='Оригинал', answer_latex='1', created_by=self.teacher)
        worksheet = Worksheet.objects.create(title='Л', owner=self.teacher)
        item = WorksheetItem.objects.create(worksheet=worksheet, task=task, order=10)
        url = (reverse('task_edit', args=[task.pk])
               + f'?worksheet={worksheet.pk}&item={item.pk}')
        data = task_form_data(
            save_local='', answer_mask='{{number: 1}}',
            **formset_management('subitems', total=1),
            **{'subitems-0-order': 10, 'subitems-0-text_latex': 'а',
               'subitems-0-answer_latex': '2', 'subitems-0-solution_latex': '',
               'subitems-0-answer_mask': '{{number: 2}}'})
        self.client.post(url, data)
        item.refresh_from_db()
        variant = item.task
        self.assertNotEqual(variant.pk, task.pk)
        self.assertEqual(variant.answer_mask, '{{number: 1}}')
        self.assertEqual(variant.subitems.get().answer_mask, '{{number: 2}}')

    def test_make_variant_copies_masks(self):
        task = Task.objects.create(
            text_latex='T', answer_mask='{{number: 1}}',
            created_by=self.teacher)
        TaskSubitem.objects.create(task=task, order=10, text_latex='а',
                                   answer_mask='{{number: 2}}')
        copy = task.make_variant(self.teacher)
        self.assertEqual(copy.answer_mask, '{{number: 1}}')
        self.assertEqual(copy.subitems.get().answer_mask, '{{number: 2}}')


class MaskEndpointTests(TestCase):
    def setUp(self):
        make_teacher()
        self.client.login(username='teacher1', password='pass12345')

    def test_preview_renders_controls_and_errors(self):
        response = self.client.post(reverse('task_mask_preview'), {
            'mask': 'Больше {{choice: мальчиков|*девочек}}, всего {{number: 20}}'})
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['slots'], 2)
        self.assertIn('name="preview_s1"', data['html'])
        self.assertIn('<option value="девочек"', data['html'])
        self.assertIn('name="preview_s2"', data['html'])
        self.assertIn('data-check="preview_s2"', data['html'])

        response = self.client.post(reverse('task_mask_preview'),
                                    {'mask': '{{number: abc}} и {{foo: 1}}'})
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertEqual(len(data['errors']), 2)

    def test_preview_selftest(self):
        response = self.client.post(reverse('task_mask_preview'), {
            'mask': '{{number: 10}} и {{simplify: \\frac{2}{a+3}}}',
            'preview_s1': '10,0', 'preview_s2': '4/(2a+6)'})
        data = response.json()
        self.assertEqual(data['overall'], 'wrong')
        self.assertEqual(data['checks'],
                         {'preview_s1': 'ok', 'preview_s2': 'wrong'})
        self.assertIn('value="10,0"', data['html'])

    def test_preview_requires_teacher(self):
        self.client.logout()
        response = self.client.post(reverse('task_mask_preview'), {'mask': 'x'})
        self.assertNotEqual(response.status_code, 200)

    def test_draft(self):
        cases = {
            '10 см': '',
            '2,5': '{{number: 2,5}}',
            '$\\frac{5}{2}$': '{{number: \\frac{5}{2}}}',
            '(3; -4); (4; -3)': '{{pair: (3; -4); (4; -3)}}',
            '(-\\infty; -1]': '{{range: (-\\infty; -1]}}',
            'x>5': '{{range: x>5}}',
            '\\{-2;1\\}': '{{set: -2;1}}',
            r'1; \frac{1}{2}': r'{{set: 1; \frac{1}{2}}}',
            'x=\\pm3': '{{set: x=\\pm3}}',
            'Нет корней': '{{set: }}',
            'y=x+5': '{{equation: y=x+5}}',
            '\\frac{2}{a+3}': '{{simplify: \\frac{2}{a+3}}}',
            'да': '{{yesno: да}}',
            'Чётная.': '{{parity: чётная}}',
            '>': '{{compare: >}}',
            'см. рисунок': '',
        }
        for answer, expected in cases.items():
            data = self.client.post(reverse('task_mask_draft'),
                                    {'answer': answer}).json()
            self.assertEqual(data['mask'], expected, answer)
            self.assertEqual(data['ok'], bool(expected), answer)


class MaskCatalogTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.login(username='teacher1', password='pass12345')

    def test_masks_toggle_in_list_and_status_in_detail(self):
        with_mask = Task.objects.create(
            text_latex='С маской', answer_mask='{{number: 1}}',
            created_by=self.teacher)
        photo_only = Task.objects.create(
            text_latex='Только фото',
            created_by=self.teacher)
        Task.objects.create(text_latex='Без маски', created_by=self.teacher)
        response = self.client.get(reverse('task_list'))
        self.assertNotContains(response, 'mask-badge')
        self.assertContains(response, 'toggle-masks')
        self.assertNotContains(response, '>только фото<')
        response = self.client.get(reverse('task_detail', args=[with_mask.pk]))
        self.assertContains(response, 'Маска готова')
        response = self.client.get(reverse('task_detail', args=[photo_only.pk]))
        self.assertContains(response, 'фото решения')

    def test_short_answer_availability(self):
        task = Task.objects.create(text_latex='T', created_by=self.teacher)
        self.assertFalse(task.short_answer_available())
        self.assertEqual(task.mask_status, '')
        task.answer_mask = '{{number: 1}}'
        self.assertTrue(task.short_answer_available())
        # Подпункты: маска задачи не в счёт, нужна хотя бы одна у подпункта
        sub = TaskSubitem.objects.create(task=task, order=10, text_latex='а')
        self.assertFalse(task.short_answer_available([sub]))
        sub.answer_mask = '{{number: 2}}'
        self.assertTrue(task.short_answer_available([sub]))

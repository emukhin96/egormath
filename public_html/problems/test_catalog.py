"""Создание, дублирование и показ материалов в каталоге и листках."""
from django.test import TestCase
from django.urls import reverse

from worksheets.models import Worksheet, WorksheetItem
from .editor import mask_data
from .models import Task, Source, TaskSource
from .tests import make_teacher, make_student, formset_management


class CatalogTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.task = Task.objects.create(created_by=self.teacher, text_latex='Исходная',
            author_answer_latex='8', author_solution_latex='Авторское решение',
            answer_latex='9', solution_latex='AI решение', answer_mask='{{number: 8}}')
        self.sub = self.task.subitems.create(order=10, text_latex='Первый',
            author_answer_latex='2', author_solution_latex='Решение подпункта',
            answer_mask='{{number: 2}}')
        self.task.subitems.create(order=20, text_latex='Второй')
        self.source = Source.objects.create(title='Книга')
        TaskSource.objects.create(task=self.task, source=self.source, number='7')

    def test_duplicate_is_independent_and_preserves_materials(self):
        url = reverse('task_duplicate', args=[self.task.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        copy = Task.objects.exclude(pk=self.task.pk).get()
        self.assertRedirects(response, reverse('task_detail', args=[copy.pk]))
        self.assertIsNone(copy.variant_of)
        self.assertEqual(copy.author_solution_latex, self.task.author_solution_latex)
        self.assertEqual(copy.solution_latex, self.task.solution_latex)
        self.assertEqual(copy.answer_mask, self.task.answer_mask)
        self.assertEqual(copy.source_refs.get().source_id, self.source.pk)
        sub = copy.subitems.first()
        self.assertNotEqual(sub.pk, self.sub.pk)
        self.assertEqual(sub.author_solution_latex, self.sub.author_solution_latex)
        sub.text_latex = 'Изменённая копия'
        sub.save()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.text_latex, 'Первый')

    def test_worksheet_duplicate_preserves_selection_and_inserts_after(self):
        ws = Worksheet.objects.create(owner=self.teacher, title='Листок')
        item = WorksheetItem.objects.create(worksheet=ws, task=self.task, order=10,
            all_subitems=False, stars_override=2, columns_override=3)
        item.subitems.add(self.sub)
        last = WorksheetItem.objects.create(worksheet=ws, text_latex='После', order=10)
        response = self.client.post(reverse('task_duplicate', args=[self.task.pk]),
                                    {'worksheet': ws.pk, 'item': item.pk})
        self.assertRedirects(response, reverse('worksheet_detail', args=[ws.pk]))
        rows = list(ws.items.all())
        self.assertEqual([rows[0].pk, rows[2].pk], [item.pk, last.pk])
        copy = rows[1]
        self.assertEqual(copy.task.variant_of_id, self.task.pk)
        self.assertEqual((copy.stars_override, copy.columns_override), (2, 3))
        self.assertFalse(copy.all_subitems)
        self.assertEqual(list(copy.subitems.values_list('text_latex', flat=True)), ['Первый'])

    def test_duplicate_permissions(self):
        ws = Worksheet.objects.create(owner=make_teacher('other'), title='Чужой')
        item = WorksheetItem.objects.create(worksheet=ws, task=self.task)
        url = reverse('task_duplicate', args=[self.task.pk])
        self.assertEqual(self.client.post(url, {'worksheet': ws.pk, 'item': item.pk}).status_code, 403)
        self.client.force_login(make_student(self.teacher))
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(Task.objects.count(), 1)

    def test_catalog_has_toggles_without_quick_answer_or_badge(self):
        response = self.client.get(reverse('task_list'))
        self.assertContains(response, 'Раздел и темы')
        self.assertContains(response, 'toggle-catalog-answers')
        self.assertContains(response, 'toggle-masks')
        self.assertNotContains(response, 'textarea name="answer_latex"')
        self.assertNotContains(response, 'badge-mask')
        self.assertContains(response, 'ws-answers" hidden')

    def test_creation_saves_author_fields_and_subitem_mask(self):
        response = self.client.get(reverse('task_create'))
        self.assertContains(response, 'problem-columns')
        data = {'text_latex': 'Новая уникальная', 'stars': '0', 'columns': '1',
                'author_answer_latex': '4', 'author_solution_latex': 'Сложение',
                **formset_management('source_refs'), **formset_management('images'),
                **formset_management('subitems', total=1),
                'subitems-0-order': '1', 'subitems-0-text_latex': 'Один',
                'subitems-0-author_answer_latex': '2',
                'subitems-0-author_solution_latex': 'Автор подпункта',
                'subitems-0-answer_mask': '{{number: 2}}'}
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(text_latex='Новая уникальная')
        self.assertEqual(task.author_answer_latex, '4')
        self.assertEqual(task.subitems.get().answer_mask, '{{number: 2}}')

    def test_inline_preview_prefills_reference_without_check(self):
        self.task.subitems.all().delete()
        self.task.answer_mask = r'$S=${{number: \sqrt{2}}} {{choice: *да|нет}} {{order: a|b|c}}'
        preview = mask_data(self.task, include_preview=True)[0]['preview_html']
        self.assertIn(r'\sqrt{2}</math-field>', preview)
        self.assertIn('value="да" selected', preview)
        self.assertEqual(preview.count(' selected'), 4)
        self.assertNotIn('check-badge', preview)

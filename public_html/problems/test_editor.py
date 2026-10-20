"""Регрессии единой карточки, масок и локальных копий."""
import json

from django.test import TestCase
from django.urls import reverse

from assignments.checks import draft_mask, parse_mask
from worksheets.models import Worksheet, WorksheetItem
from .models import Task, TaskSubitem
from .tests import make_teacher, make_student, formset_management


class EditorTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.task = Task.objects.create(text_latex='Условие', created_by=self.teacher,
                                        author_answer_latex='42', answer_latex='43',
                                        solution_latex='Решение')
        self.url = reverse('task_manage', args=[self.task.pk])

    def test_unified_page_and_old_url(self):
        response = self.client.get(reverse('task_detail', args=[self.task.pk]))
        self.assertContains(response, 'problem-columns')
        self.assertContains(response, 'data-tax-picker')
        self.assertContains(response, 'class="problem-solution" open')
        self.assertNotContains(response, 'name="answer_type"')
        self.assertNotContains(response, 'name="answer_mode"')
        response = self.client.get(reverse('task_edit', args=[self.task.pk]) + '?worksheet=1&item=2')
        self.assertEqual(response.url, reverse('task_detail', args=[self.task.pk]) + '?worksheet=1&item=2')

    def test_sources_and_partial_save(self):
        self.assertEqual(self.task.effective_answer_latex, '42')
        self.assertEqual(self.client.get(self.url).json()['answers'][0]['author'], '42')
        response = self.client.post(self.url, {'block': 'condition', 'text_latex': 'Новое'})
        self.assertEqual(response.status_code, 200, response.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.text_latex, 'Новое')
        self.assertEqual(self.task.author_answer_latex, '42')
        self.assertEqual(self.task.answer_latex, '43')

    def test_number_preview_uses_math_keyboard_and_checks_radical(self):
        response = self.client.post(reverse('task_mask_preview'), {'mask': r'{{number: \sqrt{2}}}', 'prefix': 'preview'})
        self.assertContains(response, 'math-field')
        response = self.client.post(reverse('task_mask_check'), {'mask': r'{{number: \sqrt{2}}}', 'prefix': 'preview', 'preview_s1': r'\sqrt2'})
        self.assertEqual(response.json()['checks']['preview'], 'ok')

    def test_invalid_mask_does_not_change_task(self):
        response = self.client.post(self.url, {'block': 'masks', 'masks': json.dumps([
            {'id': None, 'mask': '{{number: nonsense}}'}])})
        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.answer_mask, '')

    def test_mask_save_and_reference_change(self):
        response = self.client.post(self.url, {'block': 'masks', 'masks': json.dumps([
            {'id': None, 'mask': '{{number: 42}}'}])})
        self.assertEqual(response.status_code, 200, response.content)
        self.client.post(self.url, {'block': 'answer', 'author_answer_latex': '44', 'answer_latex': '43'})
        self.task.refresh_from_db()
        self.assertEqual(self.task.answer_mask, '{{number: 42}}')
        self.assertEqual(self.task.effective_answer_latex, '44')

    def test_subitem_independent_answer_and_mask(self):
        sub = self.task.subitems.create(order=1, text_latex='а', author_answer_latex='5')
        response = self.client.post(self.url, {'block': 'mask', 'subitem': sub.pk, 'answer_mask': '{{number: 5}}'})
        self.assertEqual(response.status_code, 200, response.content)
        sub.refresh_from_db()
        self.assertEqual(sub.answer_mask, '{{number: 5}}')
        self.assertEqual(self.task.answer_mask, '')
        other = Task.objects.create(text_latex='Другая').subitems.create(order=1,text_latex='б')
        self.assertEqual(self.client.post(self.url, {'block':'mask', 'subitem':other.pk}).status_code, 404)

    def worksheet(self):
        worksheet = Worksheet.objects.create(title='Листок', owner=self.teacher)
        a = self.task.subitems.create(order=10, text_latex='а', author_answer_latex='1', author_solution_latex='Авторское решение')
        b = self.task.subitems.create(order=20, text_latex='б', answer_latex='2')
        item = WorksheetItem.objects.create(worksheet=worksheet, task=self.task, order=1, all_subitems=False)
        item.subitems.set([a])
        return item, a, b, self.url + f'?worksheet={worksheet.pk}&item={item.pk}'

    def test_local_copy_keeps_authors_and_selection(self):
        item, a, b, url = self.worksheet()
        response = self.client.post(url, {'block':'masks', 'scope':'local', 'masks':json.dumps([{'id':a.pk,'mask':'{{number: 1}}'}])})
        self.assertEqual(response.status_code,200,response.content)
        item.refresh_from_db()
        self.assertNotEqual(item.task_id,self.task.pk)
        self.assertFalse(item.all_subitems)
        selected=item.subitems.get()
        self.assertEqual(selected.text_latex,'а')
        self.assertEqual(selected.author_answer_latex,'1')
        self.assertEqual(selected.author_solution_latex,'Авторское решение')
        self.assertEqual(selected.answer_mask,'{{number: 1}}')
        self.assertEqual(item.task.author_answer_latex,'42')
        a.refresh_from_db()
        self.assertEqual(a.answer_mask,'')

    def test_invalid_local_mask_leaves_no_copy(self):
        item,a,b,url=self.worksheet()
        response=self.client.post(url,{'block':'masks','scope':'local','masks':json.dumps([{'id':a.pk,'mask':'{{bad: 1}}'}])})
        self.assertEqual(response.status_code,400)
        self.assertEqual(Task.objects.count(),1)
        item.refresh_from_db()
        self.assertEqual(item.task_id,self.task.pk)

    def test_missing_only_does_not_replace_existing_mask(self):
        item,a,b,url=self.worksheet()
        a.answer_mask='{{number: 1}}';a.save()
        response=self.client.post(url,{'block':'masks','scope':'global','missing_only':'1','masks':json.dumps([{'id':a.pk,'mask':'{{number: 99}}'}])})
        self.assertEqual(response.status_code,200,response.content)
        a.refresh_from_db();self.assertEqual(a.answer_mask,'{{number: 1}}')

    def test_unselected_mask_rejected(self):
        item,a,b,url=self.worksheet()
        response=self.client.post(url,{'block':'masks','scope':'global','masks':json.dumps([{'id':b.pk,'mask':'{{number: 2}}'}])})
        self.assertEqual(response.status_code,400)

    def test_scope_required_and_foreign_worksheet_denied(self):
        item,a,b,url=self.worksheet()
        self.assertEqual(self.client.post(url,{'block':'condition','text_latex':'X'}).status_code,400)
        self.client.force_login(make_teacher('other'))
        self.assertEqual(self.client.get(url).status_code,403)
        self.client.force_login(make_student(self.teacher))
        self.assertNotEqual(self.client.get(self.url).status_code,200)

    def test_structure_local_copy_keeps_subitem_answers(self):
        item,a,b,url=self.worksheet()
        data={'block':'subitems','scope':'local',**formset_management('subitems',total=2,initial=2),
              'subitems-0-id':a.pk,'subitems-0-order':10,'subitems-0-text_latex':'Новое а',
              'subitems-1-id':b.pk,'subitems-1-order':20,'subitems-1-text_latex':'б'}
        response=self.client.post(url,data)
        self.assertEqual(response.status_code,200,response.content)
        item.refresh_from_db()
        self.assertEqual(item.subitems.get().author_answer_latex,'1')
        self.assertEqual(item.subitems.get().text_latex,'Новое а')

    def test_slanted_union_and_separate_preview_prefixes(self):
        mask=draft_mask(r'$a\leqslant 1$ или $a\geqslant 2$')
        self.assertTrue(parse_mask(mask).is_valid)
        response=self.client.post(reverse('task_mask_check'),{
            'mask':mask,'prefix':'preview_2','preview_2_s1':r'(-\infty;1] \cup [2;\infty)'})
        self.assertEqual(response.json()['checks'],{'preview_2':'ok','preview_2_s1':'ok'})

    def test_sources_formset_is_rendered_and_saved_locally(self):
        from .models import Source, TaskSource
        source = Source.objects.create(title='Учебник')
        ref = TaskSource.objects.create(task=self.task, source=source, number='12')
        page = self.client.get(reverse('task_detail', args=[self.task.pk]))
        self.assertContains(page, 'Учебник')
        self.assertContains(page, 'name="source_refs-0-number"')
        item, a, b, url = self.worksheet()
        response = self.client.post(url, {'block': 'sources', 'scope': 'local',
            **formset_management('source_refs', total=1, initial=1),
            'source_refs-0-id': ref.pk, 'source_refs-0-source': source.pk,
            'source_refs-0-number': '13'})
        self.assertEqual(response.status_code, 200, response.content)
        item.refresh_from_db()
        self.assertEqual(item.task.source_refs.get().number, '13')
        ref.refresh_from_db()
        self.assertEqual(ref.number, '12')

    def test_foreign_formset_id_rejected_without_local_copy(self):
        item, a, b, url = self.worksheet()
        other = Task.objects.create(text_latex='Другая')
        foreign = other.subitems.create(order=1, text_latex='Чужой')
        response = self.client.post(url, {'block': 'subitems', 'scope': 'local',
            **formset_management('subitems', total=1, initial=1),
            'subitems-0-id': foreign.pk, 'subitems-0-order': 1,
            'subitems-0-text_latex': 'Изменение'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Task.objects.count(), 2)

    def test_full_task_editor_can_edit_unselected_subitem(self):
        item, a, b, url = self.worksheet()
        full = url + '&view=task'
        self.assertEqual([row['id'] for row in self.client.get(full).json()['answers']], [a.pk, b.pk])
        response = self.client.post(full, {'block': 'masks', 'scope': 'local',
            'masks': json.dumps([{'id': b.pk, 'mask': '{{number: 2}}'}])})
        self.assertEqual(response.status_code, 200, response.content)
        item.refresh_from_db()
        self.assertEqual(item.subitems.get().text_latex, 'а')
        self.assertEqual(item.task.subitems.get(text_latex='б').answer_mask, '{{number: 2}}')
        b.refresh_from_db()
        self.assertEqual(b.answer_mask, '')

    def test_metadata_uses_shared_grade_and_difficulty_controls(self):
        from .models import GradeBand
        bands = [GradeBand.objects.get_or_create(code=f'GRADE_{n}', defaults={'name': f'{n} класс'})[0] for n in (7, 8)]
        response = self.client.post(self.url, {'block': 'metadata', 'stars': '1',
            'columns': '2', 'grades_submitted': '1',
            'grade_bands': [b.code for b in bands], 'difficulty': '3'})
        self.assertEqual(response.status_code, 200, response.content)
        self.task.refresh_from_db()
        self.assertEqual(set(self.task.grade_bands.all()), set(bands))
        self.assertEqual(self.task.grade_level, 7)
        self.assertEqual(self.task.difficulty, 3)
        self.assertIn('data-grades="1"', response.json()['html'])
        self.assertNotIn('name="grade_level"', response.json()['html'])

    def test_mask_draft_uses_condition_from_request(self):
        response = self.client.post(reverse('task_mask_draft'), {
            'answer': '4', 'condition': 'Решите уравнение x-4=0.'})
        self.assertEqual(response.json()['mask'], '$x =${{range: 4}}')
        self.task.answer_mask = '$x =${{range: 4}}'
        self.task.save()
        response = self.client.get(reverse('task_detail', args=[self.task.pk]))
        self.assertContains(response, '$x =${{range: 4}}')

    def test_local_source_mapping_survives_reverse_queryset_order(self):
        from unittest.mock import patch
        from .models import Source, TaskSource
        source=Source.objects.create(title='Книга')
        first=TaskSource.objects.create(task=self.task,source=source,number='1')
        other_source=Source.objects.create(title='Другая книга')
        second=TaskSource.objects.create(task=self.task,source=other_source,number='2')
        item,a,b,url=self.worksheet()
        with patch.object(TaskSource._meta,'ordering',['-pk']):
            response=self.client.post(url,{'block':'sources','scope':'local',
                **formset_management('source_refs',total=2,initial=2),
                'source_refs-0-id':second.pk,'source_refs-0-source':other_source.pk,'source_refs-0-number':'20',
                'source_refs-1-id':first.pk,'source_refs-1-source':source.pk,'source_refs-1-number':'10'})
        self.assertEqual(response.status_code,200,response.content)
        item.refresh_from_db()
        self.assertEqual(list(item.task.source_refs.order_by('pk').values_list('number',flat=True)),['20','10'])
        self.assertEqual(set(self.task.source_refs.values_list('number',flat=True)),{'1','2'})

    def test_manage_supplies_inline_preview_in_same_response(self):
        self.task.answer_mask='{{number: 42}}'
        self.task.save()
        response=self.client.get(self.url,{'preview':'1'})
        self.assertIn('math-field',response.json()['answers'][0]['preview_html'])

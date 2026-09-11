"""Разделение по PDF должно сохранять условия и не угадывать границы."""
from copy import deepcopy
from django.test import SimpleTestCase
from problems.textbook_parser import TaskDraft, bundle_from_text
from problems.ostromogilsky_splits import recover_geometry_splits


class PdfVerifiedSplitTests(SimpleTestCase):
    def setUp(self):
        self.first = 'Угол $A B C$ равен 44°. Найдите угол $A O C$.'
        self.second = 'Угол $A B C$ равен 16°. Найдите угол $A O C$.'
        self.parent = TaskDraft(
            external_id='16.1', source_number='16.1', source_path=['Окружности'],
            collection_key='circles', collection_title='Окружности', topic_original='Углы',
            text_latex=self.first + '\n\\taskpic{1}\n\n' + self.second + '\n\\taskpic{2}',
            images=['figure-0012_first', 'figure-0012_second'],
            author_answer_latex='$88$', author_solution_latex='Решение первого вопроса.',
            tags=['DEMO'])
        self.contexts = [{'id':'16.1','page':12,'body':self.first},
                         {'id':'16.2','page':12,'body':self.second}]
        self.answers = {'16.1':'$88$', '16.2':'$32$'}

    def test_split_keeps_each_image_answer_and_metadata(self):
        before = deepcopy(self.parent)
        rows, recovered = recover_geometry_splits([self.parent], self.contexts, self.answers)
        self.assertEqual(recovered, ['16.2'])
        self.assertEqual([row.images for row in rows], [['figure-0012_first'],['figure-0012_second']])
        self.assertEqual([row.author_answer_latex for row in rows], ['$88$','$32$'])
        self.assertEqual(rows[1].text_latex, self.second + '\n\\taskpic{1}')
        self.assertEqual(rows[1].exam_item_codes, ['OGE_2026_16'])
        self.assertEqual(rows[1].source_path, ['Окружности'])
        self.assertEqual(rows[0].tags, ['DEMO'])
        self.assertEqual(rows[1].tags, [])
        self.assertEqual(rows[1].author_solution_latex, '')
        self.assertEqual(self.parent, before)
        repeated, added = recover_geometry_splits(rows, self.contexts, self.answers)
        self.assertEqual(repeated, rows)
        self.assertEqual(added, [])

    def test_any_mismatch_keeps_the_entire_original(self):
        wrong_text = deepcopy(self.contexts)
        wrong_text[1]['body'] = self.second.replace('16', '61')
        wrong_page = deepcopy(self.contexts)
        wrong_page[1]['page'] = 13
        for contexts in [wrong_text, wrong_page]:
            rows, added = recover_geometry_splits([self.parent], contexts, self.answers)
            self.assertEqual(rows, [self.parent])
            self.assertEqual(added, [])
        parent = deepcopy(self.parent)
        parent.text_latex = parent.text_latex.replace('taskpic{2}', 'taskpic{1}')
        self.assertEqual(recover_geometry_splits([parent], self.contexts, self.answers), ([parent], []))
        self.assertEqual(recover_geometry_splits([self.parent], self.contexts, {}), ([self.parent], []))

    def test_bundle_path_uses_pdf_contexts(self):
        text = ('Задача 16.1.\n' + self.first + '\n\\includegraphics{figure-0012_first}\n\n'
                + self.second + '\n\\includegraphics{figure-0012_second}')
        bundle = bundle_from_text('ostromogilsky', text, answers=self.answers,
                                  expected_ids={'16.1','16.2'}, pdf_task_contexts=self.contexts)
        self.assertEqual([row.external_id for row in bundle.tasks], ['16.1','16.2'])
        self.assertEqual(bundle.diagnostics['missing_task_ids'], [])
        self.assertEqual(bundle.diagnostics['pdf_verified_splits'], ['16.2'])

    def test_comparison_does_not_ignore_math_operator(self):
        from problems.ostromogilsky_splits import _canonical
        self.assertNotEqual(_canonical('$x+2=5$'), _canonical('x−2=5'))


class PracticalSplitTests(SimpleTestCase):
    def setUp(self):
        self.common = 'Общий план маршрутов.\\taskpic{1}'
        def draft(key, question):
            return TaskDraft(external_id=key,source_number=key,source_path=['Маршруты'],
                             collection_key='routes',collection_title='Маршруты',topic_original='Практические задачи',
                             text_latex=self.common+'\n\n'+question,images=['shared-plan'])
        self.parent = draft('2.1.8','Второй вопрос.\n\nТретий вопрос.')
        self.neighbor = draft('4.1.8','Четвёртый вопрос.')
        self.contexts = [{'id':'2.1.8','body':'Второй вопрос.','page':1},
                         {'id':'3.1.8','body':'Третий вопрос.','page':1},
                         {'id':'4.1.8','body':'Четвёртый вопрос.','page':1}]

    def test_keeps_common_condition_and_own_question(self):
        from problems.ostromogilsky_splits import recover_practical_splits
        original = deepcopy(self.parent)
        rows, ids = recover_practical_splits([self.parent,self.neighbor],self.contexts,{'3.1.8':'$12$'})
        self.assertEqual(ids,['3.1.8'])
        self.assertEqual(rows[0].text_latex,self.common+'\n\nВторой вопрос.')
        self.assertEqual(rows[1].text_latex,self.common+'\n\nТретий вопрос.')
        self.assertEqual(rows[1].images,['shared-plan'])
        self.assertEqual(rows[1].author_answer_latex,'$12$')
        self.assertEqual(rows[1].exam_item_codes,['OGE_2026_03'])
        self.assertEqual(self.parent,original)
        self.assertEqual(recover_practical_splits(rows,self.contexts,{'3.1.8':'$12$'}),(rows,[]))

    def test_mismatch_does_not_remove_any_text(self):
        from problems.ostromogilsky_splits import recover_practical_splits
        self.contexts[1]['body']='Другой вопрос.'
        original=[self.parent,self.neighbor]
        self.assertEqual(recover_practical_splits(original,self.contexts,{'3.1.8':'$12$'}),(original,[]))


class TireTableTests(SimpleTestCase):
    def test_preserves_all_sizes_and_rejects_unknown_trailing_rows(self):
        from problems.ostromogilsky_parser import normalize_oge_tire_tables
        table = r'''\begin{tabular}[t]{|l|l|l|}
\multirow[b]{2}{*}{Ширина шины (мм)} & \multicolumn{2}{|c|}{Диаметр диска (дюймы)} \\
\hline
 & 14 & 15 \\
\hline
195 & 195/65; 195/60 & — \\
\hline
205 & 205/60 & 205/55; 205/50 \\
\hline
\end{tabular}'''
        result = normalize_oge_tire_tables(table)
        self.assertIn('Диск $14$ дюймов & Диск $15$ дюймов',result)
        self.assertIn(r'195 & 195/65; 195/60 & — \\',result)
        self.assertIn(r'205 & 205/60 & 205/55; 205/50 \\',result)
        self.assertNotIn('multirow',result)
        self.assertEqual(normalize_oge_tire_tables(result),result)
        unknown = table.replace(r'\end{tabular}', 'Примечание: особый размер.\n'+r'\end{tabular}')
        self.assertEqual(normalize_oge_tire_tables(unknown),unknown)

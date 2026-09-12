from django.test import SimpleTestCase

from .ege_parser import parse_ege


class EgeParserTests(SimpleTestCase):
    def test_uses_pdf_context_for_lost_marker_without_gluing_it_to_previous(self):
        text = '''№1. Планиметрия.\\\\
Треугольник.\\\\
Задача 1.1. DEMO
Первое условие.
Ответ: Ответ: Аналоги Ответ

Потерянное условие.
Задача 1.3.
Третье условие.
'''
        contexts = {'tasks': {
            '1.1': {'text': 'Задача 1.1.\nПервое условие.'},
            '1.2': {'text': 'Задача 1.2.\nВторое условие.'},
            '1.3': {'text': 'Задача 1.3.\nТретье условие.'},
        }}
        tasks, diagnostics = parse_ege(
            text, answers={'1.1': '$1$', '1.2': '$2$', '1.3': '$3$'},
            expected_ids=set(contexts['tasks']), pdf_task_contexts=contexts)
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(set(by_id), {'1.1', '1.2', '1.3'})
        self.assertNotIn('Потерянное условие', by_id['1.1'].text_latex)
        self.assertIn('Второе условие', by_id['1.2'].text_latex)
        self.assertEqual(diagnostics['recovered_task_ids'], ['1.2'])

    def test_analogs_are_grouped_under_their_prototype(self):
        text = '''№2. Векторы.\\\\
Длина вектора.\\\\
Задача 2.1.
Условие прототипа.
Аналог 2.1.1. SIM
Условие аналога.
'''
        tasks, _diagnostics = parse_ege(
            text, answers={'2.1': '$1$', '2.1.1': '$2$'},
            expected_ids={'2.1', '2.1.1'})
        analog = next(task for task in tasks if task.external_id == '2.1.1')
        self.assertEqual(analog.source_path[-2:], ['Прототип 2.1', 'Аналоги'])
        self.assertEqual(analog.collection_key, 'ege/02/2.1/analogs')
        self.assertEqual(analog.tags, ['SIM'])

    def test_keeps_only_lettered_subitems_and_normalizes_latin_label(self):
        text = '''№20. «Нестандартные» задачи.
Задача 20.2.
В условии есть числа 1) и 2), которые не являются подпунктами.
\\begin{itemize}
\\item[a)] Первый вопрос.
\\item[б)] Второй вопрос.
\\item[в)] Третий вопрос.
\\end{itemize}
'''
        tasks, _ = parse_ege(text, answers={'20.2': ''}, expected_ids={'20.2'})
        task = tasks[0]
        self.assertEqual(task.text_latex, 'В условии есть числа 1) и 2), которые не являются подпунктами.')
        self.assertEqual([item.label for item in task.subitems], ['а', 'б', 'в'])

    def test_removes_empty_layout_table_but_keeps_data_table(self):
        text = '''№6. Случайные величины.
Задача 6.1.
Данные:
\\begin{tabular}{|l|l|}
Цена & 100 \\\\
Число & 5 \\\\
\\hline
\\end{tabular}
Задача 8.2.
\\begin{tabular}{|l|l|}
\\hline
Аналоги & Ответ \\\\
\\hline
\\end{tabular}
Найдите значение.
'''
        tasks, _ = parse_ege(text, answers={'6.1': '', '8.2': ''}, expected_ids={'6.1', '8.2'})
        by_id = {task.external_id: task for task in tasks}
        self.assertIn('Цена & 100', by_id['6.1'].text_latex)
        self.assertIn(r'\end{tabular}', by_id['6.1'].text_latex)
        self.assertNotIn('Аналоги', by_id['8.2'].text_latex)
        self.assertIn('Найдите значение', by_id['8.2'].text_latex)

    def test_uses_stable_chapter_title(self):
        text = '№20. Случайный OCR-заголовок.}\nЗадача 20.1.\nУсловие.\n'
        tasks, _ = parse_ege(text, answers={'20.1': ''}, expected_ids={'20.1'})
        self.assertEqual(tasks[0].topic_original, '«Нестандартные» задачи')
        self.assertNotIn('}', tasks[0].source_path[0])

    def test_removes_navigation_tail_and_keeps_pdf_tags(self):
        text = r'''Задача 2.3.
Найдите длину вектора. Ответ: Ответ:
 | + — - □
\hline \& \\
'''
        tasks, _ = parse_ege(text, answers={'2.3': '3'}, expected_ids={'2.3'},
                             pdf_task_contexts={'tasks': {'2.3': {'text': 'Задача 2.3. DEMO'}}})
        self.assertEqual(tasks[0].text_latex, 'Найдите длину вектора.')
        self.assertEqual(tasks[0].tags, ['DEMO'])

    def test_proof_has_no_numeric_answer_and_second_part_gets_it(self):
        tasks, diagnostics = parse_ege(
            'Задача 18.1.\nТреугольник.\nа) Докажите равенство.\nб) Найдите площадь.',
            answers={'18.1': r'\(5\)'})
        self.assertEqual(tasks[0].author_answer_latex, '')
        self.assertEqual(tasks[0].subitems[1].author_answer_latex, r'\(5\)')
        self.assertEqual(diagnostics['answers_matched'], 1)

    def test_kilometres_ocr_does_not_change_kelvin(self):
        tasks, _ = parse_ege('Задача 10.1.\n' + r'Температура \(1\mathrm{K}\), путь \(2\mathrm{KM}\).',
                             answers={'10.1': '2'})
        self.assertIn(r'\mathrm{K}', tasks[0].text_latex)
        self.assertIn(r'\text{км}', tasks[0].text_latex)

    def test_answer_caption_does_not_leave_unclosed_brace(self):
        tasks, _ = parse_ege('Задача 12.1.\nУсловие.\n' + r'\caption{Ответ:}',
                             answers={'12.1': '2'})
        self.assertEqual(tasks[0].text_latex, 'Условие.')

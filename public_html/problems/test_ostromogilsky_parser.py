from django.test import SimpleTestCase

from problems.ostromogilsky_parser import (
    attach_grid_figures, expand_shared_ids, is_answer_blank_image,
    normalize_oge_answer, normalize_oge_choices, parse_answer_key_text, parse_ostromogilsky,
    select_figure_span)
from problems.ostromogilsky_parser import strip_oge_answer_tail
from problems.textbook_parser import bundle_from_text


NAV = r"""
\begin{center}
\begin{tabular}[t]{|l|l|l|l|l|l|l|l|l|}
\hline
Оглавление & $\lll$ & < & 5 1254 & > & \textbackslash gg & Справочный материал \\
\hline
\end{tabular}
\end{center}
"""

SAMPLE_TEX = r"""
\section*{ПРАКТИЧЕСКИЕ ЗАДАЧИ}
№1-№5. Маршруты.

Текст к задачам 1.1-5.1. Аналоги

Общий план местности.
\includegraphics[max width=\textwidth, alt={}, center]{map-1}

Задача 1.1. Ответ

Какими цифрами обозначены пункты?
""" + NAV + r"""
\begin{center}
\begin{tabular}[t]{|l|l|l|}
\hline
Ответ: &  &  \\
\hline
\end{tabular}
\end{center}

Задача 2.1.\\
Ответ

Сколько километров по шоссе?

Задача 3.1. Ответ
Найдите расстояние по прямой.

Задача 4.1. Ответ
Сколько минут по лесной дорожке?

Задача 5.1. Ответ
В каком магазине набор дешевле?

\section*{АЛГЕБРА}
№6. Дроби.
Десятичные дроби.

Задача 6.1. Аналоги Ответ
Найдите значение выражения $5,6 + 9,7$.
Ответ:

Задача 6.3. DEMO\\
Аналоги
Ответ
Найдите значение выражения $5,2 \cdot 3,1$.
Оглавление
$\textbackslash lll$
Справочный материал

\section*{№7. Координатная прямая.}
Задача 7.1. Аналоги Ответ
Какое утверждение верно?
1) $a-5<0$; 2) $5-a<0$.
Прототип\\
Ответ:\\
Ответ:

\section*{№8. Степени и корни.}
не должно попасть в 7.1

Аналог 6.1.1. Ответ
Найдите значение выражения $6,8 + 2,6$.
\includegraphics[max width=\textwidth]{936a4675-a02d-4784-a1e2-f10dd0ecfde2-0874_67_593_732_1228}

\section*{АНАЛОГИ}
Аналог 6.3.1.\\
Прототип\\
Ответ
Ещё одна дробь.
\includegraphics{936a4675-a02d-4784-a1e2-f10dd0ecfde2-0874_206_402_511_1327}

№1.1 & 142. & №3.1.3 & 17. \\
\section*{СПРАВОЧНЫЙ МАТЕРИАЛ}
не импортировать
"""

ANSWERS = {
    '1.1': '231',
    '2.1': '41',
    '3.1': '13',
    '4.1': '36',
    '5.1': '1420',
    '6.1': '15,3',
    '6.3': '16,12',
    '6.1.1': '9,4',
    '6.3.1': '1',
    '7.1': '2',
}


class OstromogilskyParserTests(SimpleTestCase):
    def test_explicit_itemize_numbers_and_tariff_bullets(self):
        numbered = r'\begin{itemize}\item[1)] Первое.\item[2)] Второе.\item[3)] Третье.\end{itemize}'
        self.assertEqual(normalize_oge_choices(numbered), '1) Первое.\\\\\n2) Второе.\\\\\n3) Третье.')
        bullets = r'\begin{itemize}\item[-] Минуты.\item[-] Интернет.\end{itemize}'
        self.assertEqual(normalize_oge_choices(bullets), '— Минуты.\\\\\n— Интернет.')
        broken = numbered.replace('[2)]', '[4)]')
        self.assertEqual(normalize_oge_choices(broken), broken)

    def test_inline_empty_answer_tail_does_not_remove_condition(self):
        tex = 'Задача 9.3. Ответ\nРешите $7x-7=19+5x$. Ответ: Ответ: |\n\n— □'
        tasks, _ = parse_ostromogilsky(tex, answers={'9.3': '$13$'})
        self.assertEqual(tasks[0].text_latex, 'Решите $7x-7=19+5x$.')

    def test_nonempty_answer_and_response_instruction_are_preserved(self):
        for text in ['Ответ дайте в метрах.', 'Ответ: $-2$', 'Ответ: нет решений.',
                     'Заполните: $|x|+1$', 'Выберите знак: +']:
            self.assertEqual(strip_oge_answer_tail(text), text)

    def test_answer_blank_glyph_tail_is_removed(self):
        tex = 'Задача 10.1. Ответ\nВычислите вероятность события.\n\nОтвет:\n\n| + — □'
        tasks, _ = parse_ostromogilsky(tex, answers={'10.1': '$0,5$'})
        self.assertEqual(tasks[0].text_latex, 'Вычислите вероятность события.')

    def test_unmarked_glyph_and_math_symbols_are_preserved(self):
        for tail in ['+', '$|x|+1$', r'$\square$']:
            tex = 'Задача 10.1. Ответ\nВыберите знак.\n\n' + tail
            tasks, _ = parse_ostromogilsky(tex, answers={'10.1': '$1$'})
            self.assertIn(tail, tasks[0].text_latex)

    def test_trailing_section_title_belongs_to_next_task(self):
        tex = r'''
Задача 17.9. Ответ
Найдите высоту параллелограмма.
Ответ:

Ромб.

Задача 17.10. Ответ
В ромбе найдите угол.
'''
        tasks, _ = parse_ostromogilsky(tex, answers={'17.9': '$3$', '17.10': '$45$'})
        self.assertEqual(tasks[0].text_latex, 'Найдите высоту параллелограмма.')
        self.assertIn('В ромбе найдите угол.', tasks[1].text_latex)

    def test_section_words_inside_statement_and_question_are_preserved(self):
        tex = 'Задача 17.9. Ответ\nРомб. Найдите площадь.\n\nОтвет дайте в квадратных сантиметрах.'
        tasks, _ = parse_ostromogilsky(tex, answers={'17.9': '$3$'})
        self.assertIn('Ромб. Найдите площадь.', tasks[0].text_latex)
        self.assertIn('Ответ дайте в квадратных сантиметрах.', tasks[0].text_latex)

    def test_inline_heading_preserves_both_tasks(self):
        tex = r"""
Задача 8.22. Аналоги Ответ
Найдите $a^3$ при $a=3$. Ответ: Ответ: Задача 8.23. Аналоги Ответ
Найдите $a^3$ при $a=5$.
"""
        tasks, _ = parse_ostromogilsky(tex, answers={'8.22': '27', '8.23': '125'})
        self.assertEqual([task.external_id for task in tasks], ['8.22', '8.23'])
        self.assertNotIn('a=5', tasks[0].text_latex)
        self.assertIn('a=5', tasks[1].text_latex)

    def test_analog_uses_prototype_cluster_not_last_heading(self):
        tex = r"""
№1-№5. Маршруты.
Задача 1.1. Ответ
Вопрос о маршрутах.
№1-№5. Тарифы.
Задача 1.8. Ответ
Вопрос о тарифах.
\section*{АНАЛОГИ}
Аналог 1.1.1. Ответ
Другой вопрос о маршрутах.
"""
        tasks, _ = parse_ostromogilsky(tex, answers={'1.1': '1', '1.8': '2', '1.1.1': '3'})
        self.assertEqual(tasks[-1].source_path[1], 'Маршруты')
        self.assertIn('/маршруты/', tasks[-1].collection_key)

    def test_requires_answer_key(self):
        with self.assertRaises(ValueError):
            parse_ostromogilsky(SAMPLE_TEX)

    def test_splits_tasks_and_merges_answers(self):
        tasks, diagnostics = parse_ostromogilsky(
            SAMPLE_TEX, answers=ANSWERS, expected_ids=set(ANSWERS))
        by_id = {task.external_id: task for task in tasks}
        self.assertEqual(sorted(by_id), sorted(ANSWERS))
        self.assertIn('Общий план местности', by_id['1.1'].text_latex)
        self.assertIn('Общий план местности', by_id['3.1'].text_latex)
        self.assertIn(r'\taskpic{1}', by_id['1.1'].text_latex)
        self.assertNotIn('Оглавление', by_id['1.1'].text_latex)
        self.assertNotIn('СПРАВОЧНЫЙ', by_id['6.1.1'].text_latex)
        self.assertNotIn('142.', by_id['6.1.1'].text_latex)
        self.assertEqual(by_id['6.1'].author_answer_latex, '15,3')
        self.assertEqual(by_id['6.3'].author_answer_latex, '16,12')
        self.assertEqual(by_id['7.1'].author_answer_latex, '2')
        self.assertEqual(by_id['6.3'].tags, ['DEMO'])
        self.assertEqual(by_id['6.1'].exam_item_codes, ['OGE_2026_06'])
        self.assertEqual(by_id['1.1'].exam_item_codes, ['OGE_2026_01'])
        self.assertEqual(by_id['6.1'].grade_band_codes, ['GRADE_9'])
        self.assertEqual(by_id['6.1'].source_path[0], '№6. Дроби')
        self.assertEqual(by_id['6.1.1'].source_path[1], 'Аналоги')
        self.assertEqual(by_id['1.1'].source_path[1], 'Маршруты')
        self.assertNotIn('Прототип', by_id['6.3'].text_latex)
        self.assertNotIn('Аналоги', by_id['6.3'].text_latex)
        self.assertNotIn('Оглавление', by_id['6.3'].text_latex)
        self.assertNotIn('Справочный', by_id['6.3'].text_latex)
        self.assertNotIn('Прототип', by_id['7.1'].text_latex)
        self.assertNotIn('Ответ:', by_id['7.1'].text_latex)
        self.assertNotIn('№8', by_id['7.1'].text_latex)
        self.assertNotIn('Степени', by_id['7.1'].text_latex)
        self.assertFalse(by_id['6.1.1'].images)
        self.assertTrue(by_id['6.3.1'].images)
        self.assertEqual(diagnostics['prototype_count'], 8)
        self.assertEqual(diagnostics['analog_count'], 2)
        self.assertEqual(diagnostics['missing_task_ids'], [])

    def test_missing_answer_lowers_confidence_except_proofs(self):
        tex = SAMPLE_TEX.replace(
            r'\section*{АНАЛОГИ}',
            'Задача 24.1. Ответ\nДокажите равенство.\n\n\\section*{АНАЛОГИ}')
        partial = {key: value for key, value in ANSWERS.items() if key != '6.1'}
        tasks, _ = parse_ostromogilsky(tex, answers=partial)
        by_id = {task.external_id: task for task in tasks}
        self.assertTrue(
            any('авторского ответа' in item for item in by_id['6.1'].warnings))
        self.assertLess(by_id['6.1'].confidence, 1)
        self.assertEqual(by_id['24.1'].warnings, [])
        self.assertEqual(by_id['24.1'].confidence, 1.0)

    def test_expand_shared_ids_varies_exam_number(self):
        self.assertEqual(
            expand_shared_ids('1.1', '5.1'),
            ['1.1', '2.1', '3.1', '4.1', '5.1'])
        self.assertEqual(
            expand_shared_ids('1.1.2', '5.1.2'),
            ['1.1.2', '2.1.2', '3.1.2', '4.1.2', '5.1.2'])

    def test_answer_key_and_normalize(self):
        parsed = parse_answer_key_text('№6.1\n15,3.\n№6.3\n16,12.\n№19.2\n< 13 >.\n')
        self.assertEqual(parsed['6.1'], '15,3.')
        self.assertEqual(normalize_oge_answer('15,3.'), '$15,3$')
        self.assertEqual(normalize_oge_answer('< 13 >.'), '$13$')
        self.assertEqual(normalize_oge_answer('−4; −3; 3.'), r'$-4; -3; 3$')
        self.assertEqual(normalize_oge_answer('29 700.'), '$29700$')

    def test_answer_sets_degrees_and_existing_fraction(self):
        self.assertEqual(normalize_oge_answer('{2} ∪(3; 5).'),
                         r'$\{2\} \cup (3; 5)$')
        self.assertEqual(normalize_oge_answer('60∘и 120∘'),
                         r'$60^{\circ}$ и $120^{\circ}$')
        self.assertEqual(normalize_oge_answer('2 и 30'), '$2$ и $30$')
        fraction = r'$\left\{\frac{25}{64}\right\}$'
        self.assertEqual(normalize_oge_answer(fraction),
                         r'$\displaystyle \left\{\frac{25}{64}\right\}$')
        for answer in [r'$\{2\} \cup (3; 5)$', '$142$', normalize_oge_answer(fraction)]:
            self.assertEqual(normalize_oge_answer(answer), answer)

    def test_bundle_from_text_wires_profile(self):
        bundle = bundle_from_text(
            'ostromogilsky', SAMPLE_TEX, answers=ANSWERS)
        self.assertEqual(bundle.profile, 'ostromogilsky')
        self.assertEqual(bundle.diagnostics['answers_matched'], 10)
        self.assertTrue(all(task.author_answer_latex for task in bundle.tasks))

    def test_answer_blank_images_and_figure_span(self):
        self.assertTrue(is_answer_blank_image(
            '936a4675-a02d-4784-a1e2-f10dd0ecfde2-0874_67_593_732_1228'))
        self.assertFalse(is_answer_blank_image(
            '936a4675-a02d-4784-a1e2-f10dd0ecfde2-0874_206_402_511_1327'))
        self.assertFalse(is_answer_blank_image(
            '936a4675-a02d-4784-a1e2-f10dd0ecfde2-0026_70_701_714_683'))
        self.assertFalse(is_answer_blank_image(
            '936a4675-a02d-4784-a1e2-f10dd0ecfde2-0030_118_795_1618_638'))
        self.assertEqual(select_figure_span(
            [(11, 80), (180, 323), (373, 419)], 430), (180, 323))
        self.assertEqual(select_figure_span(
            [(11, 86), (157, 177), (192, 332), (346, 367), (394, 439)], 450),
            (157, 367))

    def test_choices_preserve_source_numbers_without_enumerate(self):
        source = r'\begin{enumerate}\item $a<0$;\item $a>0$;\item $a=0$;\item нет решений.\end{enumerate}'
        result = normalize_oge_choices(source)
        self.assertEqual(result, '1) $a<0$;\\\\\n2) $a>0$;\\\\\n3) $a=0$;\\\\\n4) нет решений.')
        self.assertEqual(normalize_oge_choices(result), result)

    def test_incomplete_choices_require_review(self):
        source = r'\begin{enumerate}\item $a<0$;\item $a>0$.\end{enumerate}'
        self.assertEqual(normalize_oge_choices(source), source)

    def test_choice_number_misread_inside_math(self):
        source = '\\begin{enumerate}\\item нет решений;\\\\\n$2)(-\\infty;4)$;\n\\item $(2;+\\infty)$;\\item (2;4).\\end{enumerate}'
        result = normalize_oge_choices(source)
        self.assertIn('2) $(-\\infty;4)$;', result)
        self.assertIn('4) (2;4).', result)
        self.assertNotIn('enumerate', result)

    def test_attach_grid_figures_replaces_ocr(self):
        tex = r"""
\section*{ПРАКТИЧЕСКИЕ ЗАДАЧИ}
\section*{№18. Задачи на клетчатой бумаге.}
Задача 18.1.\\
Аналоги\\
Ответ
На клетчатой бумаге изображён ромб.
\includegraphics{936a4675-a02d-4784-a1e2-f10dd0ecfde2-0097_390_597_688_1222}
\includegraphics{936a4675-a02d-4784-a1e2-f10dd0ecfde2-0874_67_593_732_1228}
"""
        tasks, _ = parse_ostromogilsky(tex, answers={'18.1': '6'})
        by_id = {task.external_id: task for task in tasks}
        self.assertNotIn('Аналоги', by_id['18.1'].text_latex)
        self.assertEqual(len(by_id['18.1'].images), 1)
        attach_grid_figures(tasks, {'18.1': b'\x89PNG'}, dest=None)
        self.assertIn(r'\taskpic{1}', by_id['18.1'].text_latex)
        self.assertEqual(by_id['18.1'].images, ['oge-18-1'])
        self.assertNotIn('Прототип', by_id['18.1'].text_latex)


class TariffTableLayoutTests(SimpleTestCase):
    def test_only_column_specs_change_and_second_pass_is_identical(self):
        from problems.ostromogilsky_parser import normalize_oge_tariff_tables
        table = (r'\begin{tabular}[t]{|l|l|l|}' + '\n'
                 + 'Тарифный план & Абонентская плата & Плата за трафик ' + r'\\' + '\n'
                 + '«700» & 672 руб. за 700 Мб & 0,5 руб. за 1 Мб сверх 700 Мб ' + r'\\'
                 + r'\end{tabular}')
        result = normalize_oge_tariff_tables(table)
        self.assertEqual(result.replace(r'{|p{1.7cm}|p{2.8cm}|p{3cm}|}',r'{|l|l|l|}',1),table)
        self.assertIn(r'p{2.8cm}', result)
        self.assertEqual(normalize_oge_tariff_tables(result), result)
        unknown = table.replace('Тарифный план', 'Другое условие')
        self.assertEqual(normalize_oge_tariff_tables(unknown), unknown)

    def test_two_column_tariff_keeps_spanning_cell_text(self):
        from problems.ostromogilsky_parser import normalize_oge_tariff_tables
        table = (r'\begin{tabular}{|l|l|}' + '\n'
                 + 'Стоимость перехода на тариф & 0 руб. ' + r'\\' + '\n'
                 + 'Абонентская плата в месяц & 440 руб. ' + r'\\' + '\n'
                 + r'\multicolumn{2}{|l|}{После расходования пакетов:}\\\end{tabular}')
        result = normalize_oge_tariff_tables(table)
        self.assertIn(r'\multicolumn{2}{|p{7.9cm}|}{После расходования пакетов:}', result)
        self.assertEqual(result.replace(r'{|p{4.3cm}|p{3.2cm}|}',r'{|l|l|}',1)
                         .replace(r'\multicolumn{2}{|p{7.9cm}|}',r'\multicolumn{2}{|l|}'),table)

    def test_product_and_heater_tables_keep_data_and_normalize_units(self):
        from problems.ostromogilsky_parser import normalize_oge_practical_tables, _clean_body
        products = (r'\begin{tabular}[t]{|l|l|l|l|l|}'
                    + 'Продукт & А & Б & В & Г ' + r'\\'
                    + 'Сыр (1 кг) & 270 & 260 & 310 & 220 ' + r'\\\end{tabular}')
        heaters = (r'\begin{tabular}[t]{|l|l|l|l|l|}'
                   + r'Номер печи & Тип & Объём помещения, $\mathbf{m}^{3}$ & Macca, кг & Стоимость, руб. \\'
                   + '3 & электрическая & 9-15,5 & 15 & 15000 ' + r'\\\end{tabular}')
        result = normalize_oge_practical_tables(products + heaters)
        content = result.replace(r'\hspace{0pt}', '')
        self.assertIn('Сыр (1 кг) & 270 & 260 & 310 & 220', content)
        self.assertIn('3 & электрическая & 9-15,5 & 15 & 15000', content)
        self.assertIn(r'$\text{м}^{3}$ & Масса, кг', content)
        self.assertNotIn('{|l|l|l|l|l|}', result)
        self.assertEqual(normalize_oge_practical_tables(result), result)
        self.assertEqual(_clean_body('Найдите радиус арки.\n\n№1-№5. Квартиры.'), 'Найдите радиус арки.')

    def test_web_hides_zero_indent_but_preserves_math(self):
        from problems.web_tex import tex_to_web_html
        html = tex_to_web_html(r'\begin{tabular}{p{1.4cm}}\hspace{0pt}Васильково\\\end{tabular}')
        self.assertIn('Васильково', html)
        self.assertNotIn('hspace', html)
        self.assertIn(r'\hspace{0pt}', tex_to_web_html(r'$x\hspace{0pt}+1$'))


class TexFormulaKeyTests(SimpleTestCase):
    def test_preserves_fraction_radical_and_coordinate_pairs(self):
        from problems.ostromogilsky_parser import parse_tex_formula_answers
        text = r'''№1.1 & 1234. \\
№20.10 & $\left(\frac{2}{3};0\right);(1;1)$. & & №25.9 & $10\sqrt{13},30\sqrt{5},20\sqrt{13}$. \\
'''
        result = parse_tex_formula_answers(text, {'20.10','25.9'})
        self.assertEqual(result['20.10'], r'$\displaystyle \left(\frac{2}{3};0\right);(1;1)$')
        self.assertEqual(result['25.9'], r'$10\sqrt{13},30\sqrt{5},20\sqrt{13}$')
        self.assertNotIn('1.1', result)

    def test_nested_number_cell_and_multicolumn_answer(self):
        from problems.ostromogilsky_parser import parse_tex_formula_answers
        text = r'''№1.1 & 1234. \\
\begin{tabular}{l}□\\№25.1.2\end{tabular} & \multicolumn{2}{|l|}{$\frac{16}{3}$.} \\
'''
        self.assertEqual(parse_tex_formula_answers(text, {'25.1.2'}),
                         {'25.1.2': r'$\displaystyle \frac{16}{3}$'})

    def test_does_not_replace_unconfirmed_or_broken_key(self):
        from problems.ostromogilsky_parser import parse_tex_formula_answers
        text = r'''№1.1 & 1234. \\
№20.1 & $\frac{2}{3}$. \\
№20.2 & $\frac{2}{3$. \\
№20.3 & $\frac{2}{3}\unknown{4}$. \\
№20.4 & $\frac{2}{3}$. \\
№20.4 & $\frac{5}{3}$. \\
'''
        self.assertEqual(parse_tex_formula_answers(text, {'20.2','20.3','20.4'}), {})
        self.assertEqual(parse_tex_formula_answers('№20.1 & $\\frac{2}{3}$.', {'20.1'}), {})

    def test_parser_uses_formula_without_mutating_pdf_key(self):
        answers = {'6.1': '2'}
        text = ('Задача 6.1.\nНайдите значение выражения.\n\n'
                + r'№1.1 & 1234. \\' + '\n'
                + r'№6.1 & $\frac{2}{3}$. \\')
        tasks, diagnostics = parse_ostromogilsky(text, answers=answers, expected_ids={'6.1'})
        self.assertEqual(tasks[0].author_answer_latex, r'$\displaystyle \frac{2}{3}$')
        self.assertEqual(answers, {'6.1': '2'})
        self.assertEqual(diagnostics['formula_answers_from_tex'], 1)

    def test_pdf_coordinate_fraction_uses_vertical_numerator_and_denominator(self):
        from problems.ostromogilsky_parser import _coordinate_fraction_from_words
        words = [(381,171,403,184,'(︂14'), (394,188,400,200,'9'),
                 (404,180,408,192,';'), (413,180,419,192,'0'),
                 (419,171,428,184,')︂'), (430,180,434,192,';'),
                 (439,180,453,192,'(1;'), (459,179,482,201,'−5).')]
        self.assertEqual(_coordinate_fraction_from_words(words),
                         r'$\displaystyle (\frac{14}{9};0);(1;-5)$')
        self.assertIsNone(_coordinate_fraction_from_words(words[1:]))
        self.assertIsNone(_coordinate_fraction_from_words(words + [(395,189,401,201,'8')]))
        self.assertIsNone(_coordinate_fraction_from_words([words[0],(394,170,400,182,'9')]+words[2:]))

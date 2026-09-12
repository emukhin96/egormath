"""Проверки извлечения полных ответов ЕГЭ из OCR-TeX ключа."""

from django.test import SimpleTestCase

from problems.ege_answers import extract_ege_answers


KEY_TEX = r'''
№14.1\\
а) \(\frac{\pi}{2}+\pi n\); б) \(-\frac{15 \pi}{4}\).\\
\begin{tabular}{|l|l|l|l|}
\hline
№15.1 & \(\frac{4 \sqrt{5}}{5}\). & & №15.2 & 97,5. \\
\hline
№20.1 & \multicolumn{3}{|l|}{а) Да; б) Нет; в) \(\frac{283}{17}\).} \\
\hline
\end{tabular}
'''


class ExtractEgeAnswersTests(SimpleTestCase):
    def test_prefers_complete_tex_answers_for_14_1_15_1_and_20_1(self):
        answers, diagnostics = extract_ege_answers(
            KEY_TEX,
            {
                '14.1': '$а) \\pi$',
                '15.1': '$4\\sqrt{5}$',
                '20.1': '$а) Да; б) Нет; в) 283$',
            },
            {'tasks': {'14.1': {}, '15.1': {}, '20.1': {}}},
        )

        self.assertEqual(
            answers['14.1'],
            r'а) \(\frac{\pi}{2}+\pi n\); б) \(-\frac{15 \pi}{4}\)')
        self.assertEqual(answers['15.1'], r'\(\frac{4 \sqrt{5}}{5}\)')
        self.assertEqual(
            answers['20.1'],
            r'а) Да; б) Нет; в) \(\frac{283}{17}\)')
        self.assertEqual(diagnostics['missing_ids'], [])
        self.assertEqual(diagnostics['pdf_fallback_ids'], [])
        self.assertEqual(
            diagnostics['tex_raw_by_id']['20.1'],
            [r'а) Да; б) Нет; в) \(\frac{283}{17}\)'])

    def test_conflicting_tex_cells_use_pdf_and_report_conflict(self):
        tex = r'''
\begin{tabular}{|l|l|}
№15.1 & \(\frac{1}{2}\). \\
№15.1 & \(\frac{2}{3}\). \\
\end{tabular}
'''
        answers, diagnostics = extract_ege_answers(
            tex, {'15.1': r'$\frac{7}{8}$'}, {'tasks': {'15.1': {}}})

        self.assertEqual(answers['15.1'], r'$\frac{7}{8}$')
        self.assertEqual(
            diagnostics['conflicts']['15.1'],
            [r'\(\frac{1}{2}\)', r'\(\frac{2}{3}\)'])
        self.assertEqual(diagnostics['tex_uncertain_ids'], ['15.1'])

    def test_unkeyed_answer_is_reported_as_missing_instead_of_guessed(self):
        answers, diagnostics = extract_ege_answers(
            r'а) Да; б) Нет; в) \(\frac{283}{17}\).', {},
            {'tasks': {'20.1': {}}})

        self.assertEqual(answers, {})
        self.assertEqual(diagnostics['missing_ids'], ['20.1'])

    def test_diagnostics_separate_formatting_from_lost_math(self):
        answers, diagnostics = extract_ege_answers(
            KEY_TEX,
            {'15.1': r'$\frac{4 \sqrt{5}}{5}$', '20.1': '$283$'},
            {'tasks': {'15.1': {}, '20.1': {}}},
        )

        self.assertEqual(answers['15.1'], r'\(\frac{4 \sqrt{5}}{5}\)')
        self.assertIn('15.1', diagnostics['formatting_only_ids'])
        self.assertIn('20.1', diagnostics['substantive_tex_change_ids'])

    def test_unclosed_nested_table_is_not_used_as_an_answer(self):
        answers, diagnostics = extract_ege_answers(
            r'\begin{tabular}{|l|l|} №15.1 & \multicolumn{2}{l}{\begin{tabular}{l} \(\frac{1}{2}\)} \\ \end{tabular}',
            {'15.1': '$0,5$'}, {'tasks': {'15.1': {}}})

        self.assertEqual(answers['15.1'], '$0,5$')
        self.assertEqual(diagnostics['incomplete_tex_ids'], ['15.1'])

    def test_without_index_uses_keyed_tex_cells(self):
        answers, diagnostics = extract_ege_answers(KEY_TEX, {})

        self.assertEqual(answers['15.1'], r'\(\frac{4 \sqrt{5}}{5}\)')
        self.assertIn('15.1', diagnostics['expected_ids'])

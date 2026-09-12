"""Регрессии очистки мусора и оформления чисел ЕГЭ."""
from django.test import SimpleTestCase
from .ege_cleanup import clean_ege_text, strip_ege_noise


class EgeCleanupTests(SimpleTestCase):
    def test_numbers_preserve_formulas_and_commands(self):
        text = r'В 2020 году 0,5 км и 30°. \(x=2\), $3$; \taskpic{1}, \frac{1}{2}.'
        result = clean_ege_text(text)
        self.assertIn('$2020$', result)
        self.assertIn('$0{,}5$', result)
        self.assertIn(r'$30^{\circ}$', result)
        self.assertIn(r'\(x=2\), $3$; \taskpic{1}, \frac{1}{2}', result)
        self.assertEqual(clean_ege_text(result), result)

    def test_only_noise_tables_removed(self):
        labels = r'\begin{tabular}[t]{|l|} \(C_{1}\) \\ \(D_{1}\) \\ \end{tabular}'
        data = r'\begin{tabular}{ll} Цена & 100 \\ Число & 2 \end{tabular}'
        self.assertEqual(strip_ege_noise(labels), '')
        self.assertEqual(strip_ege_noise(data), data)

    def test_navigation_and_broken_grid(self):
        text = 'Условие.\n$\\textbackslash ggg\\\\$\nОтветы\n | + — " □'
        self.assertEqual(clean_ege_text(text), 'Условие.')

    def test_approved_union_and_split_are_idempotent(self):
        from copy import deepcopy
        from .ege_cleanup import clean_ege_rows
        rows = [{'external_id': '19.26', 'text_latex': 'Условие 2.',
                 'author_answer_latex': r'$(-\infty;0)\cup\left(0;\frac{5}{3}\right]\{2\}\cup\{3\}$', 'subitems': []},
                {'external_id': '20.6', 'text_latex': 'Условие.\nа) Первый?\nб) Второй?\nв) Третий?',
                 'author_answer_latex': 'а) Да; б) Да; в) 3.', 'subitems': []}]
        self.assertTrue(clean_ege_rows(rows))
        self.assertIn(r'\right] \cup\{2\}', rows[0]['author_answer_latex'])
        self.assertEqual(len(rows[1]['subitems']), 3)
        self.assertFalse(clean_ege_rows(deepcopy(rows)))

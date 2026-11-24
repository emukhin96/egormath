"""Таблица tabular в тексте задачи: переносы строк вокруг неё не дают
пустых строк на сайте (таблица — блок со своим отступом)."""
from django.test import SimpleTestCase

from .web_tex import tex_to_web_html

TABLE = '\\begin{tabular}{|l|l|}\n\\hline\nA & 1 \\\\\n\\hline\n\\end{tabular}'


class TableBreaksTests(SimpleTestCase):
    def test_blank_lines_around_table_are_dropped(self):
        html = str(tex_to_web_html(f'В таблице.\n\n{TABLE}\n\nНайдите $x$.'))
        self.assertIn('В таблице.<table class="tex-table">', html)
        self.assertIn('</table>Найдите', html)
        self.assertNotIn('<br>', html)

    def test_explicit_break_before_table_is_dropped(self):
        html = str(tex_to_web_html(f'Таблица:\\\\\n{TABLE}'))
        self.assertTrue(html.startswith('Таблица:<table'), html)

    def test_breaks_elsewhere_are_kept(self):
        html = str(tex_to_web_html('Строка один.\nСтрока два.'))
        self.assertIn('<br>', html)


class TableUnitsTests(SimpleTestCase):
    """Число и единица в ячейке не расходятся по строкам (техдолг 17.11)."""

    def cell(self, tex):
        html = str(tex_to_web_html(
            '\\begin{tabular}{|l|}\\hline ' + tex + ' \\\\ \\hline\\end{tabular}'))
        return html.split('<td>', 1)[1].split('</td>', 1)[0]

    def test_number_and_unit_glued(self):
        self.assertEqual(self.cell('100 р.'), '100&nbsp;р.')

    def test_abbreviated_units_glued(self):
        self.assertEqual(self.cell('50 тыс. р.'), '50&nbsp;тыс.&nbsp;р.')

    def test_unit_after_formula_glued(self):
        self.assertEqual(self.cell('$5$ кг'), '$5$&nbsp;кг')

    def test_plain_words_keep_spaces(self):
        self.assertEqual(self.cell('Выигрыш билета'), 'Выигрыш билета')

    def test_formula_untouched(self):
        self.assertNotIn('~', self.cell('$2 x$'))

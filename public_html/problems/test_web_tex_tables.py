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

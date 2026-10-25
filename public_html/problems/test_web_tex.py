from django.test import SimpleTestCase

from problems.web_tex import tex_to_web_html


class WebTexFormattingTests(SimpleTestCase):
    """Начертания и списки авторских листков не видны сырым кодом."""

    def test_bold_italic_underline(self):
        html = tex_to_web_html(
            r'\textbf{Часть 2}. \textit{Найдите все варианты.} '
            r'\emph{Важно} \underline{адрес}')
        self.assertIn('<b>Часть 2</b>', html)
        self.assertIn('<i>Найдите все варианты.</i>', html)
        self.assertIn('<i>Важно</i>', html)
        self.assertIn('<u>адрес</u>', html)
        self.assertNotIn('\\text', html)

    def test_nested_and_math_inside(self):
        html = tex_to_web_html(r'\textbf{\textit{При $x>0$}} верно')
        self.assertIn('<b><i>При $x&gt;0$</i></b>', html)

    def test_command_inside_formula_untouched(self):
        html = tex_to_web_html(r'$\textbf{v}=\underline{a}$')
        self.assertIn(r'\textbf{v}', html)
        self.assertNotIn('<b>', html)

    def test_textbit_still_bold_italic(self):
        self.assertIn('<b><i>x</i></b>', tex_to_web_html(r'\textbit{x}'))

    def test_itemize_and_enumerate_as_lines(self):
        html = tex_to_web_html(
            'Случаи:\n\\begin{itemize}\n\\item $a>3$ — нет;\n'
            '\\item $a=3$ — одна.\n\\end{itemize}')
        self.assertIn('— $a&gt;3$ — нет;', html)
        self.assertIn('— $a=3$ — одна.', html)
        self.assertNotIn('item', html)
        html = tex_to_web_html(
            'Вычеркните:\\begin{enumerate}\\item одну цифру;'
            '\\item две цифры.\\end{enumerate}')
        self.assertIn('1) одну цифру;', html)
        self.assertIn('2) две цифры.', html)

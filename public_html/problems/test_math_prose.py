"""Проза в формулах: вынос наружу, показ на сайте, починка загруженных задач."""
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from .math_prose import unwrap_math_prose
from .models import Task, TaskSubitem
from .web_tex import tex_to_web_html

OCR = r'$\text { Даны точки } M(1 ; 1) \text { и } N(4 ;-1) .$'


class UnwrapMathProseTests(SimpleTestCase):
    def test_sentence_in_formula_becomes_text(self):
        self.assertEqual(unwrap_math_prose(OCR), 'Даны точки $M(1 ; 1)$ и $N(4 ;-1)$.')

    def test_plain_formulas_untouched(self):
        for value in ('Найдите $x^2$.', r'$f(x)=\begin{cases}1,&\text{если } x>0\\0\end{cases}$'):
            self.assertEqual(unwrap_math_prose(value), value)

    def test_display_kept_when_asked(self):
        value = r'Найдите \[ \frac{1}{x}, \text { при } x=2 \]'
        self.assertEqual(unwrap_math_prose(value, display=False), value)
        self.assertNotEqual(unwrap_math_prose(value), value)


class WebTexTests(SimpleTestCase):
    def test_no_leading_space_in_text_at_line_start(self):
        html = str(tex_to_web_html(OCR))
        self.assertIn(r'$\text{Даны точки }', html)
        # В середине фразы пробел внутри \text — граница слов, его не трогаем
        self.assertIn(r'$\text{ и } y$', str(tex_to_web_html(r'Найдите $x$ и $\text{ и } y$')))
        self.assertIn(r'<br>$\text{Вторая } x$', str(tex_to_web_html('Строка\\\\$\\text { Вторая } x$')))

    def test_soft_hyphen(self):
        self.assertEqual(str(tex_to_web_html(r'рас\-сто\-яние')), 'рас­сто­яние')


class UnwrapCommandTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(text_latex=OCR)
        self.sub = TaskSubitem.objects.create(task=self.task, order=10,
                                              text_latex=r'$\text { общее для } M N ;$')
        self.clean = Task.objects.create(text_latex='Найдите $x$.')

    def test_dry_run_changes_nothing(self):
        out = StringIO()
        call_command('unwrap_math_prose', stdout=out)
        self.assertIn('Задач с изменениями: 1, подпунктов: 1', out.getvalue())
        self.task.refresh_from_db()
        self.assertEqual(self.task.text_latex, OCR)

    def test_apply_saves_text_and_search_field(self):
        call_command('unwrap_math_prose', '--apply', stdout=StringIO())
        self.task.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.task.text_latex, 'Даны точки $M(1 ; 1)$ и $N(4 ;-1)$.')
        self.assertIn('Даны точки', self.task.text_plain)
        self.assertEqual(self.sub.text_latex, 'общее для $M N$;')
        self.clean.refresh_from_db()
        self.assertEqual(self.clean.text_latex, 'Найдите $x$.')

    def test_task_filter(self):
        out = StringIO()
        call_command('unwrap_math_prose', '--task', str(self.clean.pk), stdout=out)
        self.assertIn('Задач с изменениями: 0, подпунктов: 0', out.getvalue())

"""Пунктуация подпунктов в PDF листка и презентации."""
from django.test import SimpleTestCase
from django.test import TestCase

from problems.models import Task
from problems.models import TaskSubitem
from problems.tests import make_teacher

from .beamer import worksheet_to_beamer
from .latex import punctuate_subitem
from .latex import task_to_tex
from .models import Worksheet
from .tests import make_item


class PunctuateSubitemTests(SimpleTestCase):
    def test_semicolon_between_and_dot_after_last(self):
        self.assertEqual(punctuate_subitem('$1+1$', False), '$1+1$;')
        self.assertEqual(punctuate_subitem('$1+1$', True), '$1+1$.')

    def test_trailing_line_break_does_not_hide_dot(self):
        # Прод, задача 27843: «…равен \(39\)°.\\» — «;» уезжала на новую строку
        text = r'Найдите угол \(A O C\), если угол \(O C B\) равен \(39\)°.\\'
        self.assertEqual(
            punctuate_subitem(text, False),
            r'Найдите угол \(A O C\), если угол \(O C B\) равен \(39\)°.')
        for tail in (r'\\', r'\\*', r'\\[2pt]', r' \newline', r'\par', '\\\\\n'):
            self.assertEqual(punctuate_subitem('$x=1$' + tail, False), '$x=1$;')

    def test_sentence_from_capital_letter_ends_with_dot(self):
        self.assertEqual(
            punctuate_subitem(r'Найдите угол \(AOC\)', False),
            r'Найдите угол \(AOC\).')
        self.assertEqual(punctuate_subitem('найдите $x$', False), 'найдите $x$;')

    def test_punctuation_before_closing_math_or_group(self):
        for text in (r'$39^\circ.$', r'\(x=1;\)', r'\textbf{Докажите.}'):
            self.assertEqual(punctuate_subitem(text, False), text)
        self.assertEqual(
            punctuate_subitem(r'$\frac{1}{2}$', False), r'$\frac{1}{2}$;')


class SubitemPunctInDocumentsTests(TestCase):
    def setUp(self):
        self.worksheet = Worksheet.objects.create(
            title='Тест', owner=make_teacher())
        task = Task.objects.create(text_latex='')
        TaskSubitem.objects.create(
            task=task, order=10,
            text_latex=r'Найдите угол \(AOC\), если угол \(OCB\) равен \(39\)°.\\')
        TaskSubitem.objects.create(
            task=task, order=20,
            text_latex=r'Найдите угол \(OCB\), если угол \(AOC\) равен \(46\)°.')
        self.item = make_item(self.worksheet, task)

    def test_pdf(self):
        tex = task_to_tex(self.item)
        self.assertIn(r'равен \(39\)°.' + '\n\\item ', tex)
        self.assertNotIn(';', tex)

    def test_beamer(self):
        tex = worksheet_to_beamer(self.worksheet)
        self.assertIn(r'равен \(39\)°.' + '\n\\item[{б)}]', tex)
        self.assertNotIn('°.\\\\', tex)

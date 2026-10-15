"""Ответ с рисунком на сайте: рисунок выводит шаблон, разделители — лишние."""

from django.test import SimpleTestCase

from problems.templatetags.task_extras import web_answer


class WebAnswerPictureSeparatorsTests(SimpleTestCase):
    def test_leading_separator_after_picture(self):
        html = web_answer(r'\taskpic{1}; $\displaystyle \frac{1}{36}$')
        self.assertNotIn(';', html)
        self.assertIn('frac{1}{36}', html)

    def test_comma_before_words_and_trailing_comma(self):
        self.assertFalse(web_answer(r'\taskpic{2}, вероятность равна $\frac{1}{4}$').lstrip().startswith(','))
        html = web_answer('«Неисправен только второй терминал», \\taskpic{1}')
        self.assertTrue(html.rstrip().endswith('»'), html)

    def test_text_without_pictures_keeps_separators(self):
        self.assertIn(';', web_answer('а) 0,5; б) 0,25'))

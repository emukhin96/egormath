"""Сохранение знаков коэффициентов и порядка букв из PDF."""
from django.test import SimpleTestCase
from .ostromogilsky_pdf_linear_graphs import INTRO, linear_body_from_pdf


class PdfLinearGraphTests(SimpleTestCase):
    def test_letters_and_signs_remain_in_source_order(self):
        source = INTRO.replace('$', '') + '\nКОЭФФИЦИЕНТЫ\nА) k<0, b>0; Б) k>0, b<0; В) k<0, b<0.'
        result = linear_body_from_pdf('SIM\nПрототип\nОтвет\n' + source)
        self.assertIn('А) $k<0$, $b>0$', result)
        self.assertIn('Б) $k>0$, $b<0$', result)
        self.assertIn('В) $k<0$, $b<0$', result)
        self.assertEqual(result.count(r'\taskpic{1}'),1)
        self.assertIn('А & Б & В',result)

    def test_unknown_relation_missing_letter_or_changed_question_is_rejected(self):
        source = INTRO.replace('$','') + '\nКОЭФФИЦИЕНТЫ\nА) k<0, b>0; Б) k>0, b<0; В) k<0, b<0.'
        for damaged in [source.replace('В)', 'Б)'), source.replace('k<0', 'k=0'),
                        source.replace('y=kx+b','y=kx-b'), source+' Примечание']:
            with self.subTest(source=damaged):
                self.assertIsNone(linear_body_from_pdf(damaged))

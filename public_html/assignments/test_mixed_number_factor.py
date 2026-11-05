"""Смешанное число с множителем после него — сумма, а не произведение.

Потоскуев 29534: ответ книги $25\\frac{11}{13}\\pi$ при маске
{{number: \\frac{336}{13}\\pi}} засчитывался как неверный — вычислитель читал
25·11/13·π. Без множителя смешанное число уже понималось верно (#262).
"""
from django.test import SimpleTestCase

from .checks import formulas
from .checks.mask import check_slot, parse_mask


class MixedNumberFactorTests(SimpleTestCase):
    def setUp(self):
        formulas._checked.cache_clear()
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, mask):
        spec = parse_mask(mask, validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def assertVerdicts(self, mask, ok=(), wrong=()):
        slot = self.slot(mask)
        for value in ok:
            with self.subTest(mask=mask, value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in wrong:
            with self.subTest(mask=mask, value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_mixed_number_before_pi(self):
        self.assertVerdicts(
            r'{{number: \frac{336}{13}\pi}}',
            ok=[r'25\frac{11}{13}\pi', r'25 \frac{11}{13}\pi', r'25\frac{11}{13}π',
                r'\frac{336}{13}\pi'],
            wrong=[r'25\frac{11}{13}', r'\frac{275}{13}\pi'])

    def test_mixed_number_before_root_and_sign(self):
        self.assertVerdicts(r'{{number: \frac{5}{2}\sqrt{3}}}',
                            ok=[r'2\frac{1}{2}\sqrt{3}', r'2\frac12\sqrt3'],
                            wrong=[r'\sqrt{3}'])
        self.assertVerdicts(r'{{number: -\frac{7}{2}\pi}}',
                            ok=[r'-3\frac{1}{2}\pi'], wrong=[r'-\frac{3}{2}\pi'])

    def test_mixed_number_before_letter_in_expression(self):
        self.assertVerdicts(r'{{expression: \frac{7}{2}a}}',
                            ok=[r'3\frac{1}{2}a', r'3\frac12 a'],
                            wrong=[r'\frac{3}{2}a'])

    def test_fraction_with_letter_stays_product(self):
        # 2\frac{x}{3} — не смешанное число: в дроби буква.
        self.assertVerdicts(r'{{expression: \frac{2x}{3}}}',
                            ok=[r'2\frac{x}{3}'], wrong=[r'2+\frac{x}{3}'])

    def test_mixed_number_in_equation_reference(self):
        # Ткачук 16502, Шабунин 13670: эталон уравнения со смешанным числом читался
        # как произведение — маска засчитывала a=-1 вместо a=-82/9.
        self.assertVerdicts(r'{{equation: a=-9 \frac{1}{9}}}',
                            ok=[r'a=-\frac{82}{9}', r'a=-9\frac{1}{9}'], wrong=['a=-1'])
        self.assertVerdicts(r'{{equation: y=-\frac{1}{3} x-2 \frac{1}{3}}}',
                            ok=[r'y=-\frac{1}{3}x-\frac{7}{3}', 'x+3y+7=0'],
                            wrong=[r'y=-\frac{1}{3}x-\frac{2}{3}'])

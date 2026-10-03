"""Точные градусы внутри числовых аргументов тригонометрических функций."""
import sympy as sp
from django.test import SimpleTestCase
from assignments.checks import formulas
from assignments.checks.mask import parse_mask, check_slot


class DegreeArgumentsTests(SimpleTestCase):
    def slot(self, reference):
        spec = parse_mask('{{number: ' + reference + '}}')
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_explicit_and_bare_numeric_degrees(self):
        cases = ((r'\sin(30^{\circ})', sp.Rational(1, 2)),
                 (r'\sin30^\circ', sp.Rational(1, 2)),
                 (r'\cos(60°)', sp.Rational(1, 2)),
                 (r'\tan(45^{\circ})', 1),
                 (r'\cot45°', 1),
                 (r'\sin^{2}(30°)', sp.Rational(1, 4)),
                 (r'\sin(-30°)', sp.Rational(-1, 2)),
                 (r'\sin(-30°)^2', sp.Rational(1, 4)),
                 (r'\sin((90/3)°)', sp.Rational(1, 2)),
                 (r'\sin(10°+20°)', sp.Rational(1, 2)),
                 (r'\sin\left(30^{\circ}\right)2', 1),
                 (r'\sin(30,0°)', sp.Rational(1, 2)))
        for value, expected in cases:
            with self.subTest(value=value):
                parsed = formulas._parse(value, numeric=True)
                self.assertIsNotNone(parsed, value)
                self.assertEqual(sp.simplify(parsed.expression-expected), 0)

    def test_radians_and_function_boundaries_are_preserved(self):
        parsed = formulas._parse(r'\sin(30)', numeric=True)
        self.assertEqual(parsed.expression, sp.sin(30))
        for value in (r'30°', r'\sin(30)°', r'\sin(30°)+1°',
                      r'\sin(30°', r'\sin(30°))', r'\sin(30°)^\circ'):
            self.assertIsNone(formulas._parse(value, numeric=True), value)
        # Параметры angle обрабатываются прежним отдельным контекстом.
        self.assertIsNone(formulas._parse(r'\sin(30°)'))

    def test_real_worker_accepts_book_values_and_rejects_wrong_angles(self):
        slot = self.slot(r'9/\sin(70\pi/180) ~ 0.05')
        for value in (r'9/\sin(70^{\circ})', r'9/\sin70°'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        self.assertEqual(check_slot(slot, r'9/\sin(60°)'), 'wrong')
        self.assertEqual(check_slot(self.slot('1/2'), r'\sin(30°)'), 'ok')
        self.assertEqual(check_slot(self.slot('1/2'), r'\sin(60°)'), 'wrong')

    def test_original_undefined_operations_are_not_removed(self):
        slot = self.slot('1/2')
        for value in (r'\sin(30°)+0/(1-1)', r'\sin(30°)+0*sqrt(-1)',
                      r'\sin(30°)+0*(0^0)', r'1/\sin(0°)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

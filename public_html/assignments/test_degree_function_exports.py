"""Школьные тригонометрические записи и экспорт функций MathLive."""
import sympy as sp
from django.test import SimpleTestCase
from assignments.checks import formulas
from assignments.checks.mask import parse_mask, check_slot


class DegreeFunctionExportTests(SimpleTestCase):
    def slot(self, reference):
        spec = parse_mask('{{number: ' + reference + '}}')
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]


    def test_textbook_power_spacing_and_russian_trig_commands(self):
        cases = (
            (r'\cos ^{2} 45^{\circ}+\operatorname{tg}^{2} 60^{\circ}', '7/2'),
            (r'2 \cos ^{2} 60^{\circ}-\sin ^{2} 30^{\circ}'
             r'+\sin 60^{\circ} \operatorname{ctg} 60^{\circ}', '3/4'),
            (r'\cos ^{2} 30^{\circ}-\sin ^{2} 45^{\circ}', '1/4'),
            (r'3 \operatorname{tg}^{2} 30^{\circ}+4 \operatorname{tg} 45^{\circ}'
             r'+\cos 30^{\circ} \operatorname{ctg} 30^{\circ}', '13/2'),
        )
        for value, reference in cases:
            with self.subTest(value=value):
                slot = self.slot(reference)
                self.assertEqual(check_slot(slot, value), 'ok')
                self.assertEqual(check_slot(slot, value + '+1'), 'wrong')


    def test_explicit_trig_aliases_preserve_radians_and_undefined_operations(self):
        for value in (r'\tg45°', r'\ctg(45°)',
                      r'\operatorname { tg }(\pi/4)',
                      r'\operatorname{cot}(45°)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(self.slot('1'), value), 'ok')
        # Маркер градусов по-прежнему обязателен для перевода из радиан.
        self.assertEqual(check_slot(self.slot('1'), r'\operatorname{tg}(45)'), 'wrong')
        for value in (r'0*\operatorname{tg}(90°)', r'0*\ctg(0°)',
                      r'\operatorname{sin}(30°)+0/(1-1)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(self.slot('1/2'), value), 'wrong')
        self.assertEqual(check_slot(self.slot('1'), r'\operatorname{tangent}(45°)'), 'unknown')


    def test_spaced_trig_power_keeps_preceding_variable_as_a_factor(self):
        slot = parse_mask('{{expression: a^2/2 | positive:a}}').slots[0]
        self.assertEqual(check_slot(slot, r'a^{2}\cos ^{2}(45°)'), 'ok')
        self.assertEqual(check_slot(slot, r'a^{2}\cos ^{2}(60°)'), 'wrong')


    def test_sympy_inverse_operator_names_match_standard_commands(self):
        cases = (
            (r'\operatorname{atan}(1)', r'\arctan(1)', sp.pi / 4),
            (r'\operatorname { asin }(1/2)', r'\arcsin(1/2)', sp.pi / 6),
            (r'\operatorname{acos}(1/2)', r'\arccos(1/2)', sp.pi / 3),
        )
        for alias, standard, expected in cases:
            for numeric in (False, True):
                with self.subTest(alias=alias, numeric=numeric):
                    parsed = formulas._parse(alias, numeric=numeric)
                    self.assertIsNotNone(parsed)
                    self.assertEqual(sp.simplify(parsed.expression - expected), 0)
                    self.assertEqual(parsed.expression,
                                     formulas._parse(standard, numeric=numeric).expression)


    def test_sympy_inverse_operator_names_in_numeric_angle_fields(self):
        slot = self.slot('45 ~ 0.5')
        for value in (r'180*\operatorname{atan}(1)/\pi',
                      r'180*\operatorname{asin}(\sqrt{2}/2)/\pi',
                      r'180*\operatorname{acos}(\sqrt{2}/2)/\pi'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
                self.assertEqual(check_slot(slot, value + '+1'), 'wrong')
        for value in (r'0*\operatorname{asin}(2)',
                      r'0*\operatorname{acos}(2)',
                      r'\operatorname{atan}(1)+0/(1-1)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')
        self.assertEqual(check_slot(slot, r'\operatorname{atanh}(1/2)'), 'unknown')


    def test_operator_function_command_keeps_attached_symbolic_argument(self):
        cases = (
            (r'\operatorname{tg}x', r'\tan x'),
            (r'\operatorname{\mathrm{sin}}x', r'\sin x'),
            (r'\operatorname{\mathrm{ctg}}\alpha', r'\cot \alpha'),
            (r'R\operatorname{sin}x', r'R\sin x'),
            (r'\operatorname{asin}x', r'\arcsin x'),
        )
        for value, reference in cases:
            with self.subTest(value=value):
                parsed = formulas._parse(value)
                standard = formulas._parse(reference)
                self.assertIsNotNone(parsed)
                self.assertIsNotNone(standard)
                self.assertEqual(parsed.expression, standard.expression)
                spec = parse_mask('{{expression: ' + reference + '}}')
                self.assertTrue(spec.is_valid, spec.errors)
                self.assertEqual(check_slot(spec.slots[0], value), 'ok')
                self.assertEqual(check_slot(spec.slots[0], value + '+1'), 'wrong')


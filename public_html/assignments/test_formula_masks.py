"""Контекстная эквивалентность длин, площадей и наборов диагоналей."""
from unittest.mock import patch
from django.test import SimpleTestCase
from django.template.loader import render_to_string

from assignments.checks.mask import check_slot, parse_mask, render_fragments


class FormulaMaskTests(SimpleTestCase):
    def slot(self, text):
        spec = parse_mask(text)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_area_accepts_unreduced_equivalents(self):
        slot = self.slot(r'{{expression: 2R^2\sqrt{2} | positive: R}}')
        for value in (r'2\sqrt{2}R^2', r'R^2\sqrt{8}',
                      r'4R^2/\sqrt{2}', r'8(R^2\sqrt{2}/4)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in (r'2R\sqrt{2}', r'-2R^2\sqrt{2}', r'2a^2\sqrt{2}'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_hexagon_diagonals_are_an_unordered_multiset(self):
        slot = self.slot(r'{{expressions: a\sqrt{3}; 2a | positive: a}}')
        for value in (r'2a;a\sqrt{3}', r'\sqrt{3a^2};\sqrt{4a^2}',
                      r'a+a;3a/\sqrt{3}'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in ('2a;2a', '2a', r'a\sqrt{3};2a;2a', r'-2a;a\sqrt{3}'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_assumptions_do_not_leak_between_tasks(self):
        positive = self.slot('{{expression: a | positive: a}}')
        real = self.slot('{{expression: a}}')
        self.assertEqual(check_slot(positive, r'\sqrt{a^2}'), 'ok')
        self.assertEqual(check_slot(real, r'\sqrt{a^2}'), 'wrong')
        with patch('sympy.core.expr.Expr.equals', return_value=None):
            self.assertEqual(check_slot(real, r'\sqrt{a^2}'), 'wrong')

    def test_cancellation_cannot_hide_missing_parameter_values(self):
        slot = self.slot('{{expression: a | positive: a}}')
        for value in ('a(a-1)/(a-1)', r'a(a-1)^{-1}(a-1)',
                      r'a+\sqrt{a-1}^2-(a-1)',
                      r'a+\sqrt{a-1}\sqrt{a-1}-(a-1)',
                      'a+1/(a-1)-1/(a-1)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')
        self.assertEqual(check_slot(slot, 'a^2/a'), 'ok')
        real = self.slot('{{expression: a}}')
        self.assertEqual(check_slot(real, 'a^2/a'), 'wrong')

    def test_domain_of_reference_is_respected(self):
        slot = self.slot('{{expression: (a^2-1)/(a-1)}}')
        self.assertEqual(check_slot(slot, 'a+1'), 'ok')
        self.assertEqual(check_slot(slot, '(a+1)(a-2)/(a-2)'), 'wrong')

    def test_multiple_positive_parameters_and_pi(self):
        slot = self.slot(r'{{expression: a*b/2 | positive: a,b}}')
        self.assertEqual(check_slot(slot, 'b*a/2'), 'ok')
        self.assertEqual(check_slot(slot, r'\sqrt{a^2}b/2'), 'ok')
        circle = self.slot(r'{{expression: \pi R^2 | positive: R}}')
        self.assertEqual(check_slot(circle, r'R^2\pi'), 'ok')
        self.assertEqual(check_slot(circle, '3.14R^2'), 'wrong')

    def test_bad_reference_and_untrusted_input(self):
        for mask in ('{{expression: a | positive: b}}',
                     '{{expressions: a;;b}}', '{{expression: 1/0}}',
                     '{{expression: a | positive: a>0}}'):
            with self.subTest(mask=mask):
                self.assertFalse(parse_mask(mask).is_valid)
        slot = self.slot('{{expression: a}}')
        self.assertEqual(check_slot(slot, '__import__("os").getcwd()'), 'unknown')

    def test_render_does_not_expose_reference_or_assumptions(self):
        spec = parse_mask(r'Диагонали: {{expressions: a\sqrt{3};2a | positive: a}}')
        html = render_to_string('assignments/_mask.html', {
            'fragments': render_fragments(spec, 'test'), 'editable': True})
        self.assertIn('<math-field', html)
        self.assertIn('выражения в любом порядке', html)
        self.assertNotIn('positive:', html)
        self.assertNotIn(r'\sqrt{3}', html)

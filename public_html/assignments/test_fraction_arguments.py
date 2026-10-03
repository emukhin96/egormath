"""Короткий знаменатель LaTeX не должен превращаться в множитель."""
from django.test import SimpleTestCase

from assignments.checks import expressions, formulas, numeric
from assignments.checks.mask import check_slot, parse_mask


class FractionArgumentTests(SimpleTestCase):
    def setUp(self):
        formulas._worker_retry_at = 0

    def tearDown(self):
        formulas._worker_retry_at = 0

    def slot(self, payload, kind='expression'):
        spec = parse_mask('{{' + kind + ': ' + payload + '}}',
                          validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_short_denominators_and_nested_fractions_preserve_meaning(self):
        cases = ((r'\frac{x}2', 'x/2'),
                 (r'\frac{x}b', 'x/b'),
                 (r'\frac{\sqrt{3}}2', 'sqrt(3)/2'),
                 (r'\frac{\frac{x}2}3', 'x/6'),
                 (r'\frac{x}{\frac{b}2}', '2*x/b'),
                 (r'\frac{x}2b', 'x*b/2'),
                 (r'\frac{x}{2}3', '3*x/2'),
                 (r'\sqrt{\frac{x}2}3', '3*sqrt(x/2)'),
                 (r'\frac{a+1}2', '(a+1)/2'),
                 (r'\binom{n}2', r'\binom{n}{2}'),
                 (r'\binom{4}{2}3', '18'))
        for value, expected in cases:
            with self.subTest(value=value):
                parsed = expressions.parse_expr(value)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed, expressions.parse_expr(expected))
        for command in (r'\frac', r'\dfrac', r'\tfrac'):
            for spacing in ('', ' '):
                value = command + spacing + r'{x}' + spacing + '2'
                self.assertEqual(expressions.parse_expr(value),
                                 expressions.parse_expr('x/2'))

    def test_symbolic_and_simplify_answers_accept_short_denominators(self):
        slot = self.slot('x/2')
        for value in (r'\frac{x}2', r'\frac{x}2*1', r'\frac{2x}4'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        self.assertEqual(check_slot(slot, r'\frac{x}3'), 'wrong')
        self.assertEqual(check_slot(self.slot('x/2', 'simplify'),
                                    r'\frac{x}2'), 'ok')

    def test_numeric_short_denominators_and_following_multipliers(self):
        cases = (('sqrt(3)/2', r'\frac{\sqrt{3}}2'),
                 ('1/2', r'\frac{1}2'),
                 ('3/2', r'\frac{1}{2}3'),
                 ('sqrt(3)', r'\frac{\sqrt{3}}2*2'),
                 ('6', r'\binom{4}2'),
                 ('18', r'\binom{4}{2}3'))
        for reference, value in cases:
            with self.subTest(value=value):
                slot = self.slot(reference, 'number')
                self.assertEqual(check_slot(slot, value), 'ok')
                self.assertEqual(check_slot(slot, value+'+1'), 'wrong')
        self.assertEqual(numeric.prepare(r'\frac{\sqrt{3}}2'),
                         r'\frac{\sqrt{3}}2')

    def test_short_fraction_keeps_original_undefined_operations(self):
        slot = self.slot('x/2 | positive: x')
        for value in (r'\frac{x}2+0/(x-1)', r'\frac{x}0',
                      r'\frac{x}{\frac{0}2}',
                      r'\frac{x}2+0*sqrt(-1)', r'\frac{x}2+0*(0^0)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)
        number = self.slot('1/2', 'number')
        self.assertEqual(check_slot(number, r'\frac{1}2+0/(1-1)'), 'wrong')

    def test_ratios_and_collections_accept_short_fraction_values(self):
        ratio = self.slot('1:2', 'ratio')
        self.assertEqual(check_slot(ratio, r'\frac{\sqrt{3}}2:\sqrt{3}'), 'ok')
        self.assertEqual(check_slot(ratio, r'\sqrt{3}:\frac{\sqrt{3}}2'), 'wrong')
        values = self.slot('x/2;x/3', 'expressions')
        self.assertEqual(check_slot(values, r'\frac{x}3;\frac{x}2'), 'ok')
        self.assertEqual(check_slot(values, r'\frac{x}3;\frac{x}4'), 'wrong')
        self.assertEqual(check_slot(values, r'\frac{x}3;\frac{x}2;\frac{x}2'),
                         'wrong')

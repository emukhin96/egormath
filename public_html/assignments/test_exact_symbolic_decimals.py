"""Точная десятичная арифметика и исходные области символьных ответов."""
from django.test import SimpleTestCase
from .checks import expressions, formulas
from .checks.mask import parse_mask, check_slot


class ExactSymbolicDecimalTests(SimpleTestCase):
    def setUp(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def tearDown(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, payload='a | positive: a', kind='expression'):
        spec = parse_mask('{{'+kind+': '+payload+'}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_equivalent_decimal_arithmetic_is_exact(self):
        slot = self.slot()
        for value in ('a*((0.1+0.2)/0.3)', 'a*(0.7-0.6)/0.1',
                      'a+(0.1+0.2-0.3)', 'a*(0.1*0.1)/0.01',
                      'a*((0.1+0.2)^2)/0.09'):
            self.assertEqual(check_slot(slot, value), 'ok', value)

    def test_arbitrarily_close_wrong_values_remain_wrong(self):
        slot = self.slot()
        for value in ('a+0.00000000000000000001',
                      'a*(0.1+0.2)/0.30000000000000001',
                      'a*(0.70000000000000001-0.6)/0.1'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_decimal_zero_keeps_division_and_power_restrictions(self):
        slot = self.slot()
        for value in ('a+0/(0.1+0.2-0.3)', 'a+0*(0.1+0.2-0.3)^0',
                      'a+(0.1+0.2-0.3)/(0.1+0.2-0.3)',
                      'a+0*sqrt(0.1+0.2-0.4)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_triangle_domain_and_hidden_holes_are_preserved(self):
        slot = self.slot('ab/(a+b) | positive: a,b | domain: a<2b')
        valid = 'ab/(a+b)*((0.1+0.2)/0.3)'
        self.assertEqual(check_slot(slot, valid), 'ok')
        self.assertEqual(check_slot(slot, valid+'+0/(2b-a)'), 'ok')
        for value in (valid+'+0/(a-b)', valid+'+0sqrt(a-2b)', valid+'+0z'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_expression_lists_preserve_count_and_order_independence(self):
        slot = self.slot('a; b | positive: a,b', 'expressions')
        self.assertEqual(check_slot(slot, 'b*((0.1+0.2)/0.3);a'), 'ok')
        self.assertEqual(check_slot(slot, 'a*((0.1+0.2)/0.3);a'), 'wrong')
        self.assertEqual(check_slot(slot, 'b+0.00000000000000000001;a'), 'wrong')

    def test_required_simplified_and_factored_forms_stay_required(self):
        strict = self.slot('a', 'simplify')
        self.assertEqual(check_slot(strict, 'a'), 'ok')
        self.assertEqual(check_slot(strict, 'a*((0.1+0.2)/0.3)'), 'wrong')
        product = self.slot('(a+b)(a-b)', 'factor')
        self.assertEqual(check_slot(product, '(a-b)(a+b)'), 'ok')
        self.assertEqual(check_slot(product, 'a^2-b^2'), 'wrong')

    def test_exact_transformer_does_not_change_shared_sympy_parser(self):
        from sympy import Rational, Float
        parser, transformer = expressions._lark()
        shared = parser.transformer
        tree = expressions.resolve(expressions.raw_tree('0.1'))
        self.assertIsNot(transformer, shared)
        self.assertEqual(expressions.evaluate(tree), Rational(1, 10))
        self.assertEqual(expressions.evaluate(tree, numeric=True), Rational(1, 10))
        self.assertIsInstance(shared.transform(tree), Float)
        self.assertIs(parser.transformer, shared)

    def test_decimal_references_and_numeric_masks_keep_exact_values(self):
        slot = self.slot('0.3a | positive: a')
        self.assertEqual(check_slot(slot, '(0.1+0.2)*a'), 'ok')
        self.assertEqual(check_slot(slot, '0.30000000000000001a'), 'wrong')
        number = self.slot('0.3', 'number')
        self.assertEqual(check_slot(number, '0.1+0.2'), 'ok')
        self.assertEqual(check_slot(number, '0.30000000000000001'), 'wrong')


    def test_proven_wrong_trig_values_are_rejected_before_uncertain_domain(self):
        slot = self.slot(r'h/\cos(\beta/2) | positive: h,\beta')
        correct = r'h/\cos(\beta/2)'
        self.assertEqual(check_slot(slot, correct+'*((0.1+0.2)/0.3)'), 'ok')
        for value in (correct+'+0.00000000000000000001',
                      correct+'*((0.1+0.2)/0.30000000000000001)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)
        # Равенство не отменяет исходных разрывов и невещественных частей.
        for value in (correct+'+0/(h-1)', correct+'+0sqrt(-1)',
                      correct+'+0*(0.1+0.2-0.3)^0'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

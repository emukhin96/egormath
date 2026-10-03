"""Числовое значение отношения допустимо только при явной опции маски."""
from django.test import SimpleTestCase

from .checks.mask import check_slot, parse_mask
from .checks import formulas


class RatioQuotientTests(SimpleTestCase):
    def setUp(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def tearDown(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, reference='6:7', kind='ratio'):
        spec = parse_mask('{{' + kind + ': ' + reference + ' | quotient}}',
                          validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_geometry_21_21_accepts_fraction_and_colon_in_order(self):
        slot = self.slot()
        for value in ('6:7', '12:14', '6/7', r'\frac67',
                      r'\frac{12}{14}', '(3+3)/7', '-6:-7',
                      r'6\sqrt2:7\sqrt2'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in ('7:6', '7/6', '6/7+1', '6:0', '6/0', '6:7:1',
                      'x/x', '0.8571428571428571'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')
        self.assertEqual(check_slot(slot, ''), '')

    def test_exact_irrational_quotient_does_not_accept_approximation(self):
        slot = self.slot(r'\sqrt2:1')
        for value in (r'\sqrt2', 'sqrt(2)', r'\sqrt8/2', r'2/\sqrt2'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in ('1.4142135623730951', r'\sqrt2+10^{-10}', r'1/\sqrt2'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_undefined_subexpressions_cannot_disappear(self):
        slot = self.slot('0:1')
        self.assertEqual(check_slot(slot, '0'), 'ok')
        for value in ('0/0', '0*(1/0)', '0*sqrt(-1)', '0^0',
                      '2^{1000000000}', '9'*10000):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_option_does_not_change_strict_ratio_or_proportion(self):
        for mask in ('{{ratio: 1:2}}', '{{proportion: 1:2}}'):
            slot = parse_mask(mask).slots[0]
            for value in ('1/2', '0,5'):
                self.assertEqual(check_slot(slot, value), 'wrong')
        self.assertEqual(check_slot(self.slot('1:2'), '0,5'), 'ok')
        for mask in ('{{ratio: 6/7 | quotient}}',
                     '{{ratio: 6:7 | unknown}}',
                     '{{ratio: 6:7 | quotient | quotient}}',
                     '{{proportion: 6/7 | quotient}}',
                     '{{proportion: 6:7 | quotient | quotient}}'):
            self.assertFalse(parse_mask(mask).is_valid, mask)

    def test_unordered_area_ratio_accepts_values_in_either_direction(self):
        slot = self.slot('2:3', kind='proportion')
        self.assertEqual(slot.reference, '2:3')
        self.assertEqual(slot.label, 'отношение в любом порядке или его значение')
        for value in ('2:3', '3:2', '4:6', '6:4', '2/3', '3/2',
                      r'\frac{4}{6}', '-2/-3', '2sqrt(2):3sqrt(2)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in ('2:2', '0:3', '2:0', '-2:3', '2:3:4',
                      '0.6666666666666666', '2/3+1/1000000000000'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')
        self.assertEqual(check_slot(slot, ''), '')

    def test_unordered_irrational_value_requires_exact_equality(self):
        slot = self.slot(r'\sqrt2:1', kind='proportion')
        for value in (r'\sqrt2', r'1/\sqrt2', r'\sqrt8/2',
                      r'\sqrt2:1', r'1:\sqrt2'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in ('1.4142135623730951', '0.7071067811865476',
                      r'\sqrt2+10^{-10}'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_unordered_value_does_not_hide_undefined_subexpressions(self):
        slot = self.slot('0:1', kind='proportion')
        self.assertEqual(check_slot(slot, '0'), 'ok')
        for value in ('1:0', '0/0', '0*(1/0)', '0*sqrt(-1)', '0^0'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_unordered_value_worker_failure_remains_retryable(self):
        from unittest.mock import patch
        slot = self.slot(r'\sqrt2:1', kind='proportion')
        formulas._checked.cache_clear()
        with patch.object(formulas, '_spawn',
                          side_effect=formulas.FormulaUnavailable('занято')):
            with self.assertRaises(formulas.FormulaUnavailable):
                check_slot(slot, r'1/\sqrt2')

    def test_worker_unavailability_remains_retryable(self):
        from unittest.mock import patch
        slot = self.slot(r'\sqrt2:1')
        # Предыдущие проверки могли закэшировать тот же допустимый ввод.
        formulas._checked.cache_clear()
        with patch.object(formulas, '_spawn',
                          side_effect=formulas.FormulaUnavailable('занято')):
            with self.assertRaises(formulas.FormulaUnavailable):
                check_slot(slot, r'\sqrt2')

    def test_absolute_value_bars_are_not_option_delimiters(self):
        for reference in ('|6|:7', r'\left|-6\right|:7'):
            with self.subTest(reference=reference):
                strict = parse_mask('{{ratio: ' + reference + '}}')
                self.assertTrue(strict.is_valid, strict.errors)
                self.assertEqual(check_slot(strict.slots[0], '6:7'), 'ok')
                self.assertEqual(check_slot(self.slot(reference), '6/7'), 'ok')

    def test_root_coefficients_preserve_multiplication_and_division_order(self):
        slot = self.slot()
        for value in ('6sqrt(2)/(7sqrt(2))',
                      '-6sqrt(2)/(-7sqrt(2))',
                      '0.6sqrt(2)/(0.7sqrt(2))',
                      '6sqrt2:7sqrt2',
                      r'\frac{6}{7}\sqrt2/\sqrt2'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        # Без скобок после / последнее умножение относится ко всему частному.
        value = '6sqrt(2)/7sqrt(2)'
        self.assertEqual(check_slot(slot, value), 'wrong')
        self.assertEqual(check_slot(self.slot('12:7'), value), 'ok')
        # Текстовая многозначная запись не угадывается как корень или произведение.
        for value in ('sqrt16', 'sqrt2.25'):
            self.assertEqual(check_slot(slot, value), 'wrong')

    def test_numeric_power_group_is_a_coefficient_not_a_function_script(self):
        slot = self.slot(r'\sqrt2:1')
        for value in (r'2^{1}\sqrt2/2', r'2^{-1}\sqrt2*2',
                      r'\frac{2^{1}}{2}\sqrt2'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in (r'0^{0}\sqrt2', r'2^{-1}\sqrt2/(1-1)',
                      r'2^{1}\sqrt2+0*sqrt(-1)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')
        spec = parse_mask(r'{{expression: \sin^{2}(\sqrt2)}}',
                          validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual(check_slot(spec.slots[0], r'\sin^{2}\sqrt2'), 'ok')

    def test_bare_function_scripts_keep_the_following_root_as_argument(self):
        from .checks import expressions
        for value in (r'\log_2\sqrt{8}', r'\sin^2\sqrt{x}',
                      r'\cos^2 \sqrt{x}', r'\sin^2(\sqrt{x})',
                      r'\sin^ 2\sqrt{x}', r'\log_ 2\sqrt8'):
            with self.subTest(value=value):
                self.assertNotIn(r'\cdot', expressions.prepare(value))
        for payload, value in ((r'3/2', r'\log_2\sqrt{8}'),
                               (r'\sin^{2}(\sqrt{x}) | positive: x', r'\sin^2\sqrt{x}'),
                               (r'\cos^{2}(\sqrt{x}) | positive: x', r'\cos^2\sqrt{x}'),
                               (r'3/2', r'\log_ 2\sqrt8'),
                               (r'\sin^{2}(\sqrt{x}) | positive: x', r'\sin^2(\sqrt{x})'),
                               (r'\cos^{2}(\sqrt{x}) | positive: x', r'\cos^ 2\sqrt{x}')):
            spec = parse_mask('{{expression: '+payload+'}}', validate_references=True)
            self.assertTrue(spec.is_valid, spec.errors)
            self.assertEqual(check_slot(spec.slots[0], value), 'ok')
        spec = parse_mask(r'{{equation: y=3/2}}')
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual(check_slot(spec.slots[0], r'y=\log_2\sqrt{8}'), 'ok')

    def test_numeric_bare_power_still_multiplies_the_root(self):
        slot = self.slot(r'4\sqrt2:1')
        self.assertEqual(check_slot(slot, r'2^2\sqrt2'), 'ok')
        self.assertEqual(check_slot(slot, r'2^{2}\sqrt2'), 'ok')
        for value in (r'(2^2)\sqrt2', r'(2^{2})\sqrt2', r'(4)\sqrt2'):
            self.assertEqual(check_slot(slot, value), 'ok')
        spec = parse_mask(r'{{expression: \sin^{2}(\sqrt{x})*\sqrt{x} | positive: x}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual(check_slot(spec.slots[0], r'\sin^2(\sqrt{x})\sqrt{x}'), 'ok')
        self.assertEqual(check_slot(spec.slots[0], r'\sin^2(\sqrt{x}*\sqrt{x})'), 'wrong')

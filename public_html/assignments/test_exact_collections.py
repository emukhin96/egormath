"""Числовые множества и варианты сторон не используют неявное округление."""
from unittest.mock import patch

from django.test import SimpleTestCase

from .checks import formulas
from .checks.mask import check_mask, check_slot, parse_mask, render_fragments


class ExactCollectionTests(SimpleTestCase):
    def setUp(self):
        formulas._checked.cache_clear()
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, mask):
        spec = parse_mask(mask, validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_exact_side_lengths_reject_close_radicals(self):
        slot = self.slot('{{set: 8;40}}')
        for value in ('40;sqrt(64)', '8;40;8', '{40,8}'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in ('sqrt(64+10^{-10});40', '8;40;41', '8'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_side_variants_keep_both_orders_and_grouping(self):
        slot = self.slot('{{pair: (8;12);(5;15) | unordered}}')
        self.assertEqual(check_slot(slot, '(15;5);(12;sqrt(64))'), 'ok')
        self.assertEqual(check_slot(slot, '(8;15);(5;12)'), 'wrong')
        self.assertEqual(check_slot(slot, '(sqrt(64+10^{-10});12);(5;15)'), 'wrong')
        ordered = self.slot('{{pair: (8;12)}}')
        self.assertEqual(check_slot(ordered, '(12;sqrt(64))'), 'wrong')

    def test_irrational_elements_require_exact_values(self):
        slot = self.slot(r'{{set: \sqrt2;2}}')
        self.assertEqual(check_slot(slot, r'2;\sqrt8/2'), 'ok')
        self.assertEqual(check_slot(slot, '1.4142135623730951;2'), 'wrong')
        self.assertEqual(check_slot(slot, r'\sqrt2+10^{-10};2'), 'wrong')

    def test_distinct_close_elements_do_not_merge(self):
        slot = self.slot(r'{{set: \sqrt2;\sqrt2+10^{-10}}}')
        self.assertEqual(check_slot(slot, r'\sqrt2+10^{-10};\sqrt2'), 'ok')
        self.assertEqual(check_slot(slot, r'\sqrt2'), 'wrong')
        self.assertEqual(check_slot(slot, r'\sqrt2;\sqrt2+2*10^{-10}'), 'wrong')

    def test_decimal_arithmetic_pm_and_cartesian_products(self):
        self.assertEqual(check_slot(self.slot('{{set: 0.3;2}}'), '0.1+0.2;2'), 'ok')
        self.assertEqual(check_slot(self.slot('{{set: 0.3;2}}'),
                                   '0.1+0.200000000000000001;2'), 'wrong')
        self.assertEqual(check_slot(self.slot('{{set: -2;2}}'),
                                   r'±\sqrt[3]{8}'), 'ok')
        slot = self.slot('{{pair: (1;-1);(1;2);(5;-1);(5;2)}}')
        self.assertEqual(check_slot(slot, r'\{sqrt(1);5\}\times\{-1;2\}'), 'ok')

    def test_undefined_operations_cannot_cancel(self):
        slot = self.slot('{{set: 8;40}}')
        for value in ('8+0sqrt(-1);40', '8*0^0;40', '8+0/0;40', '8+0x;40'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)
        pair = self.slot('{{pair: (8;12)}}')
        self.assertEqual(check_slot(pair, '(8+0/0;12)'), 'wrong')

    def test_worker_failures_remain_retryable(self):
        slot = self.slot('{{set: 8;40}}')
        with patch.object(formulas, '_spawn', side_effect=formulas.FormulaUnavailable('занято')):
            with self.assertRaises(formulas.FormulaUnavailable):
                check_slot(slot, 'sqrt(64);40')

    def test_one_failed_process_keeps_literal_empty_and_known_fields(self):
        spec = parse_mask('{{set: 8;40}}; {{pair: (8;12)}}; {{set: 8;40}}; '
                          '{{pair: (8;12)}}; {{set: 8;40}}; {{set: 8;40}}; '
                          '{{pair: (8;12)}}; {{number: 54}}')
        values = {'s1': 'sqrt(64);40', 's2': '(sqrt(64);12)', 's3': '40;8',
                  's4': '(8;13)', 's5': '', 's6': '9'*10000,
                  's7': '(sqrt(64);12)', 's8': '+54'}
        with patch.object(formulas, '_spawn', side_effect=formulas.FormulaUnavailable('занято')) as spawn:
            with self.assertRaises(formulas.FormulaUnavailable) as caught:
                check_mask(spec, values, known={'s7': 'ok'})
        spawn.assert_called_once()
        self.assertEqual(caught.exception.slot_checks, {
            's1': 'unknown', 's2': 'unknown', 's3': 'ok', 's4': 'wrong',
            's5': '', 's6': 'unknown', 's7': 'ok', 's8': 'ok'})

    def test_proportions_reject_close_values_and_keep_both_orders(self):
        for a, b in ((2, 1), (2, 3), (59, 53)):
            slot = self.slot('{{proportion: %s:%s}}' % (a, b))
            for value in ('%s:%s' % (a, b), '%s:%s' % (b, a),
                          '%s:%s' % (2*a, 2*b), '-%s:-%s' % (a, b),
                          'sqrt(%s):%s' % (a*a, b)):
                self.assertEqual(check_slot(slot, value), 'ok', value)
            for value in ('sqrt(%s+10^{-10}):%s' % (a*a, b),
                          '%s*0^0:%s' % (a, b), '%s:0' % a):
                self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_numeric_ratio_fallback_keeps_real_roots_and_exact_decimals(self):
        for kind in ('ratio', 'proportion'):
            slot = self.slot('{{' + kind + r': -\sqrt[3]{\pi}:1}}')
            self.assertEqual(check_slot(slot, r'\sqrt[3]{-\pi}:1'), 'ok')
            self.assertEqual(check_slot(slot, r'(-\pi)^{1/3}:1'), 'ok')
            self.assertEqual(check_slot(slot, r'-\sqrt[3]{3.141592653589793}:1'), 'wrong')
            decimal = self.slot('{{' + kind + ': 0.3:1}}')
            self.assertEqual(check_slot(decimal, '0.1+0.2:1'), 'ok')
            self.assertEqual(check_slot(decimal, '0.300000000000000001:1'), 'wrong')

    def test_literals_render_and_input_limits_do_not_start_worker(self):
        with patch.object(formulas, '_spawn') as spawn:
            spec = parse_mask('{{set: 8;40}}', validate_references=False)
            render_fragments(spec, 'task1')
            self.assertEqual(check_slot(spec.slots[0], '40;8'), 'ok')
            self.assertEqual(check_slot(spec.slots[0], '9'*10000), 'unknown')
            spawn.assert_not_called()
        self.assertEqual(check_slot(self.slot('{{pair: (8;12)}}'), '(8;12]'), 'unknown')

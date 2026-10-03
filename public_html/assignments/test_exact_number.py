"""Числовая маска без допуска проверяет точное вещественное значение."""
from unittest.mock import patch

from django.test import SimpleTestCase

from .checks import formulas
from .checks.mask import check_slot, parse_mask, render_fragments


class ExactNumberTests(SimpleTestCase):
    def setUp(self):
        formulas._checked.cache_clear()
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, reference):
        spec = parse_mask('{{number: ' + reference + '}}',
                          validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_exact_geometry_lengths_reject_rounded_answers(self):
        for reference, exact, rounded in (
                (r'\sqrt{2}', r'2/\sqrt2', '1.4142135623730951'),
                (r'2\sqrt{13}', 'sqrt(52)', '7.211102550927979'),
                (r'600\sqrt{3}', r'300\sqrt{12}', '1039.2304845413264')):
            with self.subTest(reference=reference):
                slot = self.slot(reference)
                self.assertEqual(check_slot(slot, exact), 'ok')
                self.assertEqual(check_slot(slot, rounded), 'wrong')
                self.assertEqual(check_slot(slot, exact + '+10^{-10}'), 'wrong')

    def test_decimal_arithmetic_and_close_radicals_remain_exact(self):
        self.assertEqual(check_slot(self.slot('0.3'), '0.1+0.2'), 'ok')
        self.assertEqual(check_slot(self.slot('0.3'), '0.1+0.200000000000000001'), 'wrong')
        slot = self.slot(r'\sqrt2')
        self.assertEqual(check_slot(slot, 'sqrt(2.0000000000000000000001)'), 'wrong')
        self.assertEqual(check_slot(slot, r'\sqrt{0.5}*2'), 'ok')

    def test_real_odd_roots_and_fractional_powers(self):
        for reference, value in (
                ('-2', r'\sqrt[3]{-8}'), ('-2', '(-8)^{1/3}'),
                ('4', '(-8)^{2/3}'), ('-0.5', '(-8)^{-1/3}'),
                ('0', r'\sin(\sqrt[3]{-8})-\sin(-2)')):
            with self.subTest(value=value):
                self.assertEqual(check_slot(self.slot(reference), value), 'ok')

    def test_undefined_operations_and_variables_cannot_cancel(self):
        for reference, value in (
                ('1', '1+0sqrt(-1)'), ('1', '1+sqrt(-1)-sqrt(-1)'),
                ('5', '5*0^0'), ('0', '0/0'), ('0', '0*(1/0)'),
                ('-2', r'\sqrt[3]{-8}+0/0'), ('1', 'x/x'),
                ('1', '1+0x'), ('1', '1;0')):
            with self.subTest(value=value):
                self.assertEqual(check_slot(self.slot(reference), value), 'wrong')

    def test_literals_and_pi_keep_accepted_school_notation(self):
        for reference, values in (
                ('54', ('+54', 'x=54', '54.000')),
                ('-0.5', ('1/-2', r'\frac{-1}{2}', '-0,5')),
                (r'\pi/2', ('pi/2', r'\pi/2', 'π/2'))):
            slot = self.slot(reference)
            for value in values:
                with self.subTest(value=value):
                    self.assertEqual(check_slot(slot, value), 'ok')

    def test_explicit_tolerance_keeps_approximate_check(self):
        slot = self.slot(r'\sqrt2 ~ 0.001')
        self.assertEqual(check_slot(slot, '1.414'), 'ok')
        self.assertEqual(check_slot(slot, '1.42'), 'wrong')
        self.assertEqual(check_slot(self.slot(r'\sqrt2'), '1.414'), 'wrong')
        self.assertEqual(check_slot(self.slot(r'\sqrt2 ~ 0'),
                                   '1.4142135623730951'), 'wrong')
        self.assertEqual(check_slot(self.slot(r'\sqrt2 ~ 0'), 'sqrt(2)'), 'ok')

    def test_worker_failures_remain_retryable(self):
        slot = self.slot(r'\sqrt2')
        with patch.object(formulas, '_spawn', side_effect=formulas.FormulaUnavailable('занято')):
            with self.assertRaises(formulas.FormulaUnavailable):
                check_slot(slot, 'sqrt(2)')

    def test_render_and_simple_literals_do_not_start_worker(self):
        with patch.object(formulas, '_spawn') as spawn:
            spec = parse_mask(r'Длина {{number: \sqrt2}} см.', validate_references=False)
            self.assertTrue(spec.is_valid, spec.errors)
            render_fragments(spec, 'task1')
            self.assertEqual(check_slot(self.slot('54'), '+54'), 'ok')
            self.assertEqual(check_slot(self.slot('54'), '9' * 10000), 'unknown')
            spawn.assert_not_called()

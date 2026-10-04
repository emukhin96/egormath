"""Допуск сохраняет точную границу и допустимость каждого действия."""
from unittest.mock import patch

from django.test import SimpleTestCase

from .checks import formulas
from .checks.mask import check_mask, check_slot, parse_mask, render_fragments


class ExactToleranceTests(SimpleTestCase):
    def setUp(self):
        formulas._checked.cache_clear()
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, mask):
        spec = parse_mask(mask, validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_included_irrational_boundary_and_nearby_outside_values(self):
        slot = self.slot(r'{{number: \sqrt2 ~ 0.001}}')
        for value in (r'\sqrt2+0.001', r'\sqrt2-0.001', '1.414'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'\sqrt2+0.001+10^{-30}', r'\sqrt2-0.001-10^{-30}'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_trigonometric_boundaries_from_tree_height_task(self):
        reference = r'8/5+8\tan(52\pi/180)'
        slot = self.slot('{{number: '+reference+' ~ 0.05}}')
        for sign in ('+', '-'):
            self.assertEqual(check_slot(slot, '('+reference+')'+sign+'0.05'), 'ok')
            self.assertEqual(check_slot(slot, '('+reference+')'+sign+'(0.05+10^{-30})'), 'wrong')

    def test_zero_powers_holes_nonreal_and_variables_cannot_cancel(self):
        slot = self.slot('{{number: 7 ~ 0.1}}')
        for value in ('7+0*0^0', '7+0/0', '7+0sqrt(-1)', '7+x-x'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)
        self.assertEqual(check_slot(slot, 'не знаю'), 'unknown')

    def test_exact_decimal_arithmetic_and_real_pi_roots(self):
        slot = self.slot('{{number: 0.3 ~ 0.05}}')
        self.assertEqual(check_slot(slot, '0.1+0.2+0.05'), 'ok')
        self.assertEqual(check_slot(slot, '0.1+0.2+0.050000000000000001'), 'wrong')
        pi_slot = self.slot(r'{{number: -\sqrt[3]{\pi} ~ 0.01}}')
        self.assertEqual(check_slot(pi_slot, r'\sqrt[3]{-\pi}+0.01'), 'ok')

    def test_irrational_tolerance_is_not_rounded_to_float(self):
        slot = self.slot(r'{{number: 0 ~ \sqrt2/1000}}')
        self.assertEqual(check_slot(slot, r'\sqrt2/1000'), 'ok')
        self.assertEqual(check_slot(slot, r'-\sqrt2/1000'), 'ok')
        self.assertEqual(check_slot(slot, r'\sqrt2/1000+10^{-30}'), 'wrong')

    def test_literals_limits_and_rendering_do_not_spawn(self):
        slot = self.slot('{{number: 7 ~ 0.1}}')
        with patch.object(formulas, '_spawn') as spawn:
            render_fragments(parse_mask('{{number: 7 ~ 0.1}}'), 'task1')
            self.assertEqual(check_slot(slot, '7.1'), 'ok')
            self.assertEqual(check_slot(slot, '7.100000000000000001'), 'wrong')
            self.assertEqual(check_slot(slot, '9'*10000), 'unknown')
        spawn.assert_not_called()

    def test_one_failed_worker_preserves_simple_and_empty_fields(self):
        spec = parse_mask(r'{{number: \sqrt2 ~ 0.1}}; {{number: \sqrt3 ~ 0.1}}; '
                          '{{number: 7 ~ 0.1}}; {{number: 7 ~ 0.1}}; {{number: 7 ~ 0.1}}')
        values = {'s1': r'\sqrt2+0.01', 's2': r'\sqrt3+0.01',
                  's3': '7.1', 's4': '7.2', 's5': ''}
        with patch.object(formulas, '_spawn', side_effect=formulas.FormulaUnavailable('занято')) as spawn:
            with self.assertRaises(formulas.FormulaUnavailable) as caught:
                check_mask(spec, values)
        spawn.assert_called_once()
        self.assertEqual(caught.exception.slot_checks,
                         {'s1': 'unknown', 's2': 'unknown', 's3': 'ok', 's4': 'wrong', 's5': ''})

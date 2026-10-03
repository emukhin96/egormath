"""Большие показатели отклоняются до real_root и материализации Integer."""
from unittest.mock import patch
import sympy as sp
from django.test import SimpleTestCase
from assignments.checks import expressions, sets
from assignments.checks.mask import parse_mask
from assignments.check_answer import _sympy_expr


class OddPowerBudgetTests(SimpleTestCase):
    def test_huge_rational_powers_never_reach_root_evaluation(self):
        values = (r'2^{1000000000.2}', r'10^{100000000000.2}',
                  r'2^{-1000000000.2}', r'2^{1/1001}')
        with patch('sympy.real_root', side_effect=AssertionError('корень не должен вычисляться')) as root:
            for value in values:
                self.assertIsNone(expressions.parse_expr(value), value)
            root.assert_not_called()

    def test_nested_integer_powers_cannot_hide_large_root_base(self):
        values = (r'(2^{1000000000})^{1/3}',
                  r'((2^{1000})^{1000})^{1/3}',
                  r'\sqrt[3]{(2^{1000})^{1000}}')
        with patch('sympy.real_root', side_effect=AssertionError('основание не ограничено')) as root:
            for value in values:
                self.assertIsNone(expressions.parse_expr(value), value)
            root.assert_not_called()

    def test_web_process_entry_points_reject_before_evaluation(self):
        value = r'2^{1000000000.2}'
        with patch('sympy.real_root', side_effect=AssertionError('нет ограниченного worker')) as root:
            self.assertIsNone(sets.numeric_value(value))
            self.assertIsNone(sets.parse_range('x>' + value))
            self.assertIsNone(_sympy_expr(value))
            self.assertFalse(parse_mask('{{equation: x=' + value + '}}').is_valid)
            self.assertFalse(parse_mask('{{number: 1 ~ ' + value + '}}').is_valid)
            root.assert_not_called()

    def test_school_odd_powers_keep_real_value_and_lazy_outer_power(self):
        for value, expected in ((r'(-27)^{2/3}', 9), (r'(-32)^{2/5}', 4),
                                (r'(-8)^{-1/3}', sp.Rational(-1, 2)),
                                (r'2^{1.2}', 2**sp.Rational(6, 5))):
            result = expressions.parse_expr(value)
            self.assertIsNotNone(result, value)
            self.assertEqual(sp.simplify(result-expected), 0, value)
        result = expressions.parse_expr(r'2^{3/5}')
        self.assertTrue(result.is_Pow)
        self.assertEqual(result.exp, 3)

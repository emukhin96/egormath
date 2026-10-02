"""Допустимые записи корней из реальных задач должны одинаково проверяться."""
from django.test import SimpleTestCase

from assignments.checks import formulas
from assignments.checks.mask import check_slot, parse_mask


class RadicalNotationTests(SimpleTestCase):
    def setUp(self):
        formulas._worker_retry_at = 0

    def tearDown(self):
        formulas._worker_retry_at = 0

    def slot(self, text):
        spec = parse_mask(text, validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_numeric_areas_accept_ascii_roots(self):
        for reference, value in (('156', 'sqrt(24336)'), ('1/4', 'sqrt(1/16)'),
                                 ('2', 'sqrt(sqrt(16))'), (r'8\sqrt{10}', '8sqrt(10)')):
            with self.subTest(value=value):
                slot = self.slot('{{number: ' + reference + '}}')
                self.assertEqual(check_slot(slot, value), 'ok')
                self.assertEqual(check_slot(slot, value + '+1'), 'wrong')

    def test_symbolic_areas_accept_mathlive_short_roots(self):
        for reference, value in ((r'3a^2\sqrt{3}/4 | positive: a', r'3a^2\sqrt3/4'),
                                 (r'h^2\sqrt{3} | positive: h', r'h^2\sqrt3'),
                                 ('S/2 | positive: S', r'S\sqrt4/4')):
            with self.subTest(value=value):
                slot = self.slot('{{expression: ' + reference + '}}')
                self.assertEqual(check_slot(slot, value), 'ok')
                self.assertEqual(check_slot(slot, value + '+1'), 'wrong')

    def test_single_latex_token_does_not_consume_following_digit(self):
        slot = self.slot('{{number: 6}}')
        self.assertEqual(check_slot(slot, r'\sqrt16'), 'ok')
        self.assertEqual(check_slot(slot, 'sqrt(16)'), 'wrong')

    def test_ascii_roots_in_ordered_ratios(self):
        slot = self.slot('{{ratio: 1:2}}')
        self.assertEqual(check_slot(slot, 'sqrt(2):sqrt(8)'), 'ok')
        self.assertEqual(check_slot(slot, 'sqrt(8):sqrt(2)'), 'wrong')

    def test_undefined_and_variable_roots_are_not_numeric_answers(self):
        slot = self.slot('{{number: 1}}')
        for value in ('sqrt(-1)', 'sqrt(x^2)', 'sqrt(1', 'sqrt(1/0)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'unknown')

    def test_cancellation_cannot_hide_nonreal_numeric_roots(self):
        for reference, value in (('0', '0*sqrt(-1)'), ('1', '1+0*sqrt(-1)'),
                                 ('0', r'0*\sqrt{-1}'),
                                 ('1', '1+sqrt(-1)-sqrt(-1)')):
            with self.subTest(value=value):
                self.assertEqual(check_slot(self.slot('{{number: ' + reference + '}}'),
                                            value), 'unknown')
        self.assertEqual(check_slot(self.slot('{{number: 0}}'), '0*sqrt(1)'), 'ok')

    def test_symbolic_normalization_preserves_extra_domain_holes(self):
        slot = self.slot('{{expression: a | positive: a}}')
        self.assertEqual(check_slot(slot, 'sqrt(a^2)'), 'ok')
        self.assertEqual(check_slot(slot, 'a*sqrt(a-1)/sqrt(a-1)'), 'wrong')

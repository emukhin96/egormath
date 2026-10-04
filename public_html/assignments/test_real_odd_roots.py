"""Школьные нечётные корни сохраняют знак и исходную область определения."""
from django.test import SimpleTestCase
from .checks import formulas
from .checks.mask import parse_mask, check_slot


class RealOddRootTests(SimpleTestCase):
    def setUp(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def tearDown(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, payload, multiple=False):
        kind = 'expressions' if multiple else 'expression'
        spec = parse_mask('{{'+kind+': '+payload+'}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_cube_and_fifth_roots_keep_sign_on_all_real_inputs(self):
        slot = self.slot('x')
        for value in (r'\sqrt[3]{x^3}', r'-\sqrt[3]{-x^3}',
                      r'\sqrt[5]{x^5}', r'-\sqrt[5]{-x^5}'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'\sqrt[3]{-x^3}', r'\sqrt{x^2}'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_odd_rational_powers_keep_negative_real_base(self):
        slot = self.slot('x')
        for value in (r'(x^3)^{1/3}', r'-(-x^3)^{1/3}',
                      r'-(-x^5)^{1/5}'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        square = self.slot('x^2')
        self.assertEqual(check_slot(square, r'(-x^3)^{2/3}'), 'ok')
        self.assertEqual(check_slot(square, r'-(-x^3)^{2/3}'), 'wrong')

    def test_negative_exponent_preserves_zero_restriction(self):
        reciprocal = self.slot('1/x')
        for value in (r'(x^3)^{-1/3}', r'-(-x^3)^{-1/3}'):
            self.assertEqual(check_slot(reciprocal, value), 'ok', value)
        slot = self.slot('x')
        self.assertEqual(check_slot(slot, r'x+0*(x^3)^{-1/3}'), 'wrong')

    def test_reference_itself_can_use_real_odd_root(self):
        slot = self.slot(r'\sqrt[3]{x}')
        self.assertEqual(check_slot(slot, r'-\sqrt[3]{-x}'), 'ok')
        self.assertEqual(check_slot(slot, r'-\sqrt[3]{x}'), 'wrong')

    def test_even_roots_and_nonreal_intermediates_do_not_become_valid(self):
        slot = self.slot('x')
        for value in (r'x+0\sqrt{-1}', r'x+0\sqrt[3]{i}',
                      r'x+0\sqrt[4]{-1}', r'x+0*0^0',
                      r'x+0\sqrt{-x^2}'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_cancelled_odd_root_denominator_keeps_its_hole(self):
        slot = self.slot('x')
        self.assertEqual(check_slot(slot, r'x+0/\sqrt[3]{x-1}'), 'wrong')
        positive = self.slot('x | positive: x')
        self.assertEqual(check_slot(positive, r'x+0/\sqrt[3]{x}'), 'ok')

    def test_half_angle_root_uses_proven_positive_cosine(self):
        slot = self.slot(r'd/(2\cos(\alpha/2)) | positive: d,\alpha | angle: \alpha<90')
        reference = slot.reference
        for value in ('-\\sqrt[3]{-('+reference+')^3}',
                      '-\\sqrt[5]{-('+reference+')^5}'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        self.assertEqual(check_slot(slot, '-('+reference+')'), 'wrong')

    def test_proven_negative_cosine_keeps_odd_root_sign(self):
        slot = self.slot(r'\cos\alpha | positive: \alpha | angle: 90<\alpha<180')
        for value in (r'\sqrt[3]{(\cos\alpha)^3}',
                      r'-\sqrt[3]{-(\cos\alpha)^3}'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        self.assertEqual(check_slot(slot, r'|\cos\alpha|'), 'wrong')

    def test_unproved_trigonometric_sign_is_not_assumed_positive(self):
        slot = self.slot(r'\cos\alpha | positive: \alpha | angle: \alpha<180')
        self.assertEqual(check_slot(slot, r'\sqrt{(\cos\alpha)^2}'), 'wrong')

    def test_unordered_lengths_keep_count_and_repetition(self):
        slot = self.slot(r'd*\sin(\alpha/2);d*\cos(\alpha/2) | positive: d,\alpha | angle: \alpha<90', True)
        left, right = slot.reference.split(';')
        root = lambda value: '-\\sqrt[3]{-('+value+')^3}'
        self.assertEqual(check_slot(slot, root(right)+';'+root(left)), 'ok')
        self.assertEqual(check_slot(slot, root(left)+';'+root(left)), 'wrong')
        self.assertEqual(check_slot(slot, root(right)+';'+root(left)+';d'), 'wrong')

    def test_degree_range_is_not_converted_to_radians(self):
        slot = self.slot(r'90-2\alpha | positive: \alpha | range: \alpha<45')
        self.assertEqual(check_slot(slot, r'-\sqrt[3]{-(90-2\alpha)^3}'), 'ok')
        self.assertEqual(check_slot(slot, r'\sqrt[3]{-(90-2\alpha)^3}'), 'wrong')

    def test_numeric_roots_and_pi_keep_existing_real_meaning(self):
        for expected, value in (('3', r'-\sqrt[3]{-27}'),
                                ('9', r'(-27)^{2/3}'),
                                (r'\pi', r'-\sqrt[3]{-\pi^3}')):
            slot = parse_mask('{{number: '+expected+'}}', validate_references=True).slots[0]
            self.assertEqual(check_slot(slot, value), 'ok', value)

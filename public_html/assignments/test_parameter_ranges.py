"""Конечный числовой диапазон сохраняет единицы и исходные ограничения."""
from unittest.mock import patch
from django.test import SimpleTestCase
from django.template.loader import render_to_string
from .checks import formulas
from .checks.mask import parse_mask, check_slot, render_fragments


class ParameterRangeTests(SimpleTestCase):
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

    def test_complementary_angle_keeps_degree_constants(self):
        slot = self.slot(r'180-\alpha | positive: \alpha | range: \alpha<180')
        for value in (r'|180-\alpha|', r'\sqrt{(180-\alpha)^2}',
                      r'(180^2-\alpha^2)/(180+\alpha)',
                      r'180-\alpha+0/(180-\alpha)'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'\alpha-180', r'180-\alpha+0.00000000000000000001',
                      r'\pi-\alpha'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_square_angle_keeps_positive_degree_measure(self):
        slot = self.slot(r'90-2\alpha | positive: \alpha | range: \alpha<45')
        for value in (r'|90-2\alpha|', r'\sqrt{(90-2\alpha)^2}',
                      r'2(45-\alpha)', r'1/(2/(180-4\alpha))'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'2\alpha-90', r'|90-2\alpha|+1',
                      r'90-2\alpha+0/(\alpha-30)',
                      r'90-2\alpha+0\sqrt{\alpha-30}',
                      r'90-2\alpha+0*0^0'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_open_endpoints_and_outside_poles_are_allowed(self):
        slot = self.slot(r'\alpha-10 | positive: \alpha | range: 10<\alpha<45')
        for value in (r'|\alpha-10|', r'\sqrt{(\alpha-10)^2}',
                      r'\alpha-10+0/(\alpha-10)+0/(45-\alpha)',
                      r'\alpha-10+0/(\alpha-9)+0/(46-\alpha)'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'\alpha-10+0/(\alpha-20)', r'10-\alpha'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_exact_decimal_and_fractional_bounds(self):
        for bound in ('22.5', '45/2'):
            slot = self.slot(r'45-2\alpha | positive: \alpha | range: \alpha<'+bound)
            self.assertEqual(check_slot(slot, r'|45-2\alpha|'), 'ok')
            self.assertEqual(check_slot(slot, r'45-2\alpha+0/(\alpha-15)'), 'wrong')

    def test_lists_preserve_order_independence_and_multiplicity(self):
        slot = self.slot(r'\alpha;180-\alpha | positive: \alpha | range: \alpha<180', True)
        self.assertEqual(check_slot(slot, r'|180-\alpha|;|\alpha|'), 'ok')
        for value in (r'\alpha;\alpha', r'\alpha;180-\alpha;180',
                      r'\alpha;180-\alpha+0/(\alpha-30)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_ranges_and_unrestricted_parameters_do_not_share_cache(self):
        payload = r'45-\alpha | positive: \alpha'
        value = r'|45-\alpha|'
        self.assertEqual(check_slot(self.slot(payload+r' | range: \alpha<45'), value), 'ok')
        self.assertEqual(check_slot(self.slot(payload+r' | range: \alpha<90'), value), 'wrong')
        self.assertIn(check_slot(self.slot(payload), value), ('wrong', 'unknown'))
        self.assertEqual(check_slot(self.slot(payload+r' | range: \alpha<45'), value), 'ok')

    def test_internal_chart_and_foreign_parameters_are_not_student_symbols(self):
        slot = self.slot(r'180-\alpha | positive: \alpha | range: \alpha<180')
        for value in ('180/(1+u)', r'180-\alpha+0u', r'180-\alpha+0z'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_invalid_or_conflicting_bounds_are_not_ignored(self):
        base = r'{{expression: 180-\alpha | positive: \alpha | range: '
        for option in (r'\alpha<0', r'45<\alpha<45', r'46<\alpha<45',
                       r'-1<\alpha<45', r'\alpha<=45', r'\alpha<1/0',
                       r'\alpha<1000000', r'\alpha<\pi', r'\beta<45',
                       r'\alpha<45 junk', r'\alpha<45 | range: \alpha<90',
                       r'\alpha<45 | angle: \alpha<90'):
            self.assertFalse(parse_mask(base+option+'}}').is_valid, option)
        self.assertFalse(parse_mask(r'{{expression: a+b | positive: a,b | domain: a<2b | range: a<45}}').is_valid)
        self.assertFalse(parse_mask(r'{{expression: 180-\alpha | range: \alpha<180}}').is_valid)
        for kind in ('simplify', 'factor'):
            self.assertFalse(parse_mask('{{'+kind+r': 180-\alpha | positive: \alpha | range: \alpha<180}}').is_valid)
        self.assertFalse(parse_mask(r'{{expression: 180-\alpha | positive: \alpha,\beta | range: \beta<180}}', validate_references=True).is_valid)

    def test_display_preserves_reference_without_starting_worker(self):
        with patch.object(formulas, '_spawn') as spawn:
            spec = parse_mask(r'Угол: {{expression: |180-\alpha| | positive: \alpha | range: \alpha<180}}$^{\circ}$')
            self.assertTrue(spec.is_valid, spec.errors)
            self.assertEqual(spec.slots[0].reference, r'|180-\alpha|')
            html = render_to_string('assignments/_mask.html', {
                'fragments': render_fragments(spec, 'range', {'s1': ''}), 'editable': True})
            self.assertIn('<math-field', html)
            self.assertNotIn('range:', html)
            spawn.assert_not_called()

    def test_chart_is_bijective_and_preserves_raw_denominators(self):
        from sympy import Rational
        reference, _ = formulas._parse_reference(r'90-2\alpha | positive: \alpha | range: 10<\alpha<45')
        alpha, value = reference.substitutions[0]
        u = next(iter(value.free_symbols))
        self.assertEqual(value.subs(u, 1), Rational(55, 2))
        self.assertTrue(u.is_positive)
        raw = formulas._parse(r'90-2\alpha+0/(\alpha-30)', reference.positive)
        moved = formulas._in_context(raw, reference.substitutions)
        self.assertTrue(any(d.subs(u, Rational(4, 3)) == 0 for d in moved.denominators))
        self.assertFalse(formulas._defined(moved, reference))

    def test_range_with_another_positive_parameter_preserves_domain(self):
        slot = self.slot(r'h*(180-\alpha) | positive: h,\alpha | range: \alpha<180')
        self.assertEqual(check_slot(slot, r'|h*(180-\alpha)|'), 'ok')
        for value in (r'h*(180-\alpha)+0/(\alpha-30)',
                      r'h*(180-\alpha)+0\sqrt{\alpha-30}'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

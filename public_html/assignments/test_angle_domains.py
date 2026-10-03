"""Открытые угловые области сохраняют корректность и исходные ограничения."""
from unittest.mock import patch
from django.test import SimpleTestCase
from django.template.loader import render_to_string
from .checks import formulas
from .checks.mask import parse_mask, check_slot, render_fragments


class AngleDomainTests(SimpleTestCase):
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

    def test_vertex_angle_allows_absolute_values_and_half_angle_identities(self):
        slot = self.slot(r'h/\cos(\beta/2) | positive: h,\beta | angle: \beta<180')
        for value in (r'|h/\cos(\beta/2)|', r'h/|\cos(\beta/2)|',
                      r'h/\sqrt{(\cos(\beta/2))^2}',
                      r'h*\sqrt{2/(1+\cos\beta)}'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'-h/\cos(\beta/2)', r'h/\cos(\beta/2)+1',
                      r'h/\cos(\beta/2)+0/(h-1)',
                      r'h/\cos(\beta/2)+0\sqrt{-1}'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_acute_angle_keeps_unordered_side_count(self):
        slot = self.slot(r'h/\sin\alpha;h/\cos\alpha | positive: h,\alpha | angle: \alpha<90', True)
        for value in (r'|h/\cos\alpha|;|h/\sin\alpha|',
                      r'h/\sqrt{1-\cos^2\alpha};h/\sqrt{1-\sin^2\alpha}'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'h/\cos\alpha;h/\cos\alpha',
                      r'h/\sin\alpha;h/\cos\alpha;h',
                      r'h/\sin\alpha+0/(h-1);h/\cos\alpha'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_hypotenuse_preserves_sign_and_hidden_invalid_actions(self):
        slot = self.slot(r'h/(\sin\alpha\cos\alpha) | positive: h,\alpha | angle: \alpha<90')
        for value in (r'|h/(\sin\alpha\cos\alpha)|', r'2h/\sin(2\alpha)',
                      r'h/\sqrt{\sin^2\alpha\cos^2\alpha}'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'h/(\sin\alpha\cos\alpha)+0/(\sin\alpha-\cos\alpha)',
                      r'h/(\sin\alpha\cos\alpha)+0*0^0',
                      r'h/(\sin\alpha\cos\alpha)+0\sqrt{-h}'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_context_bound_and_unbounded_masks_do_not_share_results(self):
        base = r'h/\cos\alpha | positive: h,\alpha'
        value = r'h/|\cos\alpha|'
        acute = self.slot(base+r' | angle: \alpha<90')
        wider = self.slot(base+r' | angle: \alpha<180')
        unrestricted = self.slot(base)
        self.assertEqual(check_slot(acute, value), 'ok')
        self.assertEqual(check_slot(wider, value), 'wrong')
        self.assertIn(check_slot(unrestricted, value), ('wrong', 'unknown'))
        self.assertEqual(check_slot(acute, value), 'ok')

    def test_internal_chart_parameters_and_other_symbols_are_rejected(self):
        slot = self.slot(r'h/\cos\alpha | positive: h,\alpha | angle: \alpha<90')
        for value in ('h*sqrt(1+u^2)', r'h/\cos\alpha+0u',
                      r'h/\cos\alpha+0z', r'h/\cos\alpha+0/(u-1)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_unsupported_or_conflicting_bounds_are_not_ignored(self):
        base = r'{{expression: h/\cos\alpha | positive: h,\alpha | angle: '
        for option in (r'\alpha<0', r'\alpha<361', r'\alpha<=90', r'90<\alpha<90', r'\alpha<1/0',
                       r'\alpha<\pi/2', r'\beta<90', r'\alpha<90 junk',
                       r'\alpha<90 | angle: \alpha<180',
                       r'\alpha<90 | unknown: 1'):
            self.assertFalse(parse_mask(base+option+'}}').is_valid, option)
        self.assertFalse(parse_mask(r'{{expression: h/\cos\alpha | positive: h | angle: \alpha<90}}').is_valid)
        self.assertFalse(parse_mask(r'{{expression: ab | positive: a,b | domain: a<2b | angle: a<90}}').is_valid)
        for kind in ('simplify', 'factor'):
            self.assertFalse(parse_mask('{{'+kind+r': h/\cos\alpha | positive: h,\alpha | angle: \alpha<90}}').is_valid)
        self.assertFalse(parse_mask(r'{{expression: h/\cos\alpha | positive: h,\alpha,\beta | angle: \beta<90}}', validate_references=True).is_valid)

    def test_display_preserves_reference_and_does_not_spawn_worker(self):
        with patch.object(formulas, '_spawn') as spawn:
            spec = parse_mask(r'Основание: {{expression: |h/\cos(\beta/2)| | positive: h,\beta | angle: \beta<180}}')
            self.assertTrue(spec.is_valid, spec.errors)
            self.assertEqual(spec.slots[0].reference, r'|h/\cos(\beta/2)|')
            html = render_to_string('assignments/_mask.html', {
                'fragments': render_fragments(spec, 'angle', {'s1': ''}), 'editable': True})
            self.assertIn('<math-field', html)
            self.assertNotIn('angle:', html)
            spawn.assert_not_called()

    def test_chart_bijection_moves_reference_and_raw_restrictions(self):
        from sympy import atan, pi
        reference, _ = formulas._parse_reference(r'h/\cos\alpha | positive: h,\alpha | angle: \alpha<90')
        alpha, replacement = reference.substitutions[0]
        u = next(iter(replacement.free_symbols))
        self.assertTrue(u.is_positive)
        self.assertEqual(replacement, atan(u))
        self.assertEqual(replacement.subs(u, 1), pi/4)
        raw = formulas._parse(r'h/\cos\alpha+0/(\sin\alpha-\cos\alpha)', reference.positive)
        moved = formulas._in_context(raw, reference.substitutions, angular=True)
        self.assertTrue(any(d.subs(u, 1) == 0 for d in moved.denominators))
        self.assertFalse(formulas._defined(moved, reference))

    def test_general_open_bounds_and_endpoint_restrictions(self):
        for option in (r'\alpha<45', r'\alpha<22.5', r'\alpha<45/2'):
            slot = self.slot(r'h/\cos\alpha | positive: h,\alpha | angle: '+option)
            self.assertEqual(check_slot(slot, r'h/|\cos\alpha|'), 'ok', option)
        obtuse = self.slot(r'h/\cos\beta | positive: h,\beta | angle: 90<\beta<180')
        self.assertEqual(check_slot(obtuse, r'-h/|\cos\beta|'), 'ok')
        self.assertEqual(check_slot(obtuse, r'h/|\cos\beta|'), 'wrong')
        vertex = self.slot(r'h/\cos(\beta/2) | positive: h,\beta | angle: \beta<180')
        for value in (r'h/\cos(\beta/2)+0/(\pi-\beta)',
                      r'h/\cos(\beta/2)+0/\sin(\beta/4)'):
            self.assertEqual(check_slot(vertex, value), 'ok', value)

    def test_interior_angular_poles_and_complex_components_are_wrong(self):
        slot = self.slot(r'h/\cos(\beta/2) | positive: h,\beta | angle: \beta<180')
        for value in (r'h/\cos(\beta/2)+0/(\beta-\pi/3)',
                      r'h/\cos(\beta/2)+0/(\sin\beta-\cos\beta)',
                      r'h/\cos(\beta/2)+0\sqrt{\beta-\pi/2}'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_acute_half_angle_tangent_and_cotangent_signs(self):
        tangent = self.slot(r'd\cdot\tan(\alpha/2) | positive: d,\alpha | angle: \alpha<90')
        for value in (r'|d\cdot\tan(\alpha/2)|',
                      r'\sqrt{(d\cdot\tan(\alpha/2))^2}'):
            self.assertEqual(check_slot(tangent, value), 'ok', value)
        self.assertEqual(check_slot(tangent, r'-|d\cdot\tan(\alpha/2)|'), 'wrong')
        cotangent = self.slot(r'd\cdot\cot(\alpha/2) | positive: d,\alpha | angle: \alpha<90')
        self.assertEqual(check_slot(cotangent, r'|d\cdot\cot(\alpha/2)|'), 'ok')
        obtuse = self.slot(r'd\cdot\tan\alpha | positive: d,\alpha | angle: 90<\alpha<180')
        self.assertEqual(check_slot(obtuse, r'|d\cdot\tan\alpha|'), 'wrong')

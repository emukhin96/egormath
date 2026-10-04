"""Область существования треугольника сохраняет все ограничения ответа."""
from unittest.mock import patch
from django.test import SimpleTestCase
from django.template.loader import render_to_string
from .checks import formulas
from .checks.mask import check_slot, parse_mask, render_fragments


class FormulaDomainTests(SimpleTestCase):
    payload = 'ab/(a+b) | positive: a,b | domain: a<2b'

    def setUp(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def tearDown(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, payload=None):
        spec = parse_mask('{{expression: ' + (payload or self.payload) + '}}',
                          validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_accepts_unreduced_forms_on_the_exact_triangle_domain(self):
        slot = self.slot()
        f = 'ab/(a+b)'
        for value in (f, '2ab/(2(a+b))', '1/(1/a+1/b)',
                      f+'*(2b-a)/(2b-a)', f+'*sqrt(2b-a)/sqrt(2b-a)',
                      f+'*sqrt((2b-a)^2)/(2b-a)', f+'+0/(2b-a)',
                      f+'+0/sqrt(2b-a)', f+'*(2b-a)^0',
                      f+'+sqrt(2b-a)-sqrt(2b-a)', '|a|*b/(a+b)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')

    def test_rejects_holes_and_complex_parts_even_after_cancellation(self):
        slot = self.slot()
        f = 'ab/(a+b)'
        for value in (f+'*(a-b)/(a-b)', f+'+0/(a-b)',
                      f+'*(a-b)^0', f+'*sqrt(a-b)/sqrt(a-b)',
                      f+'*(2a-3b)/(2a-3b)', f+'+0/(2a-3b)',
                      'ab(2a-3b)/((a+b)(2a-3b))',
                      f+'*sqrt(a-2b)/sqrt(a-2b)',
                      f+'*sqrt((a-2b)^2)/(a-2b)', '2ab/(a+b)',
                      f+'+0*(1/0)', f+'+0*sqrt(-1)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_internal_chart_names_are_not_student_parameters(self):
        slot = self.slot()
        for value in ('2u(u+v)/(3u+v)', 'ab/(a+b)+0/(u-1)',
                      'ab/(a+b)+0/(z-1)', 'ab/(a+b)+0*z',
                      'ab/(a+b)+0*u', 'ab/(a+b)+0*v'):
            self.assertEqual(check_slot(slot, value), 'wrong')

    def test_contexts_do_not_leak_through_the_cache(self):
        value = 'ab/(a+b)*(2b-a)/(2b-a)'
        unrestricted = self.slot('ab/(a+b) | positive: a,b')
        triangle = self.slot()
        self.assertEqual(check_slot(unrestricted, value), 'wrong')
        self.assertEqual(check_slot(triangle, value), 'ok')
        self.assertEqual(check_slot(unrestricted, value), 'wrong')
        # При обратном неравенстве тот же корень невещественен.
        reverse = self.slot('ab/(a+b) | positive: a,b | domain: b<1/2a')
        self.assertEqual(check_slot(reverse, 'ab/(a+b)+0*sqrt(2b-a)'), 'wrong')

    def test_invalid_or_unsupported_domains_cannot_be_silently_ignored(self):
        base = 'ab/(a+b) | positive: a,b'
        for option in ('a<=2b', 'a>2b', 'a<0b', 'a<2/0b', 'a<0/2b',
                       'a<a', 'a<2c', 'a<2b, b<a', 'a<2b | domain: b<a',
                       'a<2b | unknown: z', 'a<2b | positive: a,b',
                       'a<1000000b', 'a<2b junk'):
            with self.subTest(option=option):
                self.assertFalse(parse_mask('{{expression: '+base+' | domain: '+option+'}}').is_valid)
        self.assertFalse(parse_mask('{{expression: ab/(a+b) | domain: a<2b}}').is_valid)
        for kind in ('simplify', 'factor', 'expressions'):
            self.assertFalse(parse_mask('{{'+kind+': '+self.payload+'}}').is_valid)
        # Два токена одной греческой буквы не задают независимую область.
        aliased = r'\phi+\varphi | positive: \phi,\varphi | domain: \phi<2\varphi'
        self.assertFalse(parse_mask('{{expression: '+aliased+'}}', validate_references=True).is_valid)

    def test_options_and_absolute_value_bars_preserve_display(self):
        for payload in ('|a|*b/(a+b) | positive: a,b | domain: a<2*b',
                        '|a|*b/(a+b) | domain: a<2b | positive: a,b'):
            slot = self.slot(payload)
            self.assertEqual(slot.reference, '|a|*b/(a+b)')
            self.assertEqual(check_slot(slot, 'ab/(a+b)'), 'ok')
        formulas._reference_response.cache_clear()
        with patch.object(formulas, '_spawn') as spawn:
            spec = parse_mask('Длина $MK$: {{expression: '+self.payload+'}}.')
            self.assertTrue(spec.is_valid, spec.errors)
            html = render_to_string('assignments/_mask.html', {
                'fragments': render_fragments(spec, 'domain7878'), 'editable': True})
            self.assertIn('<math-field', html)
            spawn.assert_not_called()

    def test_chart_is_bijective_and_moves_raw_restrictions(self):
        from sympy import Rational, simplify
        reference, _ = formulas._parse_reference(self.payload)
        substitutions = dict(reference.substitutions)
        by_name = {str(s): s for s in reference.input_symbols}
        a, b = by_name['a'], by_name['b']
        u = substitutions[a]/2
        v = substitutions[b]-u
        self.assertTrue(u.is_positive)
        self.assertTrue(v.is_positive)
        self.assertEqual(simplify(2*substitutions[b]-substitutions[a]), 2*v)
        self.assertEqual(reference.items[0].expression.subs({u: Rational(3,2), v: Rational(1,2)}), Rational(6,5))
        raw = formulas._parse('ab/(a+b)+0/(2a-3b)', reference.positive)
        moved = formulas._in_context(raw, reference.substitutions)
        self.assertTrue(any(d.subs({u: 3, v: 1}) == 0 for d in moved.denominators))
        self.assertFalse(formulas._defined(moved, reference))

    def test_zero_times_unknown_symbol_is_rejected_without_domain_too(self):
        for payload in ('ab/(a+b) | positive: a,b', 'ab/(a+b)'):
            slot = self.slot(payload)
            self.assertEqual(check_slot(slot, 'ab/(a+b)+0*z'), 'wrong')
            self.assertEqual(check_slot(slot, 'ab/(a+b)+0*a'), 'ok')
        reference, _ = formulas._parse_reference(r'\alpha | positive: \alpha')
        self.assertEqual(formulas._check(r'\alpha+0\beta', reference), 'wrong')
        self.assertEqual(formulas._check(r'\alpha+0\alpha', reference), 'ok')

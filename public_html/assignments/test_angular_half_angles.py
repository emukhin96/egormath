"""Половинные углы: эквивалентность на всём интервале и исходные разрывы."""
import sympy as sp
from django.test import SimpleTestCase
from assignments.checks import formulas
from assignments.checks.mask import parse_mask, check_slot


class AngularHalfAnglesTests(SimpleTestCase):
    def slot(self, body):
        spec = parse_mask('{{' + body + '}}')
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_textbook_half_angle_identities(self):
        cases = (
            (r'expression: d/(2\cos(\alpha/2)) | positive:d,\alpha | angle:\alpha<90',
             (r'd/\sqrt{2+2\cos\alpha}',)),
            (r'expression: d\tan(\alpha/2) | positive:d,\alpha | angle:\alpha<90',
             (r'd\sin\alpha/(1+\cos\alpha)',
              r'd\sqrt{(1-\cos\alpha)/(1+\cos\alpha)}')),
            (r'expression: 2r/\sin\alpha | positive:r,\alpha | angle:\alpha<90',
             (r'2r*(1+\tan^2(\alpha/2))/(2\tan(\alpha/2))',)),
            (r'expressions: 2r/\sin(\alpha/2);2r/\cos(\alpha/2) | positive:r,\alpha | angle:\alpha<90',
             (r'2r*\sqrt{2/(1-\cos\alpha)};2r*\sqrt{2/(1+\cos\alpha)}',
              r'2r*\sqrt{2/(1+\cos\alpha)};2r*\sqrt{2/(1-\cos\alpha)}')),
        )
        for body, values in cases:
            slot = self.slot(body)
            for value in values:
                with self.subTest(body=body, value=value):
                    self.assertEqual(check_slot(slot, value), 'ok')
                    first, *rest = value.split(';')
                    bad = '-(' + first + ')' + (';' + ';'.join(rest) if rest else '')
                    self.assertEqual(check_slot(slot, bad), 'wrong')

    def test_half_angle_normalization_retains_original_undefined_components(self):
        slot = self.slot(r'expression: d\tan(\alpha/2) | positive:d,\alpha | angle:\alpha<90')
        correct = r'd\sqrt{(1-\cos\alpha)/(1+\cos\alpha)}'
        for extra in (r'+0/(\alpha-\pi/4)', r'+0*\sqrt{-d}', r'+0*(0^0)'):
            with self.subTest(extra=extra):
                self.assertEqual(check_slot(slot, correct + extra), 'wrong')

    def test_root_sign_is_not_discarded_for_obtuse_angles(self):
        slot = self.slot(r'expression: \cos\alpha | positive:\alpha | angle:\alpha<180')
        self.assertEqual(check_slot(slot, r'\sqrt{\cos^2\alpha}'), 'wrong')
        slot = self.slot(r'expression: \sin(\alpha/2) | positive:\alpha | angle:180<\alpha<360')
        self.assertEqual(check_slot(slot, r'-\sqrt{(1-\cos\alpha)/2}'), 'wrong')

    def test_helper_needs_positive_half_angle_and_proven_radical_difference(self):
        u = sp.Symbol('u', positive=True)
        x = sp.Symbol('x', real=True)
        v = formulas._angular_half_angles(sp.tan(sp.atan(u)/2))
        self.assertEqual(sp.simplify(v-u/(sp.sqrt(1+u*u)+1)), 0)
        self.assertEqual(formulas._angular_half_angles(sp.tan(sp.atan(x)/2)),
                         sp.tan(sp.atan(x)/2))
        self.assertEqual(sp.simplify(formulas._angular_half_angles(sp.sqrt(1+u*u)-1)
                                    - u*u/(sp.sqrt(1+u*u)+1)), 0)
        # sqrt(x²)-1 меняет знак; положительность здесь не доказана.
        self.assertEqual(formulas._angular_half_angles(sp.sqrt(x*x)-1), sp.Abs(x)-1)

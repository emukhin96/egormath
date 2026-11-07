"""Ответ без левой части в маске «величина = число».

Шабунин 16195: маска {{equation: \\alpha=\\operatorname{arctg}\\frac{1}{\\sqrt{2}}}},
поле ученика не показывает «α =», и ответ $\\arcsin\\frac{1}{\\sqrt3}$ (тот же
угол) получал «не проверено»: слот уравнения требовал знак «=». Так же
«-6» при {{equation: a=-6}} и «32» при {{equation: S=32}}.
"""
from django.test import SimpleTestCase

from .checks import formulas
from .checks.mask import check_mask, check_slot, parse_mask


class EquationBareValueTests(SimpleTestCase):
    def setUp(self):
        formulas._checked.cache_clear()
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, mask):
        spec = parse_mask(mask, validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def assertVerdicts(self, mask, ok=(), wrong=(), unknown=()):
        slot = self.slot(mask)
        for expected, values in (('ok', ok), ('wrong', wrong), ('unknown', unknown)):
            for value in values:
                with self.subTest(mask=mask, value=value):
                    self.assertEqual(check_slot(slot, value), expected)

    def test_same_angle_without_left_side(self):
        self.assertVerdicts(
            r'{{equation: \alpha=\operatorname{arctg} \frac{1}{\sqrt{2}}}}',
            ok=[r'\arcsin\frac{1}{\sqrt3}', r'\arcsin\left(\frac{1}{\sqrt{3}}\right)',
                'arcsin(1/sqrt(3))', r'\arccos\sqrt{\frac23}',
                r'\operatorname{arctg}\frac{1}{\sqrt2}',
                r'\alpha=\arcsin\frac{1}{\sqrt3}'],
            wrong=[r'\arcsin\frac{1}{\sqrt2}', r'\beta=\arcsin\frac{1}{\sqrt3}'])

    def test_parameter_value_without_left_side(self):
        self.assertVerdicts(r'{{equation: a=-6}}',
                            ok=['-6', 'a=-6', '-12/2'], wrong=['6'], unknown=['b'])
        self.assertVerdicts(r'{{equation: a=2 | strict}}', ok=['2'])

    def test_line_and_formula_still_need_equation(self):
        # x=2 и y=-0,25 — прямые (ось симметрии, ГМТ): «2» не уравнение.
        self.assertVerdicts(r'{{equation: x=2}}', ok=['x=2'], unknown=['2'])
        self.assertVerdicts(r'{{equation: y=x+5}}', unknown=['x+5'])

    def test_whole_mask_verdict(self):
        spec = parse_mask(r'{{equation: \alpha=\operatorname{arctg} \frac{1}{\sqrt{2}}}}')
        self.assertEqual(check_mask(spec, {'s1': r'\arcsin\frac{1}{\sqrt{3}}'})[0], 'ok')

"""Точные градусы внутри числовых аргументов тригонометрических функций."""
import sympy as sp
from django.test import SimpleTestCase
from assignments.checks import formulas
from assignments.checks.mask import parse_mask, check_slot


class DegreeArgumentsTests(SimpleTestCase):
    def slot(self, reference):
        spec = parse_mask('{{number: ' + reference + '}}')
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_explicit_and_bare_numeric_degrees(self):
        cases = ((r'\sin(30^{\circ})', sp.Rational(1, 2)),
                 (r'\sin30^\circ', sp.Rational(1, 2)),
                 (r'\cos(60°)', sp.Rational(1, 2)),
                 (r'\tan(45^{\circ})', 1),
                 (r'\cot45°', 1),
                 (r'\sin^{2}(30°)', sp.Rational(1, 4)),
                 (r'\sin(-30°)', sp.Rational(-1, 2)),
                 (r'\sin(-30°)^2', sp.Rational(1, 4)),
                 (r'\sin((90/3)°)', sp.Rational(1, 2)),
                 (r'\sin(10°+20°)', sp.Rational(1, 2)),
                 (r'\sin\left(30^{\circ}\right)2', 1),
                 (r'\sin(30,0°)', sp.Rational(1, 2)))
        for value, expected in cases:
            with self.subTest(value=value):
                parsed = formulas._parse(value, numeric=True)
                self.assertIsNotNone(parsed, value)
                self.assertEqual(sp.simplify(parsed.expression-expected), 0)

    def test_radians_and_function_boundaries_are_preserved(self):
        parsed = formulas._parse(r'\sin(30)', numeric=True)
        self.assertEqual(parsed.expression, sp.sin(30))
        for value in (r'30°', r'\sin(30)°', r'\sin(30°)+1°',
                      r'\sin(30°', r'\sin(30°))', r'\sin(30°)^\circ'):
            self.assertIsNone(formulas._parse(value, numeric=True), value)
        # Числовые градусы допустимы и внутри формул с параметрами;
        # символьные градусы требуют отдельного контекста angle.
        self.assertEqual(formulas._parse(r'\sin(30°)').expression,
                         sp.Rational(1, 2))
        self.assertIsNone(formulas._parse(r'\sin(alpha°)'))

    def test_mathlive_degree_macro_is_numeric_angle_only(self):
        for value in (r'\sin(30\degree)', r'\sin30\degree',
                      r'\sin((90/3)\degree)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(self.slot('1/2'), value), 'ok')
        for value in (r'30\degree', r'\sin(30)\degree',
                      r'\sin(alpha\degree)'):
            self.assertIsNone(formulas._parse(value, numeric=True), value)

    def test_symbolic_formula_accepts_equivalent_numeric_degree_angles(self):
        slot = parse_mask('{{expression: R | positive:R}}').slots[0]
        for value in (r'2R(\sin(54^{\circ})-\sin(18^{\circ}))',
                      r'2R(\sin54°-\sin18°)',
                      r'2R\sin\left(30^{\circ}\right)',
                      r'2R\sin(30\degree)',
                      r'R/\tan(45°)',
                      r'4R\sin^2(30°)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        self.assertEqual(check_slot(slot, r'2R\sin(60°)'), 'wrong')
        # Без маркера градусов прежний смысл радианного угла сохранён.
        self.assertEqual(check_slot(slot, r'2R\sin(30)'), 'wrong')

    def test_symbolic_degree_formula_preserves_original_undefined_operations(self):
        slot = parse_mask('{{expression: R | positive:R}}').slots[0]
        for value in (r'2R\sin(30°)+0/(R-R)',
                      r'2R\sin(30\degree)+0/(R-R)',
                      r'2R\sin(30°)+0*sqrt(-R)',
                      r'2R\sin(30°)+0*(0^0)',
                      r'R/\sin(0°)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_symbolic_reference_can_contain_numeric_degrees(self):
        spec = parse_mask(r'{{expression: R/\sin(30°) | positive:R}}',
                          validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual(check_slot(spec.slots[0], '2R'), 'ok')

    def test_degree_marker_does_not_convert_a_power_exponent(self):
        for value in (r'\sin(R^2°)', r'\sin(R^{2}°)',
                      r'\sin(R^ 2°)', r'\sin(R^+2°)',
                      r'\sin(R^ -2°)', r'\sin(R^2\degree)',
                      r'\sin(R^2^{\circ})', r'\sin(2^3°)',
                      r'\sin(R^(2)°)', r'\sin(2^(3)°)',
                      r'\sin(R^ (2)°)', r'\sin(R^+(2)°)',
                      r'\sin(R^ -(2)°)', r'\sin(R^[2]°)',
                      r'\sin(R^((2))°)', r'\sin(R^(2)\degree)',
                      r'\sin(2^(3)^{\circ})'):
            with self.subTest(value=value):
                for numeric in (False, True):
                    self.assertIsNone(formulas._parse(value, numeric=numeric))
        # Явно сгруппированный числовой угол по-прежнему допустим.
        for value in (r'\sin((2^3)°)', r'\sin((2^(3))°)',
                      r'\sin((2^{3})°)'):
            self.assertEqual(formulas._parse(value).expression,
                             sp.sin(2*sp.pi/45))

    def test_real_worker_accepts_book_values_and_rejects_wrong_angles(self):
        slot = self.slot(r'9/\sin(70\pi/180) ~ 0.05')
        for value in (r'9/\sin(70^{\circ})', r'9/\sin70°'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        self.assertEqual(check_slot(slot, r'9/\sin(60°)'), 'wrong')
        self.assertEqual(check_slot(self.slot('1/2'), r'\sin(30°)'), 'ok')
        self.assertEqual(check_slot(self.slot('1/2'), r'\sin(60°)'), 'wrong')

    def test_original_undefined_operations_are_not_removed(self):
        slot = self.slot('1/2')
        for value in (r'\sin(30°)+0/(1-1)', r'\sin(30°)+0*sqrt(-1)',
                      r'\sin(30°)+0*(0^0)', r'1/\sin(0°)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)


    def test_symbolic_degree_groups_remain_unparsed(self):
        for group in (r'(90-\alpha)', r'(\alpha)', r'[\alpha]',
                      '(R-R+30)', '(alpha)', '(90-α)'):
            for marker in ('°', r'\degree', r'^{\circ}'):
                value = r'\sin(' + group + marker + ')'
                with self.subTest(value=value):
                    for numeric in (False, True):
                        self.assertIsNone(formulas._parse(value, numeric=numeric))


    def test_numeric_degree_groups_allow_commands_and_constants(self):
        for value, expected in ((r'\sin((\sqrt{900})°)', sp.Rational(1, 2)),
                                (r'\cos((\frac{180}{3})°)', sp.Rational(1, 2)),
                                (r'\sin((\pi)°)', sp.sin(sp.pi**2/180))):
            for numeric in (False, True):
                with self.subTest(value=value, numeric=numeric):
                    parsed = formulas._parse(value, numeric=numeric)
                    self.assertIsNotNone(parsed)
                    self.assertEqual(sp.simplify(parsed.expression-expected), 0)


    def test_symbolic_degree_groups_do_not_receive_wrong_verdict(self):
        references = (r'{{expression: \cos\alpha}}',
                      r'{{expression: \cos\alpha | positive: \alpha | angle: \alpha<90}}',
                      r'{{expression: 90-\alpha | positive: \alpha | range: \alpha<90}}',
                      '{{number: 1/2}}')
        for reference in references:
            spec = parse_mask(reference, validate_references=True)
            self.assertTrue(spec.is_valid, spec.errors)
            for value in (r'\sin((90-\alpha)°)', r'\sin((\alpha)°)'):
                with self.subTest(reference=reference, value=value):
                    self.assertEqual(check_slot(spec.slots[0], value), 'unknown')
        slot = parse_mask(references[1]).slots[0]
        self.assertEqual(check_slot(slot, r'\sin(90°-\alpha)'), 'ok')


    def test_numeric_degree_group_does_not_hide_undefined_operations(self):
        for value in (r'\sin((30+0/(1-1))°)',
                      r'\sin((30+0*\sqrt{-1})°)',
                      r'\sin((30+0*(0^0))°)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(self.slot('1/2'), value), 'wrong')

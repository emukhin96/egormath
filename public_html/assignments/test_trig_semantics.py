"""Аргументы функций должны сохранять математический смысл школьной записи."""
import sympy as sp
from django.test import SimpleTestCase

from assignments.checks import expressions, formulas
from assignments.checks.mask import check_slot, parse_mask


class TrigSemanticsTests(SimpleTestCase):
    def assert_formula(self, latex, expected):
        parsed = formulas._parse(latex)
        self.assertIsNotNone(parsed, latex)
        self.assertEqual(sp.simplify(parsed.expression - expected), 0, latex)

    def test_rectangle_area_keeps_two_independent_functions(self):
        d, alpha = sp.symbols('d alpha', real=True)
        expected = d**2 * sp.sin(alpha) * sp.cos(alpha)
        for latex in (r'd^2\sin\alpha\cos\alpha',
                      r'd^2\sin(\alpha)\cos(\alpha)',
                      r'd^2\sin(2\alpha)/2',
                      r'd^2\cdot\sin(2\cdot\alpha)/2',
                      r'\sin(\alpha)\cdot\cos(\alpha)\cdot d^2',
                      r'd^2(\sin(\alpha)\cos(\alpha))'):
            with self.subTest(latex=latex):
                self.assert_formula(latex, expected)

    def test_right_triangle_hypotenuse_denominator_is_a_product(self):
        h, alpha = sp.symbols('h alpha', real=True)
        expected = h / (sp.sin(alpha) * sp.cos(alpha))
        for latex in (r'\frac{h}{\sin\alpha\cos\alpha}',
                      r'\frac{h}{\sin(\alpha)\cos(\alpha)}',
                      r'h/\sin(\alpha)/\cos(\alpha)'):
            with self.subTest(latex=latex):
                self.assert_formula(latex, expected)

    def test_operators_outside_parentheses_stay_outside_function(self):
        x, y = sp.symbols('x y', real=True)
        for function in ('sin', 'cos', 'tan', 'cot', 'arcsin', 'arctan'):
            f = {'arcsin': sp.asin, 'arctan': sp.atan}.get(function, getattr(sp, function, None))
            for tail, expected in (('/2', f(2*x)/2), ('+1', f(2*x)+1),
                                   ('y', y*f(2*x)), ('^2', f(2*x)**2)):
                latex = '\\' + function + '(2x)' + tail
                with self.subTest(latex=latex):
                    self.assert_formula(latex, expected)

    def test_explicit_nested_arguments_are_preserved(self):
        x = sp.Symbol('x', real=True)
        for latex, expected in ((r'\sin(\cos x)', sp.sin(sp.cos(x))),
                                (r'\sin(x\cos x)', sp.sin(x*sp.cos(x))),
                                (r'\sin(x+1)', sp.sin(x+1)),
                                (r'\sin\frac{x}{2}', sp.sin(x/2)),
                                (r'\sin(2*x)', sp.sin(2*x)),
                                (r'\sin x^2', sp.sin(x**2)),
                                (r'\sin^2 x', sp.sin(x)**2),
                                (r'\sin^{2}(x)', sp.sin(x)**2)):
            with self.subTest(latex=latex):
                self.assert_formula(latex, expected)

    def test_real_worker_does_not_accept_area_with_lost_factor(self):
        spec = parse_mask(r'{{expression: d^2\sin(2\alpha)/2 | positive: d,\alpha}}',
                          validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        slot = spec.slots[0]
        self.assertEqual(check_slot(slot, r'd^2\sin(\alpha)\cos(\alpha)'), 'ok')
        self.assertEqual(check_slot(slot, r'd^2\sin\alpha'), 'wrong')

    def test_general_expression_parser_uses_same_function_scopes(self):
        x = sp.Symbol('x')
        self.assertEqual(expressions.parse_expr(r'\sin(2x)/2'), sp.sin(2*x)/2)
        self.assertEqual(expressions.parse_expr(r'\sin x\cos x'), sp.sin(x)*sp.cos(x))


class ProductBeforeFunctionTests(SimpleTestCase):
    """После явного умножения (набранного или вставленного подготовкой
    текста) граница аргумента та же, что и без него: \\frac{2}{3}\\sin x\\cos x
    — произведение, как 2\\sin x\\cos x."""

    def assert_formula(self, latex, expected):
        parsed = formulas._parse(latex)
        self.assertIsNotNone(parsed, latex)
        self.assertEqual(sp.simplify(parsed.expression - expected), 0, latex)

    def test_coefficient_before_two_functions(self):
        x, y = sp.symbols('x y', real=True)
        for latex, expected in (
                (r'\frac{2}{3}\sin x\cos x', sp.Rational(2, 3)*sp.sin(x)*sp.cos(x)),
                (r'2\cdot\sin x\cos x', 2*sp.sin(x)*sp.cos(x)),
                (r'2\times\sin x\cos x', 2*sp.sin(x)*sp.cos(x)),
                (r'2\cdot -\sin x\cos x', -2*sp.sin(x)*sp.cos(x)),
                (r'x^2\sin x\cos x', x**2*sp.sin(x)*sp.cos(x)),
                (r'(x+1)\sin x\cos x', (x+1)*sp.sin(x)*sp.cos(x)),
                (r'2\cdot\sin x\cos x+1', 2*sp.sin(x)*sp.cos(x)+1),
                (r'2\cdot\sin x\cos x\cdot\sin y\cos y',
                 2*sp.sin(x)*sp.cos(x)*sp.sin(y)*sp.cos(y)),
                (r'\frac{2\cdot\sin x\cos x}{3}', sp.Rational(2, 3)*sp.sin(x)*sp.cos(x)),
                (r'\sqrt{2}\sin x\sqrt{\sin x}', sp.sqrt(2)*sp.sin(x)**sp.Rational(3, 2)),
                (r'\ln 2\cdot x\ln x', sp.log(2)*x*sp.log(x)),
                (r'\frac{1}{2}\ln x\ln y', sp.log(x)*sp.log(y)/2)):
            with self.subTest(latex=latex):
                self.assert_formula(latex, expected)

    def test_variable_between_coefficient_and_function(self):
        x = sp.Symbol('x', real=True)
        for latex, expected in (
                (r'\frac{1}{3} x \sin 3x', x*sp.sin(3*x)/3),
                (r'\frac{1}{3}x\sin 3x+\frac{1}{9}\cos 3x', x*sp.sin(3*x)/3 + sp.cos(3*x)/9),
                (r'\frac{1}{2}x\cos 2x', x*sp.cos(2*x)/2)):
            with self.subTest(latex=latex):
                self.assert_formula(latex, expected)

    def test_existing_argument_boundaries_do_not_change(self):
        x = sp.Symbol('x', real=True)
        for latex, expected in ((r'\frac{1}{2}\sin 2x', sp.sin(2*x)/2),
                                (r'2\cdot\sin 2x', 2*sp.sin(2*x)),
                                (r'\sin 2\cdot x', sp.sin(2)*x),
                                (r'2\cdot\sin x^2\cos x', 2*sp.sin(x**2)*sp.cos(x)),
                                (r'\sin x\cdot\cos x', sp.sin(x)*sp.cos(x))):
            with self.subTest(latex=latex):
                self.assert_formula(latex, expected)
        self.assertEqual(expressions._group_products(r'a\cdot b c/d+e'), r'a\cdot{ b c}/d+e')
        self.assertEqual(expressions._group_products(r'a\cdot x^-2 y'), r'a\cdot{ x^-2 y}')
        # Модуль группирует _absolute_products, здесь его не трогаем.
        self.assertEqual(expressions._group_products(r'a\cdot |x|\sin x'), r'a\cdot |x|\sin x')

    def test_antiderivative_mask_accepts_product_with_root(self):
        spec = parse_mask(r'{{simplify: \frac{2}{3} \sin ^{\frac{3}{2}} x+C}}',
                          validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        slot = spec.slots[0]
        self.assertEqual(check_slot(slot, r'\frac{2}{3}\sin x\sqrt{\sin x}+C'), 'ok')
        self.assertEqual(check_slot(slot, r'\frac{2}{3}\sqrt{\sin^3 x}+C'), 'ok')
        self.assertEqual(check_slot(slot, r'\frac{1}{3}\sin x\sqrt{\sin x}+C'), 'wrong')
        spec = parse_mask(r'{{expression: \frac{1}{3} x \sin 3x+\frac{1}{9}\cos 3x+C}}',
                          validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        slot = spec.slots[0]
        self.assertEqual(check_slot(slot, r'\frac{x\sin 3x}{3}+\frac{\cos 3x}{9}+C'), 'ok')
        self.assertEqual(check_slot(slot, r'\frac{1}{3}x\sin 3x-\frac{1}{9}\cos 3x+C'), 'wrong')

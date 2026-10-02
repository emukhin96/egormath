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

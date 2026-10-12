"""Граница аргумента логарифма без скобок — как у тригонометрических функций.

Раньше аргумент \\ln поглощал всё справа: 2\\ln 2-1 читалось как
2\\ln(2-1) = 0, \\ln x+C — как \\ln(x+C), x\\ln x-x+C — как x\\ln C, и эталоны
с такими записями получали неверное значение.
"""
import sympy as sp
from django.test import SimpleTestCase

from .checks import formulas
from .checks.mask import check_slot, parse_mask


class LogScopeTests(SimpleTestCase):
    def setUp(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def tearDown(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def assert_formula(self, latex, expected):
        parsed = formulas._parse(latex)
        self.assertIsNotNone(parsed, latex)
        self.assertEqual(sp.simplify(parsed.expression - expected), 0, latex)

    def test_operation_after_bare_argument_stays_outside(self):
        x, y, C = sp.symbols('x y C', real=True)
        ln = sp.log
        for latex, expected in (
                (r'\ln x-1', ln(x) - 1), (r'\ln x+C', ln(x) + C),
                (r'2\ln 2-1', 2*ln(2) - 1), (r'2(\ln 2-1)', 2*ln(2) - 2),
                (r'x\ln x-x+C', x*ln(x) - x + C), (r'\ln(x+1)-1', ln(x + 1) - 1),
                (r'\ln x/2', ln(x)/2), (r'\ln x\cdot y', y*ln(x)),
                (r'\ln x+\ln y', ln(x) + ln(y)), (r'2\ln x\ln y', 2*ln(x)*ln(y)),
                (r'\ln x\sin x', ln(x)*sp.sin(x)), (r'\ln\cos x+1', ln(sp.cos(x)) + 1),
                (r'\log_2 x+1', ln(x)/ln(2) + 1), (r'\ln|x|+C', ln(sp.Abs(x)) + C),
                (r'\frac{\ln x-1}{\ln^2 x}', (ln(x) - 1)/ln(x)**2)):
            with self.subTest(latex=latex):
                self.assert_formula(latex, expected)

    def test_argument_written_together_keeps_its_meaning(self):
        x = sp.Symbol('x', real=True)
        ln = sp.log
        for latex, expected in ((r'\ln 2x', ln(2*x)), (r'\ln 2x-1', ln(2*x) - 1),
                                (r'\ln x^2', ln(x**2)), (r'\ln(x)^2', ln(x**2)),
                                (r'\ln\left(1+e^{x}\right)^{2}', ln((1 + sp.Symbol('e', real=True)**x)**2)),
                                (r'(\ln x)^2', ln(x)**2), (r'\ln^{2} x', ln(x)**2),
                                (r'\ln\ln x', ln(ln(x)))):
            with self.subTest(latex=latex):
                self.assert_formula(latex, expected)

    def test_function_after_power_is_a_factor(self):
        x = sp.Symbol('x', real=True)
        e = sp.Symbol('e', real=True)
        for latex, expected in ((r'2^{x}\ln 2', 2**x*sp.log(2)),
                                (r'1+\ln x+2^{x} \ln 2', 1 + sp.log(x) + 2**x*sp.log(2)),
                                (r'e^{x}\ln x+\frac{e^{x}}{x}', e**x*sp.log(x) + e**x/x),
                                (r'x^2\ln x', x**2*sp.log(x))):
            with self.subTest(latex=latex):
                self.assert_formula(latex, expected)

    def test_masks_with_logarithm_accept_book_answers(self):
        # Эталон 2\ln 2-1 раньше был нулём: верный ответ получал «неверно».
        number = parse_mask(r'{{number: 2 \ln 2-1}}', validate_references=True).slots[0]
        self.assertEqual(check_slot(number, r'2\ln 2-1'), 'ok')
        self.assertEqual(check_slot(number, r'-1+2\ln 2'), 'ok')
        self.assertEqual(check_slot(number, '0'), 'wrong')
        spec = parse_mask(r'{{expression: x\ln x-x+C}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        slot = spec.slots[0]
        self.assertEqual(check_slot(slot, r'C+x\ln x-x'), 'ok')
        self.assertEqual(check_slot(slot, r'x\ln C'), 'wrong')
        spec = parse_mask(r'{{simplify: 2^{\frac{x}{\ln x}} \cdot \ln 2 \cdot '
                          r'\frac{(\ln x)-1}{(\ln x)^{2}}}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual(check_slot(spec.slots[0], r'2^{\frac{x}{\ln x}} \cdot \ln 2 \cdot '
                                                   r'\frac{\ln x-1}{\ln ^{2} x}'), 'ok')

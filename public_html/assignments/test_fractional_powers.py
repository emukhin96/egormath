"""Дробные степени и корни n-й степени: одна величина в разных записях.

Показатель с нечётным знаменателем — школьный вещественный корень:
x^{2/3} = ∛(x²) = (∛x)² при любом действительном x. С чётным знаменателем
записи сравниваются на области эталона, где основание неотрицательно.
Случаи взяты из задачника Шабунина (II.44, II.61, II.62, XIII.14, XIII.33,
XIV.92, XV.2, XV.15).
"""
import sympy as sp
from django.test import SimpleTestCase

from .checks import expressions, formulas
from .checks.mask import check_slot, parse_mask


class FractionalPowerTests(SimpleTestCase):
    def setUp(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def tearDown(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, payload, kind='expression'):
        spec = parse_mask('{{' + kind + ': ' + payload + '}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def assertVerdicts(self, slot, verdicts):
        for value, expected in verdicts:
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), expected)

    def test_odd_denominator_equals_odd_root(self):
        slot = self.slot(r'\sqrt[3]{x^{2}}', 'simplify')
        self.assertVerdicts(slot, (
            (r'x^{\frac{2}{3}}', 'ok'), (r'x^{2/3}', 'ok'),
            (r'\sqrt[3]{x}^{2}', 'ok'), (r'\sqrt[3]{x^{2}}', 'ok'),
            (r'x^{\frac{1}{3}}', 'wrong'), (r'-x^{\frac{2}{3}}', 'wrong')))
        slot = self.slot(r'\sqrt[5]{x^{16}}', 'simplify')
        self.assertVerdicts(slot, (
            (r'x^{\frac{16}{5}}', 'ok'), (r'\sqrt[5]{x}^{16}', 'ok'),
            (r'-\sqrt[5]{x^{16}}', 'wrong'), (r'\sqrt[5]{x^{15}}', 'wrong')))

    def test_negative_odd_power_is_reciprocal_root(self):
        slot = self.slot(r'\frac{2}{3 \sqrt[3]{\left(2 x_{0}+3\right)^{2}}}')
        self.assertVerdicts(slot, (
            (r'\frac{2}{3}(2x_0+3)^{-\frac{2}{3}}', 'ok'),
            (r'\frac{2}{3\sqrt[3]{2x_0+3}^2}', 'ok'),
            (r'\frac{2}{3(2x_0+3)^{2/3}}', 'ok'),
            (r'\frac{2\sqrt[3]{2x_0+3}}{3(2x_0+3)}', 'ok'),
            (r'\frac{2}{3}(2x_0+3)^{-\frac{1}{3}}', 'wrong'),
            (r'\frac{1}{3\sqrt[3]{(2x_0+3)^2}}', 'wrong')))
        slot = self.slot(r'\frac{1}{3 \sqrt[3]{x_{0}^{2}}}')
        self.assertVerdicts(slot, (
            (r'\frac{1}{3}x_{0}^{-\frac{2}{3}}', 'ok'),
            (r'\frac{1}{3x_0^{2/3}}', 'ok'),
            (r'\frac{\sqrt[3]{x_0}}{3x_0}', 'ok'),
            (r'\frac{1}{3}x_{0}^{-\frac{1}{3}}', 'wrong'),
            (r'\frac{1}{3}x_{0}^{\frac{2}{3}}', 'wrong')))
        slot = self.slot(r'e^{-\frac{1}{3}}', 'simplify')
        self.assertEqual(check_slot(slot, r'\frac{1}{\sqrt[3]{e}}'), 'ok')

    def test_powers_combine_with_odd_roots(self):
        self.assertVerdicts(self.slot(r'x^{\frac{5}{3}}'), (
            (r'x\sqrt[3]{x^2}', 'ok'), (r'\sqrt[3]{x^5}', 'ok'),
            (r'|x|\sqrt[3]{x^2}', 'wrong')))
        self.assertVerdicts(self.slot(r'x^{-\frac{2}{3}}'), (
            (r'\sqrt[3]{x^{-2}}', 'ok'), (r'\frac{1}{\sqrt[3]{x^2}}', 'ok')))
        slot = self.slot(r'\frac{3}{5} x^{\frac{5}{3}}-3 x^{\frac{4}{3}}+4 x+C', 'simplify')
        self.assertVerdicts(slot, (
            (r'\frac{3}{5}\sqrt[3]{x^5}-3\sqrt[3]{x^4}+4x+C', 'ok'),
            (r'\frac{3}{5}x^{\frac{5}{3}}+3x^{\frac{4}{3}}+4x+C', 'wrong')))

    def test_root_of_product_is_product_of_roots(self):
        slot = self.slot(r'\sqrt[3]{a b}', 'simplify')
        self.assertVerdicts(slot, (
            (r'\sqrt[3]{a}\sqrt[3]{b}', 'ok'), (r'a^{\frac{1}{3}}b^{\frac{1}{3}}', 'ok'),
            (r'\sqrt[3]{a}b', 'wrong')))
        slot = self.slot(r'\sqrt[3]{a b}-\sqrt[3]{2 b^{2}}', 'simplify')
        self.assertVerdicts(slot, (
            (r'\sqrt[3]{ab}-\sqrt[3]{2}b^{\frac{2}{3}}', 'ok'),
            (r'\sqrt[3]{ab}-\sqrt[3]{2b}', 'wrong')))
        slot = self.slot(r'x^{\frac{2}{3}}y^{\frac{1}{3}}')
        self.assertVerdicts(slot, (
            (r'\sqrt[3]{x^2y}', 'ok'), (r'-\sqrt[3]{x}^2\sqrt[3]{y}', 'wrong')))

    def test_new_hole_at_zero_is_still_wrong(self):
        self.assertVerdicts(self.slot(r'\sqrt[3]{x^{2}}'), (
            (r'x^{\frac{2}{3}}+0\cdot\frac{1}{x}', 'wrong'),
            (r'\frac{x^{\frac{4}{3}}}{x^{\frac{2}{3}}}', 'wrong')))
        self.assertEqual(check_slot(self.slot(r'\sqrt{x}'), r'\frac{x}{\sqrt{x}}'), 'wrong')

    def test_even_denominator_on_nonnegative_base(self):
        self.assertVerdicts(self.slot(r'\sqrt[4]{x^{5}}', 'simplify'), (
            (r'x^{\frac{5}{4}}', 'ok'), (r'-x^{\frac{5}{4}}', 'wrong')))
        self.assertVerdicts(self.slot(r'-\sqrt[4]{(2-x)^{5}}', 'simplify'), (
            (r'-(2-x)^{\frac{5}{4}}', 'ok'), (r'\sqrt[4]{(2-x)^{5}}', 'wrong')))
        self.assertVerdicts(self.slot(r'\sqrt{x}'), (
            (r'x^{\frac{1}{2}}', 'ok'), (r'-\sqrt{x}', 'wrong')))
        slot = self.slot(r'\frac{3}{\sqrt[4]{x}}+\frac{2}{\sqrt[3]{x}}'
                         r'+\frac{2}{\sqrt[3]{x^{5}}}+\frac{3}{\sqrt[4]{x^{7}}}', 'simplify')
        self.assertEqual(check_slot(slot, r'3x^{-\frac{1}{4}}+2x^{-\frac{1}{3}}'
                                          r'+2x^{-\frac{5}{3}}+3x^{-\frac{7}{4}}'), 'ok')
        slot = self.slot(r'\frac{14}{3} x^{\frac{3}{2}}+\frac{4}{5} x^{\frac{5}{4}}+C')
        self.assertEqual(check_slot(slot, r'\frac{14}{3}\sqrt{x^3}'
                                          r'+\frac{4}{5}\sqrt[4]{x^5}+C'), 'ok')

    def test_mixed_even_and_odd_roots_reference_is_valid(self):
        slot = self.slot(r'\frac{1}{3 \sqrt[3]{x^{2}}}-\frac{2}{\sqrt[3]{x^{5}}}'
                         r'-\frac{5}{2 \sqrt{x}}+\frac{\sqrt{2}}{x^{2}}', 'simplify')
        self.assertVerdicts(slot, (
            (r'\frac{1}{3}x^{-\frac{2}{3}}-2x^{-\frac{5}{3}}-\frac{5}{2}x^{-\frac{1}{2}}'
             r'+\sqrt{2}x^{-2}', 'ok'),
            (r'\frac{1}{3}x^{-\frac{2}{3}}-2x^{-\frac{5}{3}}+\frac{5}{2}x^{-\frac{1}{2}}'
             r'+\sqrt{2}x^{-2}', 'wrong')))

    def test_even_denominator_keeps_its_domain(self):
        # Чётный корень не определён при x < 0: другая область — неверно.
        self.assertEqual(check_slot(self.slot(r'\sqrt[4]{x^{2}}'), r'\sqrt{x}'), 'wrong')
        self.assertEqual(check_slot(self.slot(r'\sqrt[3]{x}'), r'\sqrt[6]{x^{2}}'), 'wrong')
        self.assertEqual(check_slot(self.slot('x'), r'(x^{\frac{1}{2}})^2'), 'wrong')
        self.assertEqual(check_slot(self.slot(r'\sqrt{x^{2}}'), 'x'), 'wrong')
        self.assertEqual(check_slot(self.slot(r'x^{\frac{2}{3}}'), r'\sqrt[6]{x^{4}}'), 'ok')

    def test_numeric_odd_root_is_already_simplest(self):
        slot = self.slot(r'\sqrt[3]{4 V}', 'simplify')
        self.assertVerdicts(slot, (
            (r'\sqrt[3]{4}\sqrt[3]{V}', 'ok'), (r'\sqrt[3]{4}V^{\frac{1}{3}}', 'ok'),
            (r'\sqrt[3]{2V}', 'wrong')))
        for reference, value in ((r'\sqrt[3]{4}', r'\sqrt[3]{4}'),
                                 (r'\sqrt[4]{12}', r'\sqrt[4]{12}'),
                                 (r'-\sqrt[3]{4}', r'\sqrt[3]{-4}')):
            with self.subTest(value=value):
                self.assertEqual(check_slot(self.slot(reference, 'simplify'), value), 'ok')
        # Множитель выносится или показатель понижается — не упрощено.
        for reference, value in ((r'2\sqrt[3]{2}', r'\sqrt[3]{16}'),
                                 (r'\sqrt{2}', r'\sqrt[4]{4}'),
                                 (r'\sqrt{2}', r'\sqrt[6]{8}')):
            with self.subTest(value=value):
                self.assertEqual(check_slot(self.slot(reference, 'simplify'), value), 'wrong')


class FunctionPowerTests(SimpleTestCase):
    """Степень функции: \\sin^{2/3}x, \\tan^2 x, \\ln^2 x — та же величина,
    что (\\sin x)^{2/3}, (\\tan x)^2, (\\ln x)^2."""

    def setUp(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def tearDown(self):
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def check(self, reference, value, kind='expression'):
        spec = parse_mask('{{' + kind + ': ' + reference + '}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return check_slot(spec.slots[0], value)

    def test_odd_power_of_trigonometric_function_is_real_root(self):
        for value, expected in ((r'\sqrt[3]{\sin^2 x}', 'ok'), (r'(\sin x)^{\frac{2}{3}}', 'ok'),
                                (r'\sqrt[3]{\sin x}^{2}', 'ok'),
                                (r'-\sqrt[3]{\sin^2 x}', 'wrong'),
                                (r'\sin^{\frac{1}{3}} x', 'wrong')):
            with self.subTest(value=value):
                self.assertEqual(self.check(r'\sin^{\frac{2}{3}} x', value), expected)
        self.assertEqual(self.check(r'\sqrt[3]{\sin^2 x}', r'\sin^{\frac{2}{3}} x'), 'ok')
        self.assertEqual(self.check(r'\frac{1}{\sqrt[3]{\cos x}}', r'\cos^{-\frac{1}{3}} x'), 'ok')
        self.assertEqual(self.check(r'\sqrt[3]{\tan x}', r'\tan^{\frac{1}{3}} x'), 'ok')
        self.assertEqual(self.check(r'\arcsin x', r'\sin^{-1} x'), 'ok')

    def test_even_power_of_trigonometric_function_keeps_domain(self):
        self.assertEqual(self.check(r'\cos^{\frac{3}{2}} x', r'\sqrt{\cos^3 x}'), 'ok')
        self.assertEqual(self.check(r'\cos^{\frac{3}{2}} x', r'\cos x\sqrt{\cos x}'), 'ok')
        self.assertEqual(self.check(r'\cos^{\frac{3}{2}} x', r'-\sqrt{\cos^3 x}'), 'wrong')
        self.assertEqual(self.check(r'\sqrt{\sin x}', r'\sin^{\frac{1}{2}} x'), 'ok')

    def test_power_of_function_requires_the_function_itself(self):
        # Раньше \tan x не входил в область \tan^2 x: перебор до таймаута.
        self.assertEqual(self.check(r'\tan^{2} x', r'(\tan x)^{2}'), 'ok')
        self.assertEqual(self.check(r'\tan^{2} x', r'\frac{\sin^2 x}{\cos^2 x}'), 'ok')
        self.assertEqual(self.check(r'\cot^{2} x', r'\frac{\cos^2 x}{\sin^2 x}'), 'ok')
        self.assertEqual(self.check(r'\tan^{2} x',
                                    r'\frac{\sin^2 x}{\cos^2 x}+0\cdot\frac{1}{\sin x}'), 'wrong')
        # \tan^{-1} x — арктангенс: область tan x к нему не относится.
        self.assertEqual(self.check(r'\arctan x', r'\tan^{-1} x'), 'ok')
        self.assertEqual(self.check(r'\tan^{-1} x', r'\arctan x'), 'ok')

    def test_power_of_logarithm(self):
        for reference, value, expected in (
                (r'(\ln x)^{2}', r'\ln^{2} x', 'ok'), (r'(\ln x)^{2}', r'\ln^2 x', 'ok'),
                (r'\ln^{4} x', r'(\ln x)^4', 'ok'),
                (r'(\ln x)^{2}+1', r'\ln^{2}x+1', 'ok'),
                (r'(\ln(x+1))^{2}', r'\ln^{2}(x+1)', 'ok'),
                (r'\frac{1}{3}(\ln x)^{3}+C', r'\frac{1}{3}\ln^{3}x+C', 'ok'),
                (r'(\ln x)^{\frac{1}{3}}', r'\sqrt[3]{\ln x}', 'ok'),
                (r'(\ln x)^{2}', r'\ln x^{2}', 'wrong')):
            with self.subTest(value=value):
                self.assertEqual(self.check(reference, value), expected)
        number = parse_mask(r'{{number: (\ln 3)^{2}}}', validate_references=True).slots[0]
        self.assertEqual(check_slot(number, r'\ln^{2} 3'), 'ok')
        self.assertEqual(check_slot(number, r'\ln^{2} 9'), 'wrong')

    def test_power_of_logarithm_inside_another_function(self):
        # Без внешней группы \sin(\ln x)^2 читался бы как sin²(ln x).
        x = sp.Symbol('x', real=True)
        for latex, expected in ((r'\sin\ln^2 x', sp.sin(sp.log(x)**2)),
                                (r'\cos\ln^{2} x+1', sp.cos(sp.log(x)**2) + 1),
                                (r'\sqrt{\ln^2 x}', sp.sqrt(sp.log(x)**2))):
            with self.subTest(latex=latex):
                parsed = formulas._parse(latex)
                self.assertIsNotNone(parsed, latex)
                self.assertEqual(sp.simplify(parsed.expression - expected), 0, latex)

    def test_ambiguous_logarithm_argument_is_not_guessed(self):
        # ln²(2x) или (ln² 2)·x — граница аргумента неоднозначна.
        self.assertEqual(expressions.function_powers(r'\ln^2 2x'), r'\ln^2 2x')
        self.assertEqual(expressions.function_powers(r'\ln^{2} x+1'), r'{(\ln x)^{2}}+1')
        self.assertEqual(expressions.function_powers(r'\ln^{-1} x'), r'\ln^{-1} x')

"""Требование к виду записи в ``simplify`` и ``factor``.

Проверки идут через ``formulas._check`` в текущем процессе — тот же код,
что исполняет вычислитель; запуск дочернего процесса здесь не нужен.
"""
from django.test import SimpleTestCase

from .check_answer import OK, UNKNOWN, WRONG
from .checks import expressions, formulas


def check(reference, value, mode='simplify'):
    parsed, _ = formulas._parse_reference(reference)
    return formulas._check(value, parsed, mode=mode)


class SimplifyRadicalTests(SimpleTestCase):
    def test_number_times_irreducible_root_is_simplest_form(self):
        for reference, value in (
                ('2\\sqrt{2}', '2\\sqrt{2}'), ('2\\sqrt{2}', '2\\sqrt2'),
                ('2\\sqrt{2}', '\\sqrt{2}\\cdot2'), ('2\\sqrt[3]{2}', '2\\sqrt[3]{2}'),
                ('2\\sqrt[3]{2}', '2\\cdot 2^{1/3}'), ('3\\sqrt[4]{2}', '3\\sqrt[4]{2}'),
                ('1+\\sqrt{2}', '\\sqrt{2}+1'), ('-\\sqrt[3]{2}', '\\sqrt[3]{-2}'),
                ('\\frac{\\sqrt{2}}{2}', '\\frac{1}{\\sqrt{2}}')):
            with self.subTest(reference=reference, value=value):
                self.assertEqual(check(reference, value), OK)

    def test_root_with_extractable_factor_is_not_simplified(self):
        for reference, value in (
                ('2\\sqrt{2}', '\\sqrt{8}'), ('2\\sqrt{2}', 'sqrt(8)'),
                ('2\\sqrt{3}', '\\sqrt{12}'), ('2\\sqrt{3}', '\\sqrt{4}\\sqrt{3}'),
                ('2\\sqrt{3}', '\\sqrt{2}\\sqrt{6}'), ('2\\sqrt[3]{2}', '\\sqrt[3]{16}'),
                ('2\\sqrt[3]{2}', '4\\sqrt[3]{1/4}'), ('2\\sqrt[3]{2}', '2^{4/3}'),
                ('5\\sqrt[3]{2}', '\\sqrt[3]{250}'), ('3\\sqrt[4]{2}', '\\sqrt[4]{162}'),
                ('\\frac{\\sqrt{2}}{2}', '\\sqrt{1/2}'), ('1+\\sqrt{2}', '1+\\sqrt{8}/2'),
                ('1+\\sqrt{2}', '3-2+\\sqrt2'), ('2\\sqrt{Rr}', '\\sqrt{4Rr}')):
            with self.subTest(reference=reference, value=value):
                self.assertEqual(check(reference, value), WRONG)

    def test_prepared_textbook_masks_no_longer_need_radicand_workaround(self):
        # Мерзляк-9 алгебра: вынесите множитель из-под знака корня.
        self.assertEqual(check('2\\sqrt[3]{2}', '\\sqrt[3]{16}'), WRONG)
        self.assertEqual(check('2\\sqrt[3]{2}', '2\\sqrt[3]2'), OK)
        self.assertEqual(check('2\\sqrt{3}', '2.52'), WRONG)


class SimplifyLikeTermsTests(SimpleTestCase):
    def test_like_terms_after_subtracting_bare_symbol(self):
        for value in ('13-x-2x', '13-2x-x', '-x-2x+13', '13-(x+2x)', '26/2-3x'):
            with self.subTest(value=value):
                self.assertEqual(check('13-3x', value), WRONG)
        for value in ('13-3x', '-3x+13', '-(3x-13)', '13-3*x'):
            with self.subTest(value=value):
                self.assertEqual(check('13-3x', value), OK)

    def test_unary_minus_detection_counts_symbol_tokens(self):
        tree = expressions.resolve(expressions.raw_tree('13-x'))
        inner = [c for c in tree.children if expressions._is_tree(c)][0]
        self.assertFalse(expressions._is_unary_minus(inner))
        tree = expressions.resolve(expressions.raw_tree('-x'))
        inner = [c for c in tree.children if expressions._is_tree(c)][0]
        self.assertTrue(expressions._is_unary_minus(inner))
        self.assertEqual(expressions._number_value(
            expressions.resolve(expressions.raw_tree('-3'))), -3)

    def test_classic_cases_still_hold(self):
        for value in ('2x+3x', 'x+4x', '10x/2', '5x+0', '7x-2x', '\\frac{5x}{1}'):
            with self.subTest(value=value):
                self.assertEqual(check('5x', value), WRONG)
        for value in ('5x', 'x\\cdot5', '5\\cdot x'):
            with self.subTest(value=value):
                self.assertEqual(check('5x', value), OK)


class SimplifyExpansionTests(SimpleTestCase):
    def test_unexpanded_original_is_rejected(self):
        self.assertEqual(check('b^{4/5}+9', '(b^{0,4}+3)^2-6b^{0,4}'), WRONG)
        self.assertEqual(check('b^{4/5}+9', 'b^{0,8}+6+3'), WRONG)
        self.assertEqual(check('x', 'x(x+1)-x^2'), WRONG)
        self.assertEqual(check('x^2-1', '(x-1)(x+1)'), WRONG)
        self.assertEqual(check('\\sqrt{a-3}+1', '\\sqrt{a-3}+2-1'), WRONG)

    def test_equivalent_compact_forms_are_accepted(self):
        self.assertEqual(check('b^{4/5}+9', '9+b^{0,8}'), OK)
        self.assertEqual(check('b^{4/5}+9 | positive: b', '\\sqrt[5]{b^4}+9'), OK)
        self.assertEqual(check('\\frac{a \\sqrt{3}(a-2 b)}{12}',
                               '\\frac{\\sqrt{3}a^2-2ab\\sqrt{3}}{12}'), OK)
        self.assertEqual(check('\\frac{a \\sqrt{3}(a-2 b)}{12}',
                               '\\frac{a(a-2b)}{4\\sqrt{3}}'), OK)
        self.assertEqual(check('-x/2-1/(2x)', '-\\frac{x^2+1}{2x}'), OK)
        self.assertEqual(check('2\\left(R^{2}+r^{2}\\right)', '2R^2+2r^2'), OK)
        self.assertEqual(check('2 \\sqrt{R r} | positive: R,r', '2\\sqrt{R}\\sqrt{r}'), OK)

    def test_much_longer_or_nested_forms_are_not_accepted(self):
        self.assertEqual(check('2\\left(R^{2}+r^{2}\\right)', 'R^2+r^2+R^2+r^2'), WRONG)
        self.assertIn(check('\\sqrt{a-3}+1', '\\sqrt{a-2+2\\sqrt{a-3}}'), (WRONG, UNKNOWN))

    def test_plain_drops_real_root_piecewise(self):
        expr = expressions.parse_expr('b^{0,4}')
        self.assertTrue(expr.has(*expr.atoms()) and 'Piecewise' in str(expr))
        self.assertEqual(str(expressions._plain(expr)), 'b**(2/5)')


class FactorTests(SimpleTestCase):
    REFERENCE = ('(m^{1/5}-2n^{3/5})((m^{1/5})^{2}+(m^{1/5})(2n^{3/5})+(2n^{3/5})^{2})')

    def test_difference_of_cubes_with_fractional_exponents(self):
        self.assertEqual(check(self.REFERENCE, self.REFERENCE, 'factor'), OK)
        self.assertEqual(check(
            self.REFERENCE, '(m^{1/5}-2n^{3/5})(m^{2/5}+2m^{1/5}n^{3/5}+4n^{6/5})', 'factor'), OK)
        self.assertEqual(check(self.REFERENCE, 'm^{3/5}-8n^{9/5}', 'factor'), WRONG)

    def test_factor_count_guards_extensions_factor_list_cannot_split(self):
        reference = ('(x^{2/7}-\\sqrt[3]{6})((x^{2/7})^{2}+(x^{2/7})(\\sqrt[3]{6})'
                     '+(\\sqrt[3]{6})^{2})')
        self.assertEqual(check(reference, reference, 'factor'), OK)
        self.assertEqual(check(reference, 'x^{6/7}-6', 'factor'), WRONG)

    def test_polynomial_cases_still_hold(self):
        for value, expected in (('2(x-1)(x+1)', OK), ('(x+1)(x-1)2', OK),
                                ('-2(1-x)(x+1)', OK), ('(2x-2)(x+1)', WRONG),
                                ('2x^2-2', WRONG), ('2(x^2-1)', WRONG)):
            with self.subTest(value=value):
                self.assertEqual(check('2(x-1)(x+1)', value, 'factor'), expected)

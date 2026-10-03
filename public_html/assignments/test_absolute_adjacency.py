"""Модуль как коэффициент и запрет лишних элементов одиночного ответа."""
from django.test import SimpleTestCase
from .checks.mask import check_slot, parse_mask
from .checks import formulas, expressions


class AbsoluteAdjacencyTests(SimpleTestCase):
    def slot(self, payload, kind='expression'):
        spec = parse_mask('{{'+kind+': '+payload+'}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_accepts_absolute_coefficient_in_geometry_18_13(self):
        for context in (' | positive: a,b', ' | positive: a,b | domain: a<2b'):
            slot = self.slot('ab/(a+b)'+context)
            for value in ('|a|b/(a+b)', '|a| b/(a+b)', r'\left|a\right|b/(a+b)',
                          '|a|(b)/(a+b)', '|a|sqrt(b^2)/(a+b)',
                          '|a|'+r'\frac{b}{a+b}'):
                with self.subTest(context=context, value=value):
                    self.assertEqual(check_slot(slot, value), 'ok')

    def test_preserves_sign_scope_and_original_holes(self):
        slot = self.slot('ab/(a+b) | positive: a,b | domain: a<2b')
        for value in ('|a|b/(a+b)+1', '|a|b/(a+b)+0/(a-b)',
                      '|a|b/(a+b)+0*sqrt(a-2b)', '|a|z/(a+b)',
                      '|a|b/(a+b)*(2a-3b)/(2a-3b)'):
            self.assertEqual(check_slot(slot, value), 'wrong')
        unrestricted = self.slot('ab/(a+b)')
        # Без положительности a модуль нельзя удалить. Общая область
        # рационального эталона пока неопределённа; ложного OK быть не должно.
        self.assertEqual(check_slot(unrestricted, '|a|b/(a+b)'), 'unknown')
        raw = formulas._parse('|a|b/(a+b)')
        names = {str(s): s for s in raw.expression.free_symbols}
        self.assertEqual(raw.expression.subs({names['a']: -2, names['b']: 3}), 6)
        # Деление не захватывает следующий множитель в знаменатель.
        slot = self.slot('2a')
        self.assertEqual(check_slot(slot, '2/|a|a^2'), 'wrong')
        self.assertEqual(expressions.parse_expr('2/|a|a'),
                         expressions.parse_expr('2/|a|*a'))

    def test_valid_absolute_trees_and_function_arguments_do_not_change(self):
        for value, explicit in (('a|b|', 'a*|b|'), ('|a||b|', '|a|*|b|'),
                                (r'\sin |a|b', r'\sin(|a|)*b')):
            expected = expressions.parse_expr(explicit)
            self.assertIsNotNone(expected)
            self.assertEqual(expressions.parse_expr(value), expected)
        # Неугадываемый синтаксис остаётся неопределённым.
        slot = self.slot('ab/(a+b) | positive: a,b')
        self.assertEqual(check_slot(slot, '|a b/(a+b)'), 'unknown')

    def test_single_expression_rejects_extra_list_without_affecting_lists(self):
        for kind, payload in (('expression', 'ab/(a+b) | positive: a,b | domain: a<2b'),
                              ('simplify', 'x+1'), ('factor', '(x-1)(x+1)')):
            slot = self.slot(payload, kind)
            for value in ('ab/(a+b);1', 'x+1;', ';x+1', 'x+1;x+1'):
                self.assertEqual(check_slot(slot, value), 'wrong')
        slot = self.slot('x;x+1', 'expressions')
        self.assertEqual(check_slot(slot, 'x+1;x'), 'ok')
        self.assertEqual(check_slot(slot, 'x;x+1;1'), 'wrong')
        self.assertEqual(check_slot(slot, ''), '')

    def test_latex_spacing_is_not_an_extra_list_element(self):
        cases = (('expression', 'x+1', r'x\;+\;1'),
                 ('simplify', 'x+1', r'x\;+\;1'),
                 ('factor', '(x-1)(x+1)', r'(x\;-1)(x\;+1)'),
                 ('expression', 'ab/(a+b) | positive: a,b | domain: a<2b',
                  r'\frac{ab}{a\;+\;b}'))
        for kind, payload, value in cases:
            slot = self.slot(payload, kind)
            with self.subTest(kind=kind, value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
                self.assertEqual(check_slot(slot, value+';0'), 'wrong')
        slot = self.slot('x+1')
        for spacing in (r'\;', r'\,', r'\:', r'\!', r'\ '):
            self.assertEqual(check_slot(slot, 'x'+spacing+'+'+spacing+'1'), 'ok')
            self.assertEqual(check_slot(slot, 'x'+spacing+'+'+spacing+'2'), 'wrong')
        slot = self.slot('ab/(a+b) | positive: a,b | domain: a<2b')
        self.assertEqual(check_slot(slot, r'ab/(a\;+b)+0/(a\;-b)'), 'wrong')

    def test_latex_spacing_preserves_list_count_reference_and_order(self):
        payload = r'x\;+1;x'
        slot = self.slot(payload, 'expressions')
        self.assertEqual(slot.reference, payload)
        for value in (r'x;x\;+1', r'x\;+1;x', r'x\,+1;x'):
            self.assertEqual(check_slot(slot, value), 'ok')
        for value in (r'x;x\;+1;2', r'x\;+1;', r'x\;+1;x;x', r'x;x\;+2'):
            self.assertEqual(check_slot(slot, value), 'wrong')

    def test_numeric_coefficient_after_absolute_factor(self):
        slot = self.slot('2ab/(a+b) | positive: a,b | domain: a<2b')
        for value in ('|a|2b/(a+b)', '|a| 2 b/(a+b)',
                      '|a|2(b)/(a+b)', r'\left|a\right|2b/(a+b)',
                      r'|a|2\frac{b}{a+b}'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in ('|a|3b/(a+b)', '|a|2b/(a+b)+0/(a-b)',
                      '|a|2b/(a+b)+0*sqrt(a-2b)', '|a|2z/(a+b)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)
        # Минус после модуля остаётся вычитанием, а не коэффициентом.
        expected = expressions.parse_expr('|a|-2*b')
        self.assertIsNotNone(expected)
        self.assertEqual(expressions.parse_expr('|a|-2b'), expected)

    def test_nested_absolute_products_keep_structure_and_domain(self):
        slot = self.slot('ab/(a+b) | positive: a,b | domain: a<2b')
        for value in ('||a||b/(a+b)', '| |a| | b/(a+b)',
                      r'\left|\left|a\right|\right|b/(a+b)',
                      '|||a|||b/(a+b)', '|-|a||b/(a+b)'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in ('||a||b/(a+b)+1', '||a||b/(a+b)+0/(a-b)',
                      '||a||b/(a+b)+0*sqrt(a-2b)', '||a||z/(a+b)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)
        raw = formulas._parse('||a||b/(a+b)')
        self.assertIsNotNone(raw)
        def count_abs(tree):
            return (int(str(tree.data) == 'abs')
                    + sum(count_abs(c) for c in tree.children if expressions._is_tree(c)))
        self.assertEqual(count_abs(raw.tree), 2)
        names = {str(s): s for s in raw.expression.free_symbols}
        self.assertEqual(raw.expression.subs({names['a']: -2, names['b']: 3}), 6)
        self.assertEqual(check_slot(slot, '| |a|b/(a+b)'), 'unknown')
        combined = self.slot('2ab/(a+b) | positive: a,b | domain: a<2b')
        for value in ('||a||2b/(a+b)', '|a|2|b|/(a+b)',
                      '(|a|b+|b|a)/(a+b)'):
            self.assertEqual(check_slot(combined, value), 'ok', value)

    def test_numeric_absolute_products_keep_original_invalid_actions(self):
        slot = self.slot('16', kind='number')
        for value in ('|8|2', '||8||2', '|4|2(2)'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in ('||8||2+0*0^0', '|8|2+0/0', '|8|2+0sqrt(-1)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_latex_operators_after_nested_absolute_are_not_factors(self):
        slot = self.slot('a/b | positive: a,b')
        for value in (r'||a||\div b', r'|||a|||\div b'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'||a||\div b+1', r'||a||\div 0'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)
        half = self.slot('a/(2b) | positive: a,b')
        self.assertEqual(check_slot(half, r'||a||\div(||b||2)'), 'ok')
        doubled = self.slot('2a/b | positive: a,b')
        self.assertEqual(check_slot(doubled, r'||a||\div |b|2'), 'ok')
        self.assertEqual(check_slot(half, r'||a||\div |b|2'), 'wrong')
        product = self.slot('ab | positive: a,b')
        for command in (r'\cdot', r'\times'):
            self.assertEqual(check_slot(product, '||a||'+command+' b'), 'ok')
        # ±/∓ — операторы, не множители; одиночный слот не выбирает
        # одну из двух альтернатив, но нормализация не портит запись.
        for command in (r'\div', r'\pm', r'\mp', r'\cdot', r'\times'):
            normalized = expressions._absolute_products('||a||'+command+' b')
            self.assertEqual(normalized, '|(|(a)|)|'+command+' b')
        self.assertEqual(expressions._absolute_products(r'||a|\pm 1|'),
                         r'|(|(a)|\pm 1)|')

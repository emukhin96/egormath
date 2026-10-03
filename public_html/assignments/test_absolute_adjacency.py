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

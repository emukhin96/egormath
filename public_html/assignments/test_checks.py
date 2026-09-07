"""Тесты ядра масок ответа: грамматика, слоты, проверки по типам."""
from django.test import SimpleTestCase

from .check_answer import OK, UNKNOWN, WRONG, check_answer
from .checks import (Slot, check_mask, check_slot, filled_text, parse_mask,
                     reference_text)
from .checks import expressions, sets


def slot(mask_text):
    spec = parse_mask(mask_text)
    assert spec.is_valid, spec.errors
    return spec.slots[0]


class MaskGrammarTests(SimpleTestCase):
    def test_text_and_slots(self):
        spec = parse_mask(
            'Меньшая сторона равна {{number: 10}} см, большая — '
            '{{number: 30}} см, площадь {{number: 300}} см^2.')
        self.assertTrue(spec.is_valid)
        self.assertEqual(len(spec.slots), 3)
        self.assertEqual([s.name for s in spec.slots], ['s1', 's2', 's3'])
        self.assertEqual(spec.fragments[0], 'Меньшая сторона равна ')
        self.assertIsInstance(spec.fragments[1], Slot)
        self.assertEqual(spec.fragments[-1], ' см^2.')

    def test_latex_double_braces_are_not_slots(self):
        spec = parse_mask(r'Упростите $\frac{1}{x^{2}}$: {{simplify: x^{-2}}}')
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual(len(spec.slots), 1)
        self.assertEqual(spec.slots[0].raw, 'x^{-2}')
        self.assertIn(r'\frac{1}{x^{2}}', spec.fragments[0])

    def test_brace_balance_inside_slot(self):
        spec = parse_mask(r'{{simplify: \frac{2}{a+3}}} и {{set: \{-2;1\}}}')
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual(spec.slots[0].raw, r'\frac{2}{a+3}')
        self.assertEqual(spec.slots[1].data, [-2, 1])

    def test_errors(self):
        cases = {
            '{{foo: 1}}': 'неизвестный тип',
            '{{number: abc}}': 'не разобран как число',
            '{{number: 1': 'не закрыт',
            '{{choice: a}}': 'минимум два варианта',
            '{{choice: a|b}}': 'звёздочкой',
            '{{choice: *a|*b}}': 'звёздочкой',
            'просто текст': 'ни одного слота',
            '{{equation: x+1}}': 'уравнением',
            '{{range: abc}}': 'промежуток',
            '{{pair: 1}}': 'пары вида',
            '{{order: a}}': 'минимум два элемента',
        }
        for text, fragment in cases.items():
            spec = parse_mask(text)
            self.assertFalse(spec.is_valid, text)
            self.assertTrue(
                any(fragment in e for e in spec.errors), (text, spec.errors))

    def test_empty_mask_is_invalid_without_errors(self):
        spec = parse_mask('')
        self.assertFalse(spec.is_valid)
        self.assertEqual(spec.errors, [])

    def test_presets(self):
        s = slot('{{compare: >}}')
        self.assertEqual(s.kind, 'choice')
        self.assertEqual(s.preset, 'compare')
        self.assertEqual(s.options, ['<', '=', '>'])
        self.assertEqual(s.correct, '>')
        s = slot('{{parity: общего вида|периодическая}}')
        self.assertEqual(
            s.options, ['чётная', 'нечётная', 'общего вида', 'периодическая'])
        self.assertEqual(s.correct, 'общего вида')
        s = slot('{{yesno: нет|*не знаю}}')
        self.assertEqual(s.correct, 'не знаю')
        self.assertEqual(s.options, ['да', 'нет', 'не знаю'])

    def test_choice(self):
        s = slot('В классе больше {{choice: мальчиков|*девочек}}')
        self.assertEqual(s.options, ['мальчиков', 'девочек'])
        self.assertEqual(check_slot(s, 'девочек'), OK)
        self.assertEqual(check_slot(s, 'мальчиков'), WRONG)
        self.assertEqual(check_slot(s, ''), '')

    def test_display(self):
        spec = parse_mask('Ответ: {{number: 10}} см, {{order: a|b|c}}, {{set: }}')
        self.assertEqual(
            filled_text(spec, {'s1': '10', 's3': '∅'}),
            'Ответ: [10] см, ___, [нет решений]')
        self.assertEqual(
            filled_text(spec, {'s2': '2|0|1'}), 'Ответ: ___ см, [c, a, b], ___')
        self.assertEqual(reference_text(spec), 'Ответ: [10] см, [a, b, c], [∅]')

    def test_order_shuffle_is_stable_and_not_identity(self):
        s = slot(r'{{order: \sqrt[6]{5}|\sqrt[5]{4}|2}}')
        first = s.shuffled('seed')
        self.assertEqual(first, s.shuffled('seed'))
        self.assertNotEqual([i for i, _ in first], [0, 1, 2])
        self.assertEqual(sorted(i for i, _ in first), [0, 1, 2])


class MaskCheckTests(SimpleTestCase):
    def test_overall_verdict(self):
        spec = parse_mask('{{number: 10}} и {{number: 30}}')
        self.assertEqual(check_mask(spec, {})[0], '')
        self.assertEqual(check_mask(spec, {'s1': '10'})[0], UNKNOWN)
        self.assertEqual(check_mask(spec, {'s1': '10', 's2': '30'})[0], OK)
        self.assertEqual(check_mask(spec, {'s1': '10', 's2': '31'})[0], WRONG)
        overall, per_slot = check_mask(spec, {'s1': 'abc', 's2': '30'})
        self.assertEqual(overall, UNKNOWN)
        self.assertEqual(per_slot, {'s1': UNKNOWN, 's2': OK})

    def test_number_forms(self):
        s = slot('{{number: 2,5}}')
        for value in ('2,5', '2.50', '5/2', '10/4', r'\frac{5}{2}', r'\frac{10}{4}',
                      '$2.5$', '2 1/2'.replace(' 1/2', r'\frac{1}{2}')):
            self.assertEqual(check_slot(s, value), OK, value)
        self.assertEqual(check_slot(s, '2,4'), WRONG)
        self.assertEqual(check_slot(s, 'два с половиной'), UNKNOWN)

    def test_number_irrational_and_tolerance(self):
        s = slot(r'{{number: \sqrt{2}}}')
        self.assertEqual(check_slot(s, r'\sqrt{2}'), OK)
        self.assertEqual(check_slot(s, '1,41'), WRONG)
        s = slot('{{number: 3,14 ~ 0,01}}')
        self.assertEqual(check_slot(s, '3,14159'), OK)
        self.assertEqual(check_slot(s, '3,1'), WRONG)

    def test_pair(self):
        s = slot('{{pair: (2,5; -3); (5; -6)}}')
        self.assertEqual(check_slot(s, '(5; -6); (5/2; -3)'), OK)
        self.assertEqual(check_slot(s, '(2.5;-3),(5;-6)'), OK)
        self.assertEqual(check_slot(s, '(-3; 2,5); (5; -6)'), WRONG)
        self.assertEqual(check_slot(s, '(2,5; -3)'), WRONG)
        self.assertEqual(check_slot(s, 'x=2'), UNKNOWN)
        single = slot('{{pair: (3; -4)}}')
        self.assertEqual(check_slot(single, '3; -4'), OK)
        self.assertEqual(check_slot(single, '(x=3; y=-4)'), OK)

    def test_set(self):
        s = slot('{{set: -3; 3}}')
        for value in ('3; -3', r'\{-3;3\}', r'x=\pm3', r'\pm 3', '-3, 3'):
            self.assertEqual(check_slot(s, value), OK, value)
        self.assertEqual(check_slot(s, '3'), WRONG)
        self.assertEqual(check_slot(s, '∅'), WRONG)
        empty = slot('{{set: }}')
        self.assertEqual(empty.reference, '∅')
        for value in ('∅', 'нет корней', 'нет решений'):
            self.assertEqual(check_slot(empty, value), OK, value)
        self.assertEqual(check_slot(empty, '0'), WRONG)

    def test_range(self):
        s = slot(r'{{range: (-\infty;-5)\cup(5;+\infty)}}')
        for value in ('x>5, x<-5', 'x<-5 или x>5', r'(-\infty;-5)∪(5;\infty)',
                      r'x \in (-\infty; -5) \cup (5; +\infty)', 'x<-5; x>5'):
            self.assertEqual(check_slot(s, value), OK, value)
        self.assertEqual(check_slot(s, 'x>5'), WRONG)
        self.assertEqual(check_slot(s, r'x\ge5, x<-5'), WRONG)
        self.assertEqual(check_slot(s, 'много'), UNKNOWN)
        s = slot('{{range: [1; 4)}}')
        self.assertEqual(check_slot(s, r'1\le x<4'), OK)
        self.assertEqual(check_slot(s, '1<x<4'), WRONG)
        self.assertEqual(check_slot(s, r'x\ge1, x<4'), WRONG,
                         'два неравенства через запятую — объединение (вся прямая)')
        self.assertEqual(check_slot(s, 'x>=1 и x<4'), OK)
        self.assertEqual(check_slot(slot('{{range: R}}'), 'x>1 и x<4'), WRONG)
        self.assertIsNone(sets.parse_pairs('2*(3;4)'))
        self.assertEqual(sets.parse_pairs('(3;4)'), [(3, 4)])
        s = slot('{{range: x>5}}')
        self.assertEqual(check_slot(s, r'(5; +\infty)'), OK)
        self.assertEqual(check_slot(s, '5<x'), OK)
        self.assertEqual(sets.parse_range('x<0 или x>=0'),
                         sets.parse_range('R'))
        self.assertEqual(sets.parse_range('нет решений'), frozenset())

    def test_order(self):
        s = slot(r'{{order: \sqrt[6]{5}|\sqrt[5]{4}|2}}')
        self.assertEqual(check_slot(s, '0|1|2'), OK)
        self.assertEqual(check_slot(s, '1|0|2'), WRONG)
        self.assertEqual(check_slot(s, '0|1'), UNKNOWN)
        self.assertEqual(check_slot(s, 'abc'), UNKNOWN)

    def test_equation(self):
        s = slot('{{equation: y=x+5}}')
        for value in ('y=x+5', 'y-x=5', 'x+5=y', 'y-x-5=0'):
            self.assertEqual(check_slot(s, value), OK, value)
        for value in ('y-2=x+3', '2y=2x+10', 'y=x+6', 'y=2x'):
            self.assertEqual(check_slot(s, value), WRONG, value)
        self.assertEqual(check_slot(s, 'x+5'), UNKNOWN)
        s = slot('{{equation: x=2}}')
        self.assertEqual(check_slot(s, '2=x'), OK)
        self.assertEqual(check_slot(s, '2x=4'), WRONG)

    def test_simplify(self):
        s = slot(r'{{simplify: \frac{2}{a+3}}}')
        for value in (r'\frac{2}{a+3}', r'\frac{2}{3+a}', '2*(1/(a+3))',
                      r'2\cdot\frac{1}{a+3}'):
            self.assertEqual(check_slot(s, value), OK, value)
        for value in ('4/(2a+6)', r'\frac{4}{2a+6}', r'\frac{1}{a+3}',
                      r'\frac{2a}{a^2+3a}'):
            self.assertEqual(check_slot(s, value), WRONG, value)
        s = slot('{{simplify: -2.5x+1}}')
        for value in ('-2.5x+1', '1-2,50x', '1-5x/2', '(2-5x)/2', r'\frac{2-5x}{2}',
                      r'1-\frac{5}{2}x', r'-\frac{5x}{2}+1'):
            self.assertEqual(check_slot(s, value), OK, value)
        for value in ('2(2-5x)/4', r'\frac{(x-2)(-10x+4)}{4(x-2)}',
                      r'1-\frac{10}{4}x', r'\frac{2(2-5x)}{4}', 'x'):
            self.assertEqual(check_slot(s, value), WRONG, value)
        self.assertEqual(check_slot(s, 'непонятно'), UNKNOWN)

    def test_simplify_numeric_leftovers(self):
        s = slot('{{simplify: 3x}}')
        self.assertEqual(check_slot(s, '3x'), OK)
        self.assertEqual(check_slot(s, 'x+2x'), WRONG)
        self.assertEqual(check_slot(s, r'\frac{6x}{2}'), WRONG)
        self.assertEqual(check_slot(s, r'\sqrt{9}x'), WRONG)
        self.assertEqual(check_slot(s, '(1+2)x'), WRONG)

    def test_factor(self):
        s = slot('{{factor: 2(x-1)(x+1)}}')
        for value in ('2(x-1)(x+1)', '-(x+1)*2*(1-x)', '(-1+x)(x+1)2',
                      r'2\cdot(x-1)\cdot(x+1)', '2(1-x)(-1-x)', '(x+1)(x-1)2'):
            self.assertEqual(check_slot(s, value), OK, value)
        for value in ('(2x-2)(x+1)', '2x^2-2', '(x^2-1)*2', '(x-1)(x+1)',
                      '2(x-1)(x+2)'):
            self.assertEqual(check_slot(s, value), WRONG, value)
        s = slot('{{factor: (x-1)^2(x+1)}}')
        for value in ('(x-1)^2(x+1)', '(x+1)(x-1)^{2}', '(x-1)(x-1)(x+1)'):
            self.assertEqual(check_slot(s, value), OK, value)
        self.assertEqual(check_slot(s, '(x^2-2x+1)(x+1)'), WRONG)
        s = slot('{{factor: x(x+2)}}')
        self.assertEqual(check_slot(s, '(x+2)x'), OK)
        self.assertEqual(check_slot(s, 'x^2+2x'), WRONG)
        s = slot('{{factor: x^2+1}}')
        self.assertEqual(check_slot(s, 'x^2+1'), OK,
                         'неприводимый эталон принимается как есть')


class ExpressionHelpersTests(SimpleTestCase):
    def test_prepare_inserts_multiplication(self):
        self.assertEqual(expressions.prepare('(x-1)(x+1)'), r'(x-1)\cdot (x+1)')
        self.assertEqual(expressions.prepare('x^2(x+1)'), r'x^2\cdot (x+1)')
        self.assertEqual(expressions.prepare('2x(x+1)'), r'2x\cdot (x+1)')
        self.assertEqual(expressions.prepare(r'\sin(x)'), r'\sin(x)')
        self.assertEqual(expressions.prepare(r'2\sqrt{2}x'), r'2\sqrt{2}\cdot x')
        self.assertEqual(check_answer(r'2\sqrt{2}x', r'\sqrt{8}x'), OK)

    def test_ambiguous_latex_is_still_an_expression(self):
        self.assertEqual(check_answer('2x/4', 'x/2'), OK)
        self.assertEqual(check_answer('2x(x+1)', '2x^2+2x'), OK)

    def test_numeric_value(self):
        self.assertEqual(sets.numeric_value('2,50'), 2.5)
        self.assertEqual(sets.numeric_value('10/4'), 2.5)
        self.assertEqual(sets.numeric_value(r'\frac{5}{2}'), 2.5)
        self.assertEqual(sets.numeric_value('x=3'), 3)
        self.assertIsNone(sets.numeric_value('x'))
        self.assertIsNone(sets.numeric_value('139°'))
        self.assertAlmostEqual(sets.numeric_value(r'\sqrt{2}'), 2 ** 0.5)

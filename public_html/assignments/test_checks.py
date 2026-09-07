"""Тесты ядра масок ответа: грамматика, слоты, проверки по типам."""
from fractions import Fraction

from django.test import SimpleTestCase, TestCase

from .check_answer import OK, UNKNOWN, WRONG, check_answer
from .checks import (Slot, check_mask, check_slot, collect_values, filled_text,
                     parse_mask, reference_text)
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

    def test_order_form_tokens_hide_indices(self):
        spec = parse_mask('{{order: a|b|c}}')
        slot = spec.slots[0]
        tokens = slot.order_tokens('p')
        self.assertEqual(len(set(tokens.values())), 3)
        self.assertFalse(any(tok in ('0', '1', '2') for tok in tokens.values()))
        data = {f'p_s1_{k}': tokens[k] for k in range(3)}
        self.assertEqual(collect_values(data, 'p', spec), {'s1': '0|1|2'})
        leaked = {f'p_s1_{k}': str(k) for k in range(3)}
        self.assertEqual(collect_values(leaked, 'p', spec), {'s1': ''})


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
        zero = slot('{{set: 0}}')
        self.assertEqual(check_slot(zero, r'\pm0'), OK)
        self.assertEqual(check_slot(zero, '0; 0'), OK)
        self.assertEqual(check_slot(zero, r'\pm 1'), WRONG)
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
        self.assertEqual(
            check_slot(slot(r'{{range: [1.5; 4]}}'), r'[1{,}5; 4]'), OK,
            'виджет прямой пишет десятичную запятую как 1{,}5')
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
        self.assertEqual(sets.parse_range('x>1 и x<0'), frozenset())
        self.assertEqual(check_slot(slot('{{range: нет решений}}'), 'x>1 и x<0'), OK)
        self.assertEqual(check_slot(slot('{{range: нет решений}}'), 'много'), UNKNOWN)
        self.assertEqual(sets.parse_range('вся числовая прямая'),
                         sets.parse_range('R'))
        s = slot(r'{{range: [\sqrt{2}; +\infty)}}')
        self.assertEqual(check_slot(s, r'[\sqrt{2}; +\infty)'), OK)
        self.assertEqual(check_slot(s, r'x \ge \sqrt{2}'), OK)
        s = slot(r'{{range: [\sqrt{2}; 3]}}')
        self.assertEqual(check_slot(s, r'[\sqrt{2}; 3]'), OK)
        self.assertEqual(check_slot(s, '[1.4142135623730951; 3]'), OK)
        self.assertEqual(check_slot(s, '[1.41; 3]'), WRONG)
        self.assertEqual(check_slot(s, r'(\sqrt{2}; 3]'), WRONG)
        s = slot(r'{{range: [\frac{7}{3}; 5]}}')
        self.assertEqual(check_slot(s, r'[7/3; 5]'), OK)
        spec = parse_mask(r'{{number: 1 ~ \infty}}')
        self.assertFalse(spec.is_valid)

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
        s = slot('{{factor: x^2}}')
        self.assertEqual(check_slot(s, 'x^2'), OK,
                         'степень одиночной переменной — уже разложение')
        self.assertEqual(check_slot(s, 'x^{2}'), OK)


class ExpressionHelpersTests(SimpleTestCase):
    def test_prepare_inserts_multiplication(self):
        self.assertEqual(expressions.prepare('(x-1)(x+1)'), r'(x-1)\cdot (x+1)')
        self.assertEqual(expressions.prepare('x^2(x+1)'), r'x^2\cdot (x+1)')
        self.assertEqual(expressions.prepare('2x(x+1)'), r'2x\cdot (x+1)')
        self.assertEqual(expressions.prepare(r'\sin(x)'), r'\sin(x)')
        self.assertEqual(expressions.prepare(r'2\sqrt{2}x'), r'2\sqrt{2}\cdot x')
        self.assertEqual(expressions.prepare(r'\log_{2}x'), r'\log_{2}x')
        self.assertEqual(expressions.prepare(r'\sin^{2}x'), r'\sin^{2}x')
        self.assertEqual(expressions.prepare(r'\log_{2}(x)'), r'\log_{2}(x)')
        self.assertEqual(check_answer(r'2\sqrt{2}x', r'\sqrt{8}x'), OK)
        self.assertEqual(check_answer(r'\log_{2}x', r'\frac{\ln x}{\ln 2}'), OK)
        self.assertEqual(check_answer(r'\sin^{2}x', r'1-\cos^{2}x'), OK)

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
        self.assertIsNone(sets.numeric_value(r'\infty'))
        self.assertIsNone(sets.numeric_value('+\\infty'))
        huge = Fraction(10 ** 999, 1)
        self.assertTrue(sets.numbers_equal(huge, huge))
        self.assertFalse(sets.numbers_equal(huge, huge + 1))
        self.assertTrue(sets.numbers_equal(huge, huge, tolerance=1))
        self.assertFalse(sets.numbers_equal(huge, huge + 2, tolerance=1))
        self.assertEqual(check_slot(slot(r'{{number: 10^{999}}}'), r'10^{999}'), OK)
        self.assertEqual(check_slot(slot(r'{{number: 10^{999}}}'), r'10^{998}'), WRONG)


class MaskModelTests(TestCase):
    """answer_json/check_json у ответа: сверка по маске и показ учителю."""

    def setUp(self):
        from problems.models import Task, TaskSubitem
        from .tests import make_assignment, make_student, make_teacher
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.assignment = make_assignment(self.teacher, self.student)
        self.task = self.assignment.worksheet.ordered_items()[0].task
        self.task.answer_mask = ('Меньшая сторона {{number: 10}} см, '
                                 'больше {{choice: мальчиков|*девочек}}')
        self.task.save()
        self.sub = TaskSubitem.objects.create(
            task=self.task, order=10, text_latex='а',
            answer_mask='{{set: -2; 1}}')
        self.Task = Task

    def test_run_check_by_mask_and_display(self):
        from .models import Submission
        s = Submission(assignment=self.assignment, task=self.task,
                       answer_json={'s1': '20/2', 's2': 'мальчиков'})
        changed = s.run_check(spec=self.task.mask_spec)
        self.assertTrue(changed)
        self.assertEqual(s.auto_check, WRONG)
        self.assertEqual(s.check_json, {'s1': OK, 's2': WRONG})
        self.assertEqual(s.slot_check('s2'), WRONG)
        self.assertEqual(s.slot_value('s1'), '20/2')
        self.assertEqual(s.display_answer,
                         'Меньшая сторона [20/2] см, больше [мальчиков]')
        # Повтор без изменений — не «changed»
        self.assertFalse(s.run_check(spec=self.task.mask_spec))

    def test_run_check_without_spec_uses_free_fields(self):
        from .models import Submission
        s = Submission(assignment=self.assignment, task=self.task,
                       answer_text='0; 2')
        s.run_check(reference=self.task.answer_latex)
        self.assertEqual(s.auto_check, OK)
        self.assertEqual(s.check_json, {})
        self.assertEqual(s.display_answer, '0; 2')

    def test_part_uses_subitem_mask(self):
        from .models import Submission, SubmissionPart
        s = Submission.objects.create(assignment=self.assignment, task=self.task)
        part = SubmissionPart(submission=s, subitem=self.sub,
                              answer_json={'s1': '1; -2'})
        self.assertIs(part.mask_owner, self.sub)
        part.run_check(spec=part.mask_spec)
        self.assertEqual(part.auto_check, OK)
        self.assertEqual(part.display_answer, '[1; -2]')
        # Пустой JSON — старое представление
        part.answer_json = {}
        self.assertEqual(part.display_answer, '')

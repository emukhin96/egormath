"""Черновик маски из ответа: именованные величины, неравенства, отношения."""
from django.test import SimpleTestCase

from .checks.mask import _draft_mask, _named_objects, draft_mask


class NamedQuantityDraftTests(SimpleTestCase):
    def test_named_angles_get_labeled_fields_in_order(self):
        condition = (r'В трапеции \(A B C D\) \(A B=C D, \angle B A C=20^{\circ}\). '
                     r'Найдите углы \(A C B\) и \(A C D\).')
        self.assertEqual(
            draft_mask(r'$50^{\circ}$, $60^{\circ}$', condition),
            r'$\angle ACB =$ {{number: 50}}°; $\angle ACD =$ {{number: 60}}°')
        self.assertEqual(
            draft_mask('$45$ см, $18$ см', 'Дан треугольник. Найдите стороны $AC$ и $BC$.'),
            '$AC =$ {{number: 45}} см; $BC =$ {{number: 18}} см')

    def test_named_objects_parser(self):
        self.assertEqual(_named_objects(r'Найдите углы \(A C B\) и \(A C D\).'),
                         [r'\angle ACB', r'\angle ACD'])
        self.assertEqual(_named_objects('Найдите стороны $AC$, $BC$ и $AB$.'), ['AC', 'BC', 'AB'])
        self.assertEqual(_named_objects('Найдите $AK$ и $KC$.'), ['AK', 'KC'])
        self.assertEqual(_named_objects('Найдите углы параллелограмма.'), [])
        self.assertEqual(_named_objects('Дано: углы $A$ и $B$ равны. Найдите периметр.'), [])

    def test_name_count_mismatch_abstains(self):
        self.assertEqual(draft_mask(
            r'$60^{\circ}$, $120^{\circ}$, $60^{\circ}$, $120^{\circ}$',
            'Найдите углы $A$ и $B$ параллелограмма.'), '')

    def test_unnamed_homogeneous_quantities_keep_multiplicity_without_order(self):
        self.assertEqual(draft_mask(r'$60^{\circ}$, $120^{\circ}$',
                                    'Найдите углы параллелограмма, если один в 2 раза больше.'),
                         '{{expressions: 60; 120}}°')
        self.assertEqual(draft_mask('$8$ см, $40$ см',
                                    'Найдите стороны параллелограмма, периметр которого 96 см.'),
                         '{{expressions: 8; 40}} см')
        self.assertEqual(draft_mask(r'$56^{\circ}$, $56^{\circ}$, $68^{\circ}$',
                                    'Найдите углы треугольника.'),
                         '{{expressions: 56; 56; 68}}°')
        self.assertEqual(draft_mask('$2$ см или $18$ см', 'Найдите расстояние между основаниями.'),
                         '{{set: 2; 18}} см')
        # Повтор без геометрического контекста по-прежнему не угадывается.
        self.assertEqual(draft_mask('$3$, $3$', 'Найдите значения.'), '')


class InequalityAndRangeDraftTests(SimpleTestCase):
    def test_inequality_solution_is_a_range_not_a_pair(self):
        self.assertEqual(draft_mask('$(-2; 1)$', r'Решите неравенство \(\left|x^{2}-x-3\right|<9\).'),
                         r'$x \in${{range: (-2; 1)}}')
        self.assertEqual(draft_mask(r'$(-\infty;-2)\cup(3;+\infty)$', 'Решите неравенство $x^2-x-6>0$.'),
                         r'$x \in${{range: (-\infty;-2)\cup(3;+\infty)}}')
        self.assertEqual(draft_mask('$(-2; 1)$', 'При каких значениях $a$ уравнение имеет корни?'),
                         '{{range: (-2; 1)}}')
        self.assertEqual(draft_mask('$(-2; 1)$', 'Найдите координаты точки пересечения.'),
                         '{{pair: (-2; 1)}}')
        self.assertEqual(draft_mask('$-3; -1; 2$', 'Решите уравнение $x(x^2+2x+1)=6(x+1)$.'),
                         '$x =${{range: -3; -1; 2}}')

    def test_set_braces_and_multi_variable_ranges(self):
        self.assertEqual(draft_mask(r'$\{3\}$', ''), r'{{range: \{3\}}}')
        self.assertEqual(draft_mask(r'$\{3\}$', r'Решите неравенство $\frac13x^2-2x+3\le0$.'),
                         r'$x \in${{range: \{3\}}}')
        self.assertEqual(draft_mask('$a>0, b<0, c<0$', 'Определите знаки коэффициентов a, b, c.'), '')
        self.assertEqual(draft_mask('$m<-2$', 'При каких значениях параметра $m$ функция убывает?'),
                         '{{range: m<-2}}')


class RatioAndRadicalDraftTests(SimpleTestCase):
    def test_ratio_order_follows_the_question(self):
        self.assertEqual(draft_mask('$2 : 3$', 'Найдите отношение $CO:OE$.'), '{{ratio: 2 : 3}}')
        self.assertEqual(draft_mask('$2 : 3$', 'В каком отношении точка D делит отрезок BC, считая от B?'),
                         '{{ratio: 2 : 3}}')
        self.assertEqual(draft_mask('$2 : 3$', 'Как относятся площади трапеций?'),
                         '{{proportion: 2 : 3}}')
        self.assertEqual(draft_mask(r'$\frac{6}{7}$', 'Найдите отношение $CK:BD$.'),
                         '{{ratio: 6:7 | quotient}}')
        self.assertEqual(draft_mask('$6/7$', 'Как относятся площади частей?'),
                         '{{proportion: 6:7 | quotient}}')
        self.assertEqual(draft_mask(r'$\frac{6}{7}$', 'Найдите вероятность.'),
                         r'{{number: \frac{6}{7}}}')

    def test_radical_answers_in_simplification_tasks_become_simplify(self):
        # Кандидат до проверки собственным эталоном: число совпадает и у
        # \sqrt{8}, требование к виду записи держит только simplify.
        self.assertEqual(_draft_mask(r'$2\sqrt{2}$', r'Вынесите множитель из-под знака корня: $\sqrt{8}$.'),
                         r'{{simplify: 2\sqrt{2}}}')
        self.assertEqual(_draft_mask(r'$\sqrt{12}$', r'Внесите множитель под знак корня: $2\sqrt{3}$.'),
                         r'{{simplify: \sqrt{12}}}')
        self.assertEqual(draft_mask(r'$2\sqrt{2}$', 'Найдите длину отрезка.'),
                         r'{{number: 2\sqrt{2}}}')

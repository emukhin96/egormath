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

    def test_names_in_data_clause_and_wrong_object_kind_are_ignored(self):
        # Имена из придаточного «если катеты AC и BC…» не подписывают углы.
        self.assertEqual(draft_mask(
            r'$30^{\circ}$, $60^{\circ}$',
            r'Найдите острые углы треугольника, если катеты $AC$ и $BC$ равны $3$ и $3\sqrt3$.'),
            '{{expressions: 30; 60}}°')
        # Градусы не подписываются именами отрезков и наоборот; дуги — в градусах.
        self.assertEqual(draft_mask(r'$30^{\circ}$, $60^{\circ}$', 'Найдите стороны $AB$ и $BC$.'), '')
        self.assertEqual(draft_mask('$3$ см, $4$ см', 'Найдите углы $A$ и $B$.'), '')
        self.assertEqual(draft_mask(r'$100^{\circ}$, $260^{\circ}$', 'Найдите дуги $AB$ и $BC$.'),
                         '$AB =$ {{number: 100}}°; $BC =$ {{number: 260}}°')
        self.assertEqual(_named_objects('Найдите дуги $AB$ и $BC$.', with_measure=True),
                         (['AB', 'BC'], 'angular'))
        # Имена с \angle без слова «углы» — тоже углы, префикс сохраняется.
        self.assertEqual(draft_mask(r'$50^{\circ}$, $60^{\circ}$', r'Найдите $\angle A$ и $\angle B$.'),
                         r'$\angle A =$ {{number: 50}}°; $\angle B =$ {{number: 60}}°')
        self.assertEqual(_named_objects('Катеты $AC$ и $BC$ равны 3 и 4. Найдите углы треугольника.'), [])
        self.assertEqual(_named_objects('Найдите углы $A$ и $B$, если $AB=5$ и $BC=3$.'),
                         [r'\angle A', r'\angle B'])

    def test_quantity_and_ratio_words_only_in_the_question(self):
        self.assertEqual(draft_mask('$2$ ч, $3$ ч',
                                    'Скорость лодки 10 км/ч. Найдите время движения туда и обратно.'),
                         '{{number: 2}} ч, {{number: 3}} ч')
        self.assertEqual(draft_mask(r'$\frac{3}{5}$',
                                    'Стороны относятся как $3:4:5$. Найдите синус угла $A$.'),
                         r'{{number: \frac{3}{5}}}')
        self.assertEqual(draft_mask('$2 : 3$',
                                    'Площади относятся как 2:3. В каком отношении точка делит отрезок, считая от A?'),
                         '{{ratio: 2 : 3}}')

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
        # Перечисление разных объектов задаёт порядок: поля по порядку.
        self.assertEqual(draft_mask(r'$\frac{3}{2}$ см, $\frac{25}{8}$ см',
                                    'Найдите радиусы вписанной и описанной окружностей.'),
                         r'{{number: \frac{3}{2}}} см, {{number: \frac{25}{8}}} см')
        self.assertEqual(draft_mask('$4$ см, $9$ см', 'Найдите катеты, если гипотенуза равна 5 и один катет больше.'),
                         '{{expressions: 4; 9}} см')
        for condition in ('Найдите периметр и площадь прямоугольника.',
                          'Найдите площадь треугольника ABC и его периметр.',
                          'Найдите объём и площадь поверхности куба.',
                          'Найдите скорость лодки в стоячей воде и скорость течения.',
                          'Найдите радиус окружности, вписанной в треугольник, и радиус описанной.',
                          'Найдите меньший и больший катеты.',
                          'Найдите острый и тупой углы ромба.',
                          'Найдите площади треугольников ABC и ABD.'):
            with self.subTest(condition=condition):
                self.assertEqual(draft_mask('$24$, $20$', condition),
                                 '{{number: 24}}, {{number: 20}}')
        # Одно имя на два значения — черновик отказывается, а не угадывает.
        self.assertEqual(draft_mask('$24$, $20$', 'Найдите длину стороны AB и высоту.'), '')
        # Единственное число величины — не однородный набор.
        self.assertEqual(draft_mask('$24$, $20$', 'Найдите площадь.'), '{{number: 24}}, {{number: 20}}')
        # Родительный множественный и вопрос без слова-величины — тоже набор.
        for condition in ('Найдите величины углов треугольника.',
                          'Найдите градусные меры углов параллелограмма.',
                          'Углы треугольника относятся как 2:3:4. Найдите их.'):
            with self.subTest(condition=condition):
                self.assertEqual(draft_mask(r'$30^{\circ}$, $60^{\circ}$, $90^{\circ}$', condition),
                                 '{{expressions: 30; 60; 90}}°')
                self.assertEqual(draft_mask(r'$56^{\circ}$, $56^{\circ}$, $68^{\circ}$', condition),
                                 '{{expressions: 56; 56; 68}}°')
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
        # Ответ-неравенство остаётся без подписи «x ∈».
        self.assertEqual(draft_mask('$x<2$', 'Решите неравенство $3x-1<5$.'), '{{range: x<2}}')
        self.assertEqual(draft_mask(r'$x\le -1$ или $x\ge 3$', 'Решите неравенство $x^2-2x-3\ge0$.'),
                         r'{{range: x\le -1; x\ge 3}}')
        # \left( — не \le: скобочная запись Mathpix сохраняет подпись.
        self.assertEqual(draft_mask(r'$\left(-2; 1\right)$', 'Решите неравенство $|x^2-x-3|<9$.'),
                         r'$x \in${{range: \left(-2; 1\right)}}')

    def test_set_braces_and_multi_variable_ranges(self):
        self.assertEqual(draft_mask(r'$\{3\}$', ''), '{{set: 3}}')
        self.assertEqual(draft_mask(r'$\{-2;1\}$', ''), '{{set: -2;1}}')
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

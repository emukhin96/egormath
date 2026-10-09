"""ОГЭ проверяет запись ответа, отношения — точную пропорцию."""
from django.test import SimpleTestCase
from .checks import parse_mask, check_slot, draft_mask


class StrictFormatsTests(SimpleTestCase):
    def check_values(self, mask, correct, wrong, bad_format=()):
        """``wrong`` — верный формат, неверное значение; ``bad_format`` —
        запись не по бланку: статус ``format`` (в итоге по задаче — неверно)."""
        spec = parse_mask(mask)
        self.assertTrue(spec.is_valid, spec.errors)
        for value in correct:
            with self.subTest(mask=mask, value=value):
                self.assertEqual(check_slot(spec.slots[0], value), 'ok')
        for value in wrong:
            with self.subTest(mask=mask, value=value):
                self.assertEqual(check_slot(spec.slots[0], value), 'wrong')
        for value in bad_format:
            with self.subTest(mask=mask, value=value):
                self.assertEqual(check_slot(spec.slots[0], value), 'format')
        self.assertEqual(check_slot(spec.slots[0], ''), '')

    def test_digits_are_not_numbers(self):
        self.check_values('{{digits: 234}}', ['234', ' 234 '], ['0234'],
                          ['234,00', '468/2', '2 3 4', '+234',
                           '234.0', '٢٣٤', '$234$', '234\n0', '2*117'])
        self.check_values('{{digits: 001}}', ['001'], ['1', '01'])

    def test_decimal_requires_decimal_not_expression(self):
        self.check_values('{{decimal: -0,5}}', ['-0,5', '-0,50', '-00,500'], ['0,5', '-0,6'],
                          ['-1/2', '-0.5', '-,5', '-0,5+0', '−0,5', '+0,5'])
        self.check_values('{{decimal: 234}}', ['234', '234,00'], [], ['468/2'])

    def test_ratio_order_and_scaling(self):
        self.check_values('{{ratio: 1:2}}', ['1:2', '2:4', '8:16', '1,5 : 3', '-1:-2', '1:2+0'],
                          ['2:1', '1:0', '0:0', '1:2:3', '1:3+0'], ['0,5', '1/2'])
        self.check_values('{{proportion: 1:2}}', ['1:2', '2:1', '8:16', '16:8'],
                          ['1:3', '1:0', '0:0'], ['0,5', '2'])
        self.check_values('{{ratio: 0:2}}', ['0:3'], ['1:0'], ['0'])

    def test_invalid_references_and_large_values(self):
        for text in ['{{digits: 2 3}}', '{{digits: 2,0}}', '{{decimal: 1/2}}',
                     '{{ratio: 0,5}}', '{{proportion: 1:0}}']:
            self.assertFalse(parse_mask(text).is_valid, text)
        self.check_values('{{ratio: 1:2}}', [], ['9' * 10000 + ':2'])

    def test_oge_drafting_and_existing_number_behavior(self):
        for number in [1, 7, 11, 13, 19]:
            self.assertEqual(draft_mask('$234$', exam_codes=[f'OGE_2026_{number:02}']),
                             '{{digits: 234}}')
        self.assertEqual(draft_mask('$-0{,}5$', exam_codes=['OGE_2026_06']),
                         '{{decimal: -0,5}}')
        self.assertEqual(draft_mask('1/2', exam_codes=['OGE_2026_06']), '')
        self.assertEqual(draft_mask('234', exam_codes=['OGE_2026_06', 'OGE_2026_11']), '')
        self.assertEqual(draft_mask('1:2'), '{{ratio: 1:2}}')
        self.assertEqual(draft_mask('234'), '{{number: 234}}')
        self.check_values('{{number: 234}}', ['234,00', '468/2'], ['235'])

    def test_textbook_geometry_drafting(self):
        self.assertEqual(
            draft_mask(r'$60^{\circ}$ или $120^{\circ}$'),
            '{{set: 60; 120}}°')
        self.assertEqual(
            draft_mask(r'$60^{\circ}$'),
            '{{number: 60}}°')
        self.assertEqual(
            draft_mask(r'$15$ см, $24$ см'),
            '{{number: 15}} см, {{number: 24}} см')
        self.assertEqual(
            draft_mask(r'$40^{\circ}$, $80^{\circ}$, $40^{\circ}$'),
            '')
        self.assertEqual(
            draft_mask(r'$5$ сторон'),
            '{{number: 5}} сторон')
        self.assertEqual(
            draft_mask(
                r'$A(1; 2)$, $B(-3; 4)$',
                'Найдите координаты точек A и B.'),
            '$A =$ {{pair: (1; 2)}}, $B =$ {{pair: (-3; 4)}}')
        self.assertEqual(
            draft_mask(
                r'$\overrightarrow{AF}(1; 2)$, $\vec m(-3; 4)$',
                'Найдите координаты векторов.'),
            (r'$\overrightarrow{AF} =$ {{pair: (1; 2)}}, '
             r'$\vec m =$ {{pair: (-3; 4)}}'))
        self.assertEqual(
            draft_mask(
                r'$(1; -4)$ или $(-1; 1)$',
                'Найдите координаты точки M.'),
            '{{pair: (1; -4); (-1; 1)}}')
        self.assertEqual(
            draft_mask('$x=2$, $y=-3$', 'Найдите x и y.'),
            '$x =${{range: 2}}, $y =${{range: -3}}')
        self.assertEqual(
            draft_mask('$x=3$', 'Найдите x.'),
            '$x =${{range: 3}}')
        self.assertEqual(
            draft_mask('$x=7$ или $x=-1$', 'Решите уравнение.'),
            '$x =${{range: 7; -1}}')
        self.assertEqual(
            draft_mask('$5x+3y=6$', 'Составьте уравнение прямой.'),
            '{{equation: 5x+3y=6}}')

    def test_ordered_named_values_do_not_become_a_set(self):
        self.assertEqual(
            draft_mask(
                r'$\frac{3}{2}$ см, $\frac{25}{8}$ см',
                'Найдите радиусы вписанной и описанной окружностей.'),
            (r'{{number: \frac{3}{2}}} см, '
             r'{{number: \frac{25}{8}}} см'))
        self.assertEqual(
            draft_mask('$8$ км/ч, $3$ км/ч',
                       'Найдите скорости лодки и течения.'),
            '{{number: 8}} км/ч, {{number: 3}} км/ч')

    def test_generated_mask_must_accept_its_reference(self):
        # Уравнение окружности с константами по обе стороны раньше отвергало
        # собственный эталон (приведённый вид); теперь equation принимает
        # равносильные записи, и черновик допустим.
        self.assertEqual(
            draft_mask(r'$(x+3)^2+(y-2)^2=25$',
                       'Составьте уравнение окружности.'),
            '{{equation: (x+3)^2+(y-2)^2=25}}')
        self.assertEqual(draft_mask('$x+x$'), '')

    def test_textbook_yes_no_drafting(self):
        self.assertEqual(draft_mask('Да.'), '{{yesno: да}}')
        self.assertEqual(draft_mask('Нет.'), '{{yesno: нет}}')
        self.assertEqual(draft_mask('Да, точка A лежит на прямой.'), '')
        self.assertEqual(
            draft_mask('Существует.', 'Существует ли такой угол?'),
            '{{yesno: да}}')
        self.assertEqual(
            draft_mask('Не могут.', 'Могут ли точки совпадать?'),
            '{{yesno: нет}}')

    def test_ratio_trigonometric_numbers_keep_order_and_domains(self):
        self.check_values('{{ratio: 4:1 | quotient}}',
                          [r'4\sin(90^{\circ})', r'8\sin(30^{\circ})',
                           r'8\sin(30^{\circ}):1', r'4:\cos(0)',
                           r'\sqrt[3]{-8}:-0.5'],
                          [r'4\sin(30^{\circ})', r'1:4\sin(90^{\circ})',
                           r'4:\sin(0)', r'4+0/\sin(0)', r'4+0*\tan(90^{\circ})',
                           r'4+\sin(x)-\sin(x)', r'4+\sqrt{-1}-\sqrt{-1}',
                           r'4\sin(90^{\circ})=4', r'4:1:1'])
        self.check_values('{{proportion: 4:1 | quotient}}',
                          [r'\cos(0):4', r'\cos(0)/4', r'4:\cos(0)'],
                          [r'0:\sin(0)', r'\sin(0):4', r'4:\sin(0)'])

    def test_ratio_mathlive_function_aliases_and_degree_macro(self):
        self.check_values('{{ratio: 4:1 | quotient}}',
                          [r'4\operatorname{tg}(45^{\circ}):1',
                           r'8\sin(30\degree):1', r'4\tg(45°):1',
                           r'4\operatorname{ctg}(45°):1',
                           r'4\operatorname{\mathrm{tg}}45^{\circ}:1',
                           r'4\operatorname{\mathrm{ctg}}45^{\circ}:1',
                           r'2\sec(60°):1', r'2\csc(30°):1'],
                          [r'4\operatorname{tg}(30°):1',
                           r'1:4\operatorname{tg}(45°)',
                           r'4\operatorname{tg}(90°):1',
                           r'4+0*\operatorname{ctg}(0°):1',
                           r'4+0/\sin(0\degree):1',
                           r'4+\operatorname{tg}(x)-\operatorname{tg}(x):1',
                           r'4\operatorname{unknown}(45°):1',
                           r'4\tga(45°):1'])
        self.check_values('{{proportion: 4:1 | quotient}}',
                          [r'1:4\operatorname{tg}(45°)',
                           r'\operatorname{\mathrm{ctg}}45°/4'],
                          [r'0:\operatorname{tg}(0°)',
                           r'4:\operatorname{tg}(0°)'])

    def test_ratio_function_power_keeps_original_domain(self):
        self.check_values('{{ratio: 7:2}}',
                          [r'\cos^245^{\circ}+\operatorname{\mathrm{tg}}^260^{\circ}:1',
                           r'\cos^{2}(45\degree)+\tg^{2}(60\degree):1'],
                          [r'\cos^245^{\circ}+\tg^260^{\circ}:2',
                           r'7/2+0*\tg^{2}(90°):1'])

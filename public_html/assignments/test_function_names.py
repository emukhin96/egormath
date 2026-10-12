"""Школьные имена тригонометрических функций в ответе ученика.

Ученик набирает arccos(1/6) буквами, MathLive присылает \\mathrm{arctg},
в эталонах книг стоит \\operatorname{arcctg}. Все записи должны сводиться
к одной функции до сравнения; нераспознанное имя — «не знаю», а не «неверно».
"""
from django.test import SimpleTestCase

from assignments.check_answer import check_answer, normalize, unrecognized_function
from assignments.checks.mask import check_slot, parse_mask


class FunctionNameNormalizeTests(SimpleTestCase):
    def test_letters_wrappers_and_commands_become_one_command(self):
        for value, expected in (
                ('arccos(1/6)', r'\arccos(1/6)'),
                (r'\mathrm{arctg}(1)', r'\arctan(1)'),
                (r'\operatorname{asin}x', r'\arcsin x'),
                (r'\operatorname{\mathrm{arcctg}} 2', r'\arccot 2'),
                (r'\text{ctg} x', r'\cot x'),
                (r'\arcctg 2', r'\arccot 2'),
                ('2arcsin x', r'2\arcsin x'),
                ('tg^2 x', r'\tan^2 x')):
            with self.subTest(value=value):
                self.assertEqual(normalize(value), expected)

    def test_letters_without_argument_stay_product(self):
        # t·g и s·i·n без аргумента — произведение параметров, не функция.
        for value in ('tg', 'tg + 1', 'tg^2/2', 'xsin x', 'arccosx', r'\cosh x'):
            with self.subTest(value=value):
                self.assertNotIn(r'\tan', normalize(value))
                self.assertNotIn(r'\sin ', normalize(value))
                self.assertNotIn(r'\arccos', normalize(value))

    def test_leftover_function_name_is_detected(self):
        for value in ('Arccos(1/6)', 'acos(1/6)', 'sinx', 'arcctgx'):
            with self.subTest(value=value):
                self.assertTrue(unrecognized_function(value))
        for value in ('arccos(1/6)', r'\mathrm{arctg}(1)', r'\sqrt{3}', 'ab+c', r'\pi-1'):
            with self.subTest(value=value):
                self.assertFalse(unrecognized_function(value))


class FunctionNameMaskTests(SimpleTestCase):
    def check(self, mask, value):
        spec = parse_mask(mask, validate_references=True)
        self.assertEqual(spec.errors, [], mask)
        return check_slot(spec.slots[0], value)

    def test_arccos_number_accepts_letters_and_mathrm(self):
        # Потоскуев, 6.085 в).
        mask = r'{{number: \arccos \frac{1}{6}}}'
        for value in ('arccos(1/6)', r'\arccos(1/6)', r'\mathrm{arccos}\frac{1}{6}',
                      r'\operatorname{arccos}(1/6)'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'ok')
        for value in ('arcsin(1/6)', 'arccos(1/5)'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'wrong')

    def test_arctg_number_accepts_every_spelling(self):
        # Потоскуев, 2.034 д).
        mask = r'{{number: \operatorname{arctg} \frac{\sqrt{2}}{2}}}'
        for value in ('arctg(sqrt(2)/2)', 'arctan(sqrt(2)/2)', r'\mathrm{arctg}(\sqrt{2}/2)',
                      r'\operatorname{\mathrm{arctg}}\frac{\sqrt{2}}{2}', r'\arctg\frac{\sqrt2}{2}',
                      r'\arctan(\sqrt{2}/2)'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'ok')
        self.assertEqual(self.check(mask, 'arctg(sqrt(3)/2)'), 'wrong')

    def test_arcctg_and_tg_references_are_numbers(self):
        mask = r'{{number: \operatorname{arcctg} 2}}'
        for value in ('arcctg(2)', 'arcctg 2', r'\mathrm{arcctg}(2)', r'\arccot 2', 'arccot(2)'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'ok')
        self.assertEqual(self.check(mask, 'arcctg(3)'), 'wrong')
        mask = r'{{number: \operatorname{tg} 2}}'
        for value in ('tg(2)', 'tg 2', 'tan 2', r'\mathrm{tg}(2)'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'ok')
        self.assertEqual(self.check(mask, 'ctg 2'), 'wrong')

    def test_constant_with_inverse_function(self):
        mask = r'{{number: \pi - \arccos \frac{1}{3}}}'
        for value in ('pi - arccos(1/3)', 'π-arccos(1/3)'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'ok')

    def test_unrecognized_name_goes_to_teacher(self):
        mask = r'{{number: \arccos \frac{1}{6}}}'
        for value in ('Arccos(1/6)', 'acos(1/6)', 'arccosx'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'unknown')

    def test_expression_and_simplify_with_letters(self):
        # Потоскуев, 6.090.
        mask = (r'{{simplify: \arccos \frac{\left|2 h^{2}-a^{2}\right|}'
                r'{2\left(a^{2}+h^{2}\right)}}}')
        for value in ('arccos(|2h^2-a^2|/(2(a^2+h^2)))',
                      r'\mathrm{arccos}\frac{|2h^2-a^2|}{2(a^2+h^2)}'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'ok')
        self.assertEqual(self.check(mask, 'arcsin(|2h^2-a^2|/(2(a^2+h^2)))'), 'wrong')
        mask = r'{{expression: \operatorname{arctg} x}}'
        for value in ('arctg(x)', 'arctg x', 'arctan(x)', r'\mathrm{arctg}(x)'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'ok')
        self.assertEqual(self.check(mask, 'arcctg(x)'), 'wrong')
        self.assertEqual(self.check(r'{{expression: 2\arccos x}}', '2arccos(x)'), 'ok')

    def test_parameters_t_and_g_stay_product(self):
        mask = r'{{expression: g t}}'
        for value in ('tg', 'tg+0', 't g'):
            with self.subTest(value=value):
                self.assertEqual(self.check(mask, value), 'ok')

    def test_collections_with_letters(self):
        self.assertEqual(self.check(r'{{set: \arccos\frac13; \pi-\arccos\frac13}}',
                                    'pi - arccos(1/3); arccos(1/3)'), 'ok')
        self.assertEqual(self.check(r'{{pair: \operatorname{arctg} 2; 1}}', '(arctg(2); 1)'), 'ok')

    def test_plain_answer_check(self):
        self.assertEqual(check_answer('arccos(1/6)', r'\arccos\frac{1}{6}'), 'ok')
        self.assertEqual(check_answer(r'\mathrm{arctg} 2', r'\operatorname{arctg} 2'), 'ok')
        self.assertEqual(check_answer('Arccos(1/6)', r'\arccos\frac{1}{6}'), 'unknown')

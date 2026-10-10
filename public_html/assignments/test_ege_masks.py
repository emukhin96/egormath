"""Маски ЕГЭ: строгие короткие ответы и эквивалентные серии корней."""
from django.test import SimpleTestCase
from .checks import draft_mask, parse_mask, check_slot
from .checks import series, sets


class EgeMaskTests(SimpleTestCase):
    def mask(self, answer, number, source='', condition=''):
        return draft_mask(answer, condition, [f'EGE_PROFILE_2027_{number:02}'],
                          source_number=source)

    def test_short_formats(self):
        self.assertEqual(self.mask(r'$\frac{1}{8}$', 1), '{{decimal: 0,125}}')
        self.assertEqual(self.mask('3', 9, '9.1.2'), '{{digits: 3}}')
        self.assertEqual(self.mask('3', 9, '9.2'), '{{decimal: 3}}')
        self.assertEqual(self.mask('1/3', 1), '')
        slot = parse_mask(self.mask('3', 9, '9.8')).slots[0]
        # Точка вместо запятой — ошибка записи, а не значения: отдельный
        # статус для подсказки ученику; итог по задаче всё равно «неверно».
        self.assertEqual(check_slot(slot, '3.0'), 'format')

    def test_late_formats(self):
        self.assertIn('range:', self.mask(r'$-\pi, 0, \pi$', 14))
        self.assertIn('number:', self.mask(r'$\pi$', 14))
        self.assertIn('range:', self.mask(r'(-\infty;0)\cup(0;5/3]\cup\{2\}\cup\{3\}', 19))
        self.assertEqual(self.mask('12', 18, condition='Докажите равенство.'), '')
        self.assertEqual(self.mask('1;2;3', 20, condition='Приведите пример.'), '')
        self.assertIn('number:', self.mask(r'\operatorname{arctg}\frac{1}{2}', 15))

    def test_pi_numeric(self):
        self.assertTrue(sets.numbers_equal(sets.numeric_value(r'2\pi'), sets.numeric_value('2*π')))
        self.assertIsNone(sets.numeric_value('Q+π'))

    def test_series_exact_equivalence(self):
        for left, right in [(r'\pi n', r'2\pi k; \pi+2\pi k'),
                            (r'\pm\frac{\pi}{6}+2\pi n', r'\frac{\pi}{6}+2\pi k; -\frac{\pi}{6}+2\pi k'),
                            (r'\pi n', r'2\pi k \cup (\pi+2\pi k)'),
                            (r'\pi/2+\pi n', r'3\pi/2-\pi k')]:
            with self.subTest(left=left):
                self.assertTrue(series.equal(series.parse(left), series.parse(right)))
        slot = parse_mask(self.mask(r'\pi n, n\in\mathbb{Z}', 14)).slots[0]
        self.assertEqual(check_slot(slot, r'2\pi k'), 'wrong')
        self.assertEqual(check_slot(slot, 'π*k; π/2+π*k'), 'wrong')
        self.assertEqual(check_slot(slot, 'π*k'), 'ok')

    def test_series_rejects_unsupported(self):
        for value in ('p*n', '0', 'π', 'π*n*n', 'sin(n)', 'π*n/10001', '__import__("os")', 'π/(n+1)'):
            with self.subTest(value=value):
                self.assertIsNone(series.parse(value))

"""Кэш числового вычислителя: ``sets.numeric_value`` запоминает результат
по тексту (аудит быстродействия 06.11.2026)."""
from fractions import Fraction

from unittest import mock

from django.core.cache import caches
from django.test import SimpleTestCase

from assignments.checks import sets
from assignments.checks.mask import parse_mask


class NumericValueCacheTests(SimpleTestCase):
    def setUp(self):
        sets._numeric_value.cache_clear()
        caches['numeric'].clear()

    def test_file_cache_survives_process_restart(self):
        # Новый процесс = пустой lru_cache; значение берётся из файлового кэша без разбора
        self.assertEqual(sets.numeric_value(r'\sqrt{2}'), sets.numeric_value(r'\sqrt{2}'))
        sets._numeric_value.cache_clear()
        with mock.patch('assignments.checks.sets._numeric_value_uncached',
                        side_effect=AssertionError('должно читаться из файлового кэша')):
            self.assertAlmostEqual(sets.numeric_value(r'\sqrt{2}'), 2 ** 0.5)
            # None тоже запоминается
        self.assertIsNone(sets.numeric_value('x+1'))
        sets._numeric_value.cache_clear()
        with mock.patch('assignments.checks.sets._numeric_value_uncached',
                        side_effect=AssertionError('None должен быть в кэше')):
            self.assertIsNone(sets.numeric_value('x+1'))

    def test_file_cache_key_depends_on_evaluator_code(self):
        sets.numeric_value('7')
        with mock.patch('assignments.checks.sets._numeric_code_version', 'other-code'):
            sets._numeric_value.cache_clear()
            with mock.patch('assignments.checks.sets._numeric_value_uncached',
                            return_value=Fraction(7)) as calc:
                sets.numeric_value('7')
        calc.assert_called_once()

    def test_without_django_cache_still_computes(self):
        sets._numeric_value.cache_clear()
        with mock.patch('assignments.checks.sets._file_cache', return_value=None):
            self.assertEqual(sets.numeric_value('3/4'), Fraction(3, 4))

    def test_repeat_is_served_from_cache(self):
        self.assertEqual(sets.numeric_value(r'\frac{3}{4}'), Fraction(3, 4))
        misses = sets._numeric_value.cache_info().misses
        self.assertEqual(sets.numeric_value(r'\frac{3}{4}'), Fraction(3, 4))
        info = sets._numeric_value.cache_info()
        self.assertEqual(info.misses, misses)
        self.assertGreaterEqual(info.hits, 1)

    def test_none_and_empty_text(self):
        self.assertIsNone(sets.numeric_value(None))
        self.assertIsNone(sets.numeric_value(''))
        self.assertIsNone(sets.numeric_value('x+1'))

    def test_mask_parsed_twice_gives_equal_specs(self):
        mask = r'Ответ: {{number: \sqrt{2}~0,01}} и {{range: x>1, x\ne 3}}'
        first = parse_mask(mask)
        second = parse_mask(mask)
        self.assertTrue(first.is_valid, first.errors)
        self.assertEqual([s.data for s in first.slots], [s.data for s in second.slots])
        self.assertEqual([s.tolerance for s in first.slots], [s.tolerance for s in second.slots])
        # Разные объекты MaskSpec: правки одного не задевают другой
        self.assertIsNot(first, second)
        self.assertIsNot(first.slots[0], second.slots[0])

"""Статус «формат» строгих полей, точный range, разделители списков и пар."""
from django.test import SimpleTestCase

from .check_answer import FORMAT, OK, UNKNOWN, WRONG
from .checks import formats, formulas, numeric_collections, sets
from .checks.mask import check_mask, check_slot, parse_mask


def slot(mask):
    spec = parse_mask(mask)
    assert spec.is_valid, spec.errors
    return spec.slots[0]


class StrictFormatStatusTests(SimpleTestCase):
    def test_decimal_wrong_notation_is_format_not_value(self):
        s = slot('{{decimal: 0,8}}')
        for value in ('0.8', '4/5', r'\frac{4}{5}', ',8', '+0,8', '0,8 см', '80%'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(s, value), FORMAT)
        for value, expected in (('0,8', OK), ('0,80', OK), ('0,9', WRONG), ('-0,8', WRONG)):
            with self.subTest(value=value):
                self.assertEqual(check_slot(s, value), expected)

    def test_digits_and_ratio(self):
        s = slot('{{digits: 215}}')
        for value in ('215,0', '2 1 5', '430/2', '215.'):
            self.assertEqual(check_slot(s, value), FORMAT, value)
        self.assertEqual(check_slot(s, '0215'), WRONG)
        self.assertEqual(check_slot(s, '215'), OK)
        s = slot('{{ratio: 2:3}}')
        self.assertEqual(check_slot(s, '2/3'), FORMAT)
        self.assertEqual(check_slot(s, '3:2'), WRONG)
        s = slot('{{ratio: 2:3 | quotient}}')
        self.assertEqual(check_slot(s, '2/3'), OK)
        self.assertEqual(check_slot(s, '3/2'), WRONG)
        s = slot('{{proportion: 2:3}}')
        self.assertEqual(check_slot(s, '3/2'), FORMAT)

    def test_overall_verdict_counts_format_as_wrong(self):
        spec = parse_mask('{{decimal: 0,8}}; {{digits: 12}}')
        overall, checks = check_mask(spec, {'s1': '0.8', 's2': '12'})
        self.assertEqual(overall, WRONG)
        self.assertEqual(checks, {'s1': FORMAT, 's2': OK})

    def test_badge_carries_the_slot_hint(self):
        from django.template.loader import render_to_string
        from .checks.mask import render_fragments
        spec = parse_mask('{{ratio: 2:3}} и {{decimal: 0,8}}')
        html = render_to_string('assignments/_mask.html', {
            'fragments': render_fragments(spec, 'p', {'s1': '2/3', 's2': '0.8'},
                                          {'s1': FORMAT, 's2': FORMAT}),
            'editable': True, 'show_checks': True})
        self.assertIn('data-hint="Отношение через двоеточие — например 2:3"', html)
        self.assertIn('title="Отношение через двоеточие — например 2:3">✗ не тот формат', html)
        self.assertIn('title="Целое число или десятичная дробь через запятую', html)
        self.assertNotIn('цифры и запятая, без дробей, точки и единиц', html)

    def test_format_hint_text_and_helper(self):
        self.assertIn('запятую', slot('{{decimal: 0,8}}').format_hint)
        self.assertIn('дробью', slot('{{ratio: 2:3 | quotient}}').format_hint)
        self.assertEqual(slot('{{number: 2}}').format_hint, '')
        self.assertTrue(formats.wrong_format('decimal', '0.8'))
        self.assertFalse(formats.wrong_format('decimal', '0,9'))
        self.assertFalse(formats.wrong_format('ratio', '2/3', allow_quotient=True))
        self.assertFalse(formats.wrong_format('number', 'anything'))


class ExactRangeTests(SimpleTestCase):
    def test_irrational_bounds_are_compared_exactly(self):
        self.assertEqual(numeric_collections.check(
            '1.6457513110645906', r'-1+\sqrt{7}', kind='range'), WRONG)
        self.assertEqual(numeric_collections.check(r'\sqrt7-1', r'-1+\sqrt{7}', kind='range'), OK)
        self.assertEqual(numeric_collections.check(
            r'(-\infty;-\sqrt2]\cup[\sqrt2;+\infty)', r'x\le-\sqrt{2} или x\ge\sqrt{2}',
            kind='range'), OK)
        self.assertEqual(numeric_collections.check(
            r'(-\infty;-1.4142]\cup[\sqrt2;+\infty)', r'x\le-\sqrt{2} или x\ge\sqrt{2}',
            kind='range'), WRONG)
        self.assertEqual(numeric_collections.check(
            r'\pi/2; \pi/6', r'\frac{\pi}{6};\frac{\pi}{2}', kind='range'), OK)
        self.assertEqual(numeric_collections.check(
            '0.5236;1.5708', r'\frac{\pi}{6};\frac{\pi}{2}', kind='range'), WRONG)

    def test_literal_ranges_stay_on_the_fast_path(self):
        s = slot('{{range: (-\\infty;-2)}}')
        for value, expected in (('m<-2', OK), ('2(m+1)<-2', OK), ('(-\\infty;-2]', WRONG),
                                ('[0, +\\infty)', UNKNOWN)):
            with self.subTest(value=value):
                self.assertEqual(check_slot(s, value), expected)
        self.assertFalse(formats.collection_needs_worker('m<-2', '(-\\infty;-2)', kind='range'))
        self.assertTrue(formats.collection_needs_worker(r'\sqrt7-1', r'-1+\sqrt{7}', kind='range'))

    def test_range_parser_accepts_exact_value_parser(self):
        from sympy import sqrt
        parsed = sets.parse_range(r'[\sqrt2;3)', value_parser=numeric_collections._number)
        self.assertEqual(parsed, frozenset({(sqrt(2), 3, '[', ')')}))
        self.assertTrue(sets.ranges_equal(
            parsed, sets.parse_range(r'x\ge\sqrt{2} и x<3', value_parser=numeric_collections._number),
            equal=numeric_collections._equal))


class ListSeparatorTests(SimpleTestCase):
    def test_sets_accept_conjunctions(self):
        for value in ('2;18', '18, 2', '2 и 18', '2 или 18'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot('{{set: 2; 18}}'), value), OK)
        self.assertEqual(check_slot(slot('{{range: \\{-6;6\\}}}'), '-6 и 6'), OK)

    def test_pairs_expand_plus_minus_and_or(self):
        s = slot('{{pair: (-2; 4 \\sqrt{3}); (-2; -4 \\sqrt{3})}}')
        for value in (r'(-2;\pm4\sqrt3)', r'(-2;±4\sqrt{3})', r'(-2;4\sqrt{3}) или (-2;-4\sqrt{3})'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(s, value), OK)
        self.assertEqual(check_slot(s, r'(\pm2;4\sqrt3)'), WRONG)
        self.assertEqual(check_slot(slot('{{pair: (-2;1)}}'), r'(-2;\pm1)'), WRONG)
        self.assertEqual(sets.parse_pairs(r'(1;\pm2)'), [(1, 2), (1, -2)])
        self.assertIsNone(sets.parse_pairs(r'(1;\pm2\pm3)'))

    def test_expressions_split_by_comma_and_conjunction(self):
        reference, _ = formulas._parse_reference('8; 40', multiple=True)
        for value, expected in (('8;40', OK), ('8, 40', OK), ('40, 8', OK), ('8 и 40', OK),
                                ('8,40', WRONG), ('8', WRONG), ('8;40;40', WRONG)):
            with self.subTest(value=value):
                self.assertEqual(formulas._check(value, reference, multiple=True), expected)
        reference, _ = formulas._parse_reference('22.5;67.5;90', multiple=True)
        self.assertEqual(formulas._check('22,5, 67,5, 90', reference, multiple=True), OK)
        self.assertEqual(formulas._check('22,5,67,5,90', reference, multiple=True), WRONG)
        self.assertEqual(formulas._split_list('a, b', 2), ['a', 'b'])
        self.assertEqual(formulas._split_list('7,2', 1), ['7,2'])

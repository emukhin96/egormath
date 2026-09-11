"""ОГЭ проверяет запись ответа, отношения — точную пропорцию."""
from django.test import SimpleTestCase
from .checks import parse_mask, check_slot, draft_mask


class StrictFormatsTests(SimpleTestCase):
    def check_values(self, mask, correct, wrong):
        spec = parse_mask(mask)
        self.assertTrue(spec.is_valid, spec.errors)
        for value in correct:
            with self.subTest(mask=mask, value=value):
                self.assertEqual(check_slot(spec.slots[0], value), 'ok')
        for value in wrong:
            with self.subTest(mask=mask, value=value):
                self.assertEqual(check_slot(spec.slots[0], value), 'wrong')
        self.assertEqual(check_slot(spec.slots[0], ''), '')

    def test_digits_are_not_numbers(self):
        self.check_values('{{digits: 234}}', ['234', ' 234 '],
                          ['234,00', '468/2', '2 3 4', '0234', '+234',
                           '234.0', '٢٣٤', '$234$', '234\n0', '2*117'])
        self.check_values('{{digits: 001}}', ['001'], ['1', '01'])

    def test_decimal_requires_decimal_not_expression(self):
        self.check_values('{{decimal: -0,5}}', ['-0,5', '-0,50', '-00,500'],
                          ['-1/2', '-0.5', '-,5', '-0,5+0', '−0,5', '+0,5'])
        self.check_values('{{decimal: 234}}', ['234', '234,00'], ['468/2'])

    def test_ratio_order_and_scaling(self):
        self.check_values('{{ratio: 1:2}}', ['1:2', '2:4', '8:16', '1,5 : 3', '-1:-2'],
                          ['2:1', '0,5', '1/2', '1:0', '0:0', '1:2:3', '1:2+0'])
        self.check_values('{{proportion: 1:2}}', ['1:2', '2:1', '8:16', '16:8'],
                          ['0,5', '2', '1:3', '1:0', '0:0'])
        self.check_values('{{ratio: 0:2}}', ['0:3'], ['1:0', '0'])

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

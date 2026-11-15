"""Маски ЕГЭ части 2: число с единицей, «да (пример)», формула с параметром,
параметр серии вне n/k/m/l и десятичная запятая в сдвиге серии
(сборник Ященко «36 вариантов», профиль ``yashchenko_ege``)."""
from django.test import SimpleTestCase

from .checks import check_slot, parse_mask
from .checks.ege_policy import ege_draft

OK = 'ok'


def draft(answer, number, condition=''):
    return ege_draft(answer, condition, [f'EGE_PROFILE_2027_{number:02d}'])


class EgePolicyUnitsTests(SimpleTestCase):
    def assert_accepts(self, mask, value):
        spec = parse_mask(mask)
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual(check_slot(spec.slots[0], value), OK, (mask, value))

    def test_number_with_unit_keeps_unit_as_text(self):
        self.assertEqual(draft('$204$ м', 17), '{{number: 204}} м')
        self.assertEqual(draft('$75$ Вт', 17), '{{number: 75}} Вт')
        self.assertEqual(draft('60°', 15), '{{number: 60}}°')
        mask = draft(r'\(3{,}105 \cdot 10^{-21}\) Дж', 17)
        self.assertTrue(mask.endswith(' Дж'), mask)
        self.assert_accepts(mask, r'3.105\cdot10^{-21}')
        mask = draft(r'\(1250 \mathrm{c}^{-1}\)', 17)
        self.assertTrue(mask.startswith('{{number: 1250}}'), mask)

    def test_part_one_answers_are_unchanged(self):
        self.assertEqual(draft('$2{,}5$', 7), '{{decimal: 2,5}}')

    def test_yes_with_example_is_yes_no(self):
        self.assertEqual(draft('да (например, число 729)', 20), '{{yesno: да}}')
        self.assertEqual(draft('нет', 20), None)

    def test_formula_with_condition_parameter(self):
        mask = draft(r'\(125 \sqrt{2 R}\)', 17)
        self.assertEqual(mask, r'{{expression: 125 \sqrt{2 R} | positive: R}}')
        self.assert_accepts(mask, r'125\sqrt{2R}')
        mask = draft(r'\(14{,}4 \sqrt{\frac{2}{2-n}}\)', 17)
        self.assert_accepts(mask, r'14.4\sqrt{\frac{2}{2-n}}')

    def test_series_parameter_p_and_decimal_shift(self):
        mask = draft(r'\(\frac{\pi}{2}+\pi m, m \in \mathbb{Z} ; 2 \pi p, p \in \mathbb{Z};'
                     r' \pi+4 \pi l, l \in \mathbb{Z}\)', 14)
        self.assertTrue(mask.startswith('{{series:'), mask)
        self.assertNotIn(' p', mask)
        mask = draft(r'\(\operatorname{arctg} 5{,}5+\pi n, n \in \mathbb{Z};'
                     r' \operatorname{arctg} 0{,}5+\pi k, k \in \mathbb{Z}\)', 14)
        self.assert_accepts(mask, r'arctg 5.5+\pi n; arctg 0.5+\pi k')

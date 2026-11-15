"""Маски ЕГЭ части 2: число с единицей, «да (пример)», формула с параметром,
параметр серии вне n/k/m/l и десятичная запятая в сдвиге серии
(сборник Ященко «36 вариантов», профиль ``yashchenko_ege``)."""
from django.test import SimpleTestCase

from .checks import check_slot, parse_mask
from .checks.ege_policy import ege_draft

OK = 'ok'


def draft(answer, number, condition='Найдите \\(x\\), если \\(n\\), \\(R\\) заданы.'):
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

    def test_relations_are_not_parameter_formulas(self):
        for answer in (r'\(x=2\)', r'\(a>1\)', r'\(S = 12\)', r'\(a \leq 3\)', 'a ≤ 3'):
            mask = draft(answer, 17)
            self.assertNotIn('expression', mask or '', answer)

    def test_units_in_mathrm_are_not_parameters(self):
        for answer in (r'\(14{,}4 \mathrm{c}\)', r'\(204 \mathrm{~m}\)', r'\(75 \text{ Вт}\)'):
            mask = draft(answer, 17, r'Найдите \(\tau\), если \(T=14{,}4\) с.')
            self.assertNotIn('expression', mask or '', answer)

    def test_parameter_must_be_in_condition(self):
        self.assertNotIn('expression', draft(r'\(125 \sqrt{2 R}\)', 17, 'Найдите мощность.') or '')

    def test_count_question_in_variant_book_is_digits(self):
        condition = 'Найдите количество точек, в которых производная функции равна 0.'
        mask = ege_draft('$4$', condition, ['EGE_PROFILE_2027_09'], source_number='В7/9')
        self.assertTrue(mask.startswith('{{digits:'), mask)
        mask = ege_draft('$-2$', 'Найдите точку максимума.', ['EGE_PROFILE_2027_09'], source_number='В7/9')
        self.assertTrue(mask.startswith('{{decimal:'), mask)
        # Банк: прототип по номеру, слова условия не решают.
        mask = ege_draft('$4$', condition, ['EGE_PROFILE_2027_09'], source_number='9.2.5')
        self.assertTrue(mask.startswith('{{decimal:'), mask)

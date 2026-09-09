"""Контекстный подбор не раскрывает количество корней и не решает задачу."""
from django.test import SimpleTestCase
from .checks import draft_mask, parse_mask, check_mask


class ContextDraftTests(SimpleTestCase):
    def test_single_root_still_uses_range(self):
        self.assertEqual(draft_mask('4', r'Решите уравнение $x-4=0$.'), '$x =${{range: 4}}')

    def test_multiple_roots_use_one_field(self):
        mask = draft_mask('x_1=1; x_2=4', r'Решите уравнение $x^2-5x+4=0$.')
        self.assertEqual(mask, '$x =${{range: 1; 4}}')
        self.assertEqual(check_mask(parse_mask(mask), {'s1':'4; 1'})[0], 'ok')

    def test_system_single_solution(self):
        self.assertEqual(draft_mask('x=1; y=2', r'Решите систему $x+y=3$, $x-y=-1$.'),
                         '$x =${{range: 1}}, $y =${{range: 2}}')

    def test_ambiguous_system_is_not_cartesian_product(self):
        self.assertEqual(draft_mask('x=1; y=2; x=3; y=4', 'Решите систему x+y=5.'), '')

    def test_catheti_sorted_and_units_from_condition(self):
        mask = draft_mask('20 и 15', 'В прямоугольном треугольнике гипотенуза равна 25 см. Найдите катеты треугольника.')
        self.assertEqual(mask, 'Меньший катет равен {{number: 15}} см, больший катет равен {{number: 20}} см')

    def test_area_label_and_dimension(self):
        self.assertEqual(draft_mask('23', 'В ромбе ABCD сторона равна 5 см. Найдите площадь ромба ABCD.'),
                         '$S_{ABCD} =${{number: 23}} см$^2$')

    def test_no_invented_unit_or_reference(self):
        self.assertEqual(draft_mask('23', 'Найдите площадь ромба.'), '$S =${{number: 23}}')
        self.assertEqual(draft_mask('', 'В ромбе сторона равна 5 см. Найдите площадь ромба.'), '')
        self.assertEqual(draft_mask('15 и 20', 'Найдите площадь ромба.'), '')

    def test_no_context_keeps_old_api(self):
        self.assertEqual(draft_mask('4'), '{{number: 4}}')

    def test_finite_range_accepts_point_and_multiple_roots(self):
        mask = parse_mask('{{range: 4}}')
        self.assertTrue(mask.is_valid)
        self.assertEqual(check_mask(mask, {'s1': '[4;4]'})[0], 'ok')
        self.assertEqual(check_mask(mask, {'s1': '4;5'})[0], 'wrong')
        self.assertEqual(check_mask(parse_mask('{{range: 1,5}}'), {'s1': '1.5'})[0], 'ok')

    def test_system_preserves_pairs(self):
        mask = draft_mask('(1;2);(3;4)', 'Решите систему x+y=5.')
        self.assertEqual(mask, '$(x; y) =${{pair: (1;2);(3;4)}}')
        self.assertEqual(check_mask(parse_mask(mask), {'s1': '(1;4);(3;2)'})[0], 'wrong')

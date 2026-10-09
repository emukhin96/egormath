"""Повторённые единицы углов не меняют контекст соседних полей и формул."""
from unittest.mock import patch
from django.test import SimpleTestCase
from assignments.checks import formulas
from assignments.checks.mask import parse_mask, check_slot, check_mask


class DegreeUnitMaskTests(SimpleTestCase):
    def test_degree_suffix_belongs_only_to_its_own_slot(self):
        for suffix in ('°', r'$^{\circ}$', r'\(^{\circ}\)', r'$^\circ$', r'\degree'):
            with self.subTest(suffix=suffix):
                spec = parse_mask('{{number: 6}} см; {{expressions: 45; 90}}' + suffix)
                self.assertTrue(spec.is_valid)
                self.assertFalse(spec.slots[0].degree_unit)
                self.assertTrue(spec.slots[1].degree_unit)
        self.assertFalse(parse_mask('{{number: 90}}; угол в градусах °').slots[0].degree_unit)

    def test_numeric_angle_list_accepts_reordering_and_equivalents_with_units(self):
        slot = parse_mask(r'{{expressions: 70; 110}}$^{\circ}$').slots[0]
        for value in ('70;110', '110°;70°', r'110^{\circ};70^{\circ}',
                      r'\frac{140}{2}°;\sqrt{12100}°', '70;110°',
                      r'$70^{\circ}$;$110^{\circ}$'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')

    def test_wrong_list_and_undefined_division_stay_wrong(self):
        slot = parse_mask(r'{{expressions: 70; 110}}$^{\circ}$').slots[0]
        for value in ('70°;111°', '70°;70°', '70°;110°;110°',
                      '70+0/(1-1)°;110°', '-70°;110°', '70.000001°;110°'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_length_fields_do_not_inherit_degrees(self):
        spec = parse_mask(r'{{number: 6}} см; {{expressions: 45; 90}}$^{\circ}$')
        self.assertNotEqual(check_slot(spec.slots[0], '6°'), 'ok')
        self.assertEqual(check_slot(spec.slots[1], '90°;45°'), 'ok')
        lengths = parse_mask('{{expressions: 9; 14}} см').slots[0]
        self.assertNotEqual(check_slot(lengths, '9°;14°'), 'ok')

    def test_scalar_angle_literal_needs_no_process(self):
        slot = parse_mask(r'{{number: 90}}$^{\circ}$').slots[0]
        with patch.object(formulas, '_spawn') as spawn:
            self.assertEqual(check_slot(slot, '90°'), 'ok')
            self.assertEqual(check_slot(slot, r'91^{\circ}'), 'wrong')
        spawn.assert_not_called()

    def test_degree_of_trig_argument_is_not_removed(self):
        slot = parse_mask(r'{{number: 1/2}}$^{\circ}$').slots[0]
        self.assertEqual(check_slot(slot, r'\sin 30°'), 'ok')
        self.assertEqual(check_slot(slot, r'\sin(30°)'), 'ok')

    def test_after_worker_failure_degree_literal_still_checks(self):
        spec = parse_mask(r'{{expression: x}}; {{number: 90}}$^{\circ}$')
        with patch.object(formulas, 'check', side_effect=formulas.FormulaUnavailable('сбой')):
            with self.assertRaises(formulas.FormulaUnavailable) as caught:
                check_mask(spec, {'s1': 'x', 's2': '90°'})
        self.assertEqual(caught.exception.slot_checks, {'s1': 'unknown', 's2': 'ok'})

    def test_oversized_degree_input_does_not_start_process(self):
        slot = parse_mask(r'{{expressions: 70; 110}}$^{\circ}$').slots[0]
        with patch.object(formulas, '_spawn') as spawn:
            self.assertEqual(check_slot(slot, '1' * 301 + '°;110°'), 'unknown')
        spawn.assert_not_called()

    def test_nonangular_units_in_angle_fields_are_wrong_without_worker(self):
        for payload, values in [
            (r'{{number: 180}}$^{\circ}$',
             ('180см', '180 см', r'180\text{см}', r'180\mathrm{см}',
              '180м²', r'180\text{м}^2', '180км', '(90+90)см')),
            (r'{{expressions: 70; 110}}$^{\circ}$',
             ('70см;110', '70;110м', r'70;110\text{мм}')),
        ]:
            slot = parse_mask(payload).slots[0]
            with patch.object(formulas, '_spawn') as spawn:
                for value in values:
                    with self.subTest(payload=payload, value=value):
                        self.assertEqual(check_slot(slot, value), 'wrong')
            spawn.assert_not_called()

    def test_wrong_angle_unit_is_still_checked_after_worker_failure(self):
        spec = parse_mask(r'{{expression: x}}; {{number: 180}}$^{\circ}$')
        with patch.object(formulas, 'check', side_effect=formulas.FormulaUnavailable('сбой')):
            with self.assertRaises(formulas.FormulaUnavailable) as caught:
                check_mask(spec, {'s1': 'x', 's2': '180см'})
        self.assertEqual(caught.exception.slot_checks, {'s1': 'unknown', 's2': 'wrong'})

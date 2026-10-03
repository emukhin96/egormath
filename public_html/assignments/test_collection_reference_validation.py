"""Сохранённый числовой эталон должен проверяться ограниченным worker."""
from unittest.mock import patch
from django.test import SimpleTestCase
from assignments.checks import formulas
from assignments.checks.mask import check_slot, parse_mask, render_fragments


class CollectionReferenceValidationTests(SimpleTestCase):
    def test_literal_and_render_paths_do_not_start_worker(self):
        with patch.object(formulas, '_run_worker') as worker:
            for mask in ('{{set: 2;3}}', '{{set: }}', '{{pair: (2;3) | unordered}}'):
                self.assertTrue(parse_mask(mask, validate_references=True).is_valid)
            spec = parse_mask(r'{{set: \sqrt2;\sqrt3}}')
            self.assertTrue(spec.is_valid)
            render_fragments(spec, 'task')
            worker.assert_not_called()

    def test_unavailable_worker_blocks_saving_reference(self):
        for mask in (r'{{set: \sqrt2;\sqrt3}}',
                     r'{{pair: (\sqrt2;3) | unordered}}'):
            with patch.object(formulas, '_run_worker',
                              side_effect=formulas.FormulaUnavailable('занято')) as worker:
                spec = parse_mask(mask, validate_references=True)
            self.assertFalse(spec.is_valid)
            self.assertTrue(spec.slots[0].reference_unavailable)
            worker.assert_called_once()
            self.assertNotIn('value', worker.call_args.args[0])

    def test_original_undefined_reference_is_rejected(self):
        for value in ('sqrt(2)+0/0', 'sqrt(2)+0*sqrt(-1)', 'sqrt(2)+0*(0^0)'):
            spec = parse_mask('{{set: ' + value + ';3}}', validate_references=True)
            self.assertFalse(spec.is_valid, value)

    def test_long_radical_reference_and_reordered_answer_are_checkable(self):
        values = [r'\sqrt{' + str(k) + '}' for k in range(2, 23)]
        payload = ';'.join(values)
        spec = parse_mask('{{set: ' + payload + '}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        self.assertEqual(check_slot(spec.slots[0], ';'.join(reversed(values))), 'ok')
        self.assertEqual(check_slot(spec.slots[0], payload + ';sqrt(23)'), 'wrong')

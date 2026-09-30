"""Контекстная эквивалентность длин, площадей и наборов диагоналей."""
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
import json
import subprocess
import time
from django.test import SimpleTestCase
from django.template.loader import render_to_string

from assignments.checks.mask import check_slot, parse_mask, render_fragments
from assignments.checks import formulas


class FormulaMaskTests(SimpleTestCase):
    def setUp(self):
        formulas._worker_retry_at = 0

    def tearDown(self):
        formulas._worker_retry_at = 0

    def slot(self, text):
        spec = parse_mask(text)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_area_accepts_unreduced_equivalents(self):
        slot = self.slot(r'{{expression: 2R^2\sqrt{2} | positive: R}}')
        for value in (r'2\sqrt{2}R^2', r'R^2\sqrt{8}',
                      r'4R^2/\sqrt{2}', r'8(R^2\sqrt{2}/4)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in (r'2R\sqrt{2}', r'-2R^2\sqrt{2}', r'2a^2\sqrt{2}'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_hexagon_diagonals_are_an_unordered_multiset(self):
        slot = self.slot(r'{{expressions: a\sqrt{3}; 2a | positive: a}}')
        for value in (r'2a;a\sqrt{3}', r'\sqrt{3a^2};\sqrt{4a^2}',
                      r'a+a;3a/\sqrt{3}'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in ('2a;2a', '2a', r'a\sqrt{3};2a;2a', r'-2a;a\sqrt{3}'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')

    def test_assumptions_do_not_leak_between_tasks(self):
        positive = self.slot('{{expression: a | positive: a}}')
        real = self.slot('{{expression: a}}')
        self.assertEqual(check_slot(positive, r'\sqrt{a^2}'), 'ok')
        self.assertEqual(check_slot(real, r'\sqrt{a^2}'), 'wrong')
        with patch('sympy.core.expr.Expr.equals', return_value=None):
            reference, _ = formulas._parse_reference('a')
            self.assertEqual(formulas._check(r'\sqrt{a^2}', reference), 'wrong')

    def test_absolute_value_bars_are_not_option_separators(self):
        for reference, value in ((r'|a-1|', r'\sqrt{(a-1)^2}'),
                                 (r'\left|x\right|', r'\sqrt{x^2}'),
                                 (r'|a| | positive: a', 'a')):
            with self.subTest(reference=reference):
                slot = self.slot('{{expression: ' + reference + '}}')
                self.assertEqual(check_slot(slot, value), 'ok')
        slot = self.slot('{{expression: |a-1|}}')
        self.assertEqual(check_slot(slot, 'a-1'), 'wrong')

    def test_expanded_square_under_root_keeps_absolute_value_and_domain(self):
        slot = self.slot('{{expression: |x-1|}}')
        for value in (r'\sqrt{x^2-2x+1}', 'sqrt(x^2-2x+1)',
                      'sqrt((x-1)^2)', r'\sqrt{4x^2-8x+4}/2'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'ok')
        for value in ('x-1', r'-\sqrt{x^2-2x+1}',
                      r'\sqrt{x^2-2x+1}+1/(x-1)-1/(x-1)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')
        positive = self.slot('{{expression: x | positive: x}}')
        self.assertEqual(check_slot(positive, 'sqrt(sqrt(x^4))'), 'ok')

    def test_slow_input_is_bounded_and_timeout_does_not_poison_cache(self):
        reference, _ = formulas.parse_reference('a+17')
        formulas._checked.cache_clear()
        formulas._failed_inputs.clear()
        with patch.object(formulas, 'WORKER_TIMEOUT', 0.001):
            started = time.monotonic()
            # Таймаут — временная недоступность, а не вердикт
            with self.assertRaises(formulas.FormulaUnavailable):
                formulas.check('17+a', reference)
            self.assertLess(time.monotonic() - started, 1)
        # Пауза после сбоя — только для этого ввода: тот же ввод не форкает
        # процесс заново, другой ввод проверяется сразу.
        with patch.object(formulas.subprocess, 'run') as worker:
            with self.assertRaises(formulas.FormulaUnavailable):
                formulas.check('17+a', reference)
            worker.assert_not_called()
        self.assertEqual(formulas.check('a+17', reference), 'ok')
        # После паузы временный сбой не подменяет правильный вердикт.
        formulas._failed_inputs.clear()
        self.assertEqual(formulas.check('17+a', reference), 'ok')
        started = time.monotonic()
        try:
            slow = formulas.check('1/(a^97+a^13+3)', reference)
        except formulas.FormulaUnavailable:
            slow = 'unavailable'
        self.assertIn(slow, ('unknown', 'wrong', 'unavailable'))
        self.assertLess(time.monotonic() - started, formulas.WORKER_TIMEOUT + 1)

    def test_worker_failure_is_not_a_wrong_mathematical_answer(self):
        reference, _ = formulas.parse_reference('a+23')
        with patch.object(formulas, '_run_worker',
                          side_effect=subprocess.TimeoutExpired('worker', 3)):
            # Сбой вычислителя — не «unknown», а недоступность: вердикт не сохраняется
            with self.assertRaises(formulas.FormulaUnavailable):
                formulas.check('a+23', reference)
            slot = self.slot('{{expression: a+24}}')
            self.assertEqual(slot.reference, 'a+24')
            with self.assertRaises(formulas.FormulaUnavailable):
                check_slot(slot, '24+a')
            html = render_to_string('assignments/_mask.html', {
                'fragments': render_fragments(parse_mask('{{expression: a+24}}'), 'busy'),
                'editable': True})
            self.assertIn('<math-field', html)
        self.assertEqual(check_slot(slot, '24+a'), 'ok')

    def test_reference_resource_failure_is_retried_without_hiding_fields(self):
        with patch.object(formulas, '_run_worker', return_value={'unavailable': True}):
            slot = self.slot('{{expression: a+29 | positive: a}}')
            self.assertEqual(slot.reference, 'a+29')
            with self.assertRaises(formulas.FormulaUnavailable):
                check_slot(slot, '29+a')
        with patch.object(formulas, '_run_worker', return_value={'error': 'ошибка эталона'}) as worker:
            self.assertFalse(parse_mask('{{expression: a+29 | positive: a}}',
                                        validate_references=True).is_valid)
            worker.assert_called_once()
        formulas._reference_response.cache_clear()

    def test_render_of_cold_references_never_starts_worker(self):
        formulas._reference_response.cache_clear()
        with patch.object(formulas, '_run_worker') as worker:
            spec = parse_mask(r'{{expression: |x-1|}}; '
                              r'{{expressions: a\sqrt{3};2a | positive: a}}')
            self.assertTrue(spec.is_valid)
            html = render_to_string('assignments/_mask.html', {
                'fragments': render_fragments(spec, 'cold'), 'editable': True})
            self.assertEqual(html.count('<math-field'), 2)
            worker.assert_not_called()

    def test_reference_is_validated_before_save_and_failure_is_retryable(self):
        from django.core.exceptions import ValidationError
        from problems.forms import clean_mask_text
        from problems.textbook_import import normalize_answer_mask, TextbookImportError
        mask = '{{expression: a+43}}'
        formulas._reference_response.cache_clear()
        with patch.object(formulas, '_run_worker', return_value={'unavailable': True}):
            with self.assertRaisesMessage(ValidationError, 'повторите сохранение'):
                clean_mask_text(mask)
            with self.assertRaisesMessage(TextbookImportError, 'повторите сохранение'):
                normalize_answer_mask(mask)
            self.assertTrue(parse_mask(mask).is_valid)
        self.assertEqual(clean_mask_text(mask), mask)
        with patch.object(formulas, '_run_worker') as worker:
            self.assertEqual(clean_mask_text(mask), mask)
            worker.assert_not_called()
        for invalid in ('{{expression: 1/0}}', '{{expression: a | positive: b}}'):
            with self.assertRaises(ValidationError):
                clean_mask_text(invalid)

    def test_busy_worker_waits_then_reports_unavailable(self):
        reference, _ = formulas.parse_reference('a+47')
        formulas._failed_inputs.clear()
        # Все слоты заняты: ждём не дольше WORKER_WAIT и отказываем как
        # временно недоступную проверку, не запуская новый процесс.
        for _ in range(formulas.WORKER_PARALLEL):
            self.assertTrue(formulas._worker_slots.acquire(blocking=False))
        try:
            with patch.object(formulas, 'WORKER_WAIT', 0.05), \
                    patch.object(formulas.subprocess, 'run') as worker:
                with self.assertRaises(formulas.FormulaUnavailable):
                    formulas.check('47+a', reference)
                worker.assert_not_called()
        finally:
            for _ in range(formulas.WORKER_PARALLEL):
                formulas._worker_slots.release()
        # Занятость не запоминается как сбой ввода: следующая проверка идёт
        self.assertEqual(formulas.check('47+a', reference), 'ok')

    def test_unavailable_check_is_not_persisted_as_verdict(self):
        from django.utils import timezone
        from assignments.models import Submission
        spec = parse_mask('{{expression: a+24}}')
        name = spec.slots[0].name
        submission = Submission(answer_json={name: '24+a'})
        submission.auto_check, submission.check_json = 'ok', {name: 'ok'}
        checked_at = timezone.now()
        submission.checked_at = checked_at
        formulas._checked.cache_clear()
        with patch.object(formulas, '_run_worker',
                          side_effect=subprocess.TimeoutExpired('worker', 3)):
            self.assertFalse(submission.run_check(spec=spec))
        self.assertEqual(submission.auto_check, 'ok')
        self.assertEqual(submission.check_json, {name: 'ok'})
        self.assertEqual(submission.checked_at, checked_at)
        self.assertTrue(submission.check_unavailable)

    def test_parser_memory_failure_reaches_worker_as_temporary(self):
        from assignments.checks import expressions, formula_worker
        from lark.exceptions import VisitError
        parser, transformer = expressions._lark()
        for target, method, error in (
            (parser, 'doparse', MemoryError()),
            (transformer, 'transform', MemoryError()),
            (transformer, 'transform', VisitError('add', None, MemoryError())),
        ):
            with self.subTest(method=method, error=type(error).__name__):
                output = StringIO()
                # Тестируем протокол настоящего worker без изменения лимитов
                # текущего тестового процесса на Linux.
                with patch.object(formula_worker.sys, 'platform', 'test'), \
                     patch.object(formula_worker.sys, 'stdin', StringIO(json.dumps({
                         'payload': 'a+31', 'multiple': False}))), \
                     patch.object(target, method, side_effect=error), redirect_stdout(output):
                    formula_worker.main()
                self.assertEqual(json.loads(output.getvalue()), {'unavailable': True})

    def test_cancellation_cannot_hide_missing_parameter_values(self):
        slot = self.slot('{{expression: a | positive: a}}')
        for value in ('a(a-1)/(a-1)', r'a(a-1)^{-1}(a-1)',
                      r'a+\sqrt{a-1}^2-(a-1)',
                      r'a+\sqrt{a-1}\sqrt{a-1}-(a-1)',
                      'a+1/(a-1)-1/(a-1)'):
            with self.subTest(value=value):
                self.assertEqual(check_slot(slot, value), 'wrong')
        self.assertEqual(check_slot(slot, 'a^2/a'), 'ok')
        real = self.slot('{{expression: a}}')
        self.assertEqual(check_slot(real, 'a^2/a'), 'wrong')

    def test_domain_of_reference_is_respected(self):
        slot = self.slot('{{expression: (a^2-1)/(a-1)}}')
        self.assertEqual(check_slot(slot, 'a+1'), 'ok')
        self.assertEqual(check_slot(slot, '(a+1)(a-2)/(a-2)'), 'wrong')

    def test_simplification_preserves_endpoints_and_structural_requirement(self):
        slot = self.slot(r'{{simplify: 1+\sqrt{a-3}}}')
        for value in (r'\sqrt{a-3}+1', '(a-3)^{1/2}+1'):
            self.assertEqual(check_slot(slot, value), 'ok', value)
        for value in (r'1+(a-3)/\sqrt{a-3}', r'\sqrt{a-3}+a/a',
                      r'1+\sqrt{a-3}+1/(a-4)-1/(a-4)'):
            self.assertEqual(check_slot(slot, value), 'wrong', value)
        # Одинаковая формула в разных режимах не должна делить кэш вердиктов.
        free = self.slot('{{expression: 3x}}')
        strict = self.slot('{{simplify: 3x}}')
        self.assertEqual(check_slot(free, 'x+2x'), 'ok')
        self.assertEqual(check_slot(strict, 'x+2x'), 'wrong')

    def test_factoring_does_not_cancel_a_forbidden_point(self):
        slot = self.slot('{{factor: (x-1)(x+1)}}')
        self.assertEqual(check_slot(slot, '(x+1)(x-1)'), 'ok')
        self.assertEqual(check_slot(slot, 'x^2-1'), 'wrong')
        self.assertEqual(check_slot(slot, '((x-1)(x-2)/(x-2))(x+1)'), 'wrong')
        product = self.slot('{{factor: a*b}}')
        self.assertEqual(check_slot(product, 'a*b'), 'ok')
        self.assertEqual(check_slot(product, 'b*a'), 'ok')

    def test_multiple_parameter_rational_domains(self):
        for reference, value in (('a/b', 'a/b'), ('a/b+1', '(a+b)/b'),
                                 ('a/(b*c)', 'a/b/c'), ('a*b^{-1}', 'a/b')):
            slot = self.slot('{{simplify: ' + reference + '}}')
            self.assertEqual(check_slot(slot, value), 'ok', (reference, value))
        slot = self.slot('{{expression: a/b}}')
        self.assertEqual(check_slot(slot, 'a*(a-1)/(b*(a-1))'), 'wrong')
        for kind, reference, value in (
                ('factor', '(a+b)*(a-b)', r'(a+b+\frac0a)*(a-b)'),
                ('expression', 'a+b', r'a+b+\frac0a'),
                ('expression', 'a', r'a+\frac0a')):
            slot = self.slot('{{' + kind + ': ' + reference + '}}')
            self.assertEqual(check_slot(slot, value), 'wrong', value)

    def test_strict_expression_render_is_lightweight_and_save_validates(self):
        formulas._reference_response.cache_clear()
        with patch.object(formulas, '_run_worker') as worker:
            spec = parse_mask('{{simplify: 1/(a+b)}};{{factor: (x-1)(x+1)}}')
            self.assertTrue(spec.is_valid)
            html = render_to_string('assignments/_mask.html', {
                'fragments': render_fragments(spec, 'strict'), 'editable': True})
            self.assertEqual(html.count('<math-field'), 2)
            worker.assert_not_called()
        for kind in ('simplify', 'factor'):
            self.assertFalse(parse_mask('{{' + kind + ': 1/0}}',
                                        validate_references=True).is_valid)

    def test_strict_structure_keeps_assumptions_and_pi(self):
        for reference, value in ((r'\sqrt{a^2}+b | positive: a,b', 'a+b'),
                                 (r'\pi*a', r'a*\pi')):
            slot = self.slot('{{simplify: ' + reference + '}}')
            self.assertEqual(check_slot(slot, value), 'ok', value)

    def test_zero_power_keeps_school_domain_before_evaluation(self):
        for kind in ('expression', 'simplify'):
            slot = self.slot('{{' + kind + ': a+b+1}}')
            self.assertEqual(check_slot(slot, 'a^0+a+b'), 'wrong')
            self.assertFalse(parse_mask('{{' + kind + ': 0^0}}',
                                        validate_references=True).is_valid)
        free = self.slot('{{expression: a+1 | positive: a}}')
        strict = self.slot('{{simplify: a+1 | positive: a}}')
        self.assertEqual(check_slot(free, 'a+a^0'), 'ok')
        self.assertEqual(check_slot(strict, 'a+a^0'), 'wrong')

    def test_multiple_positive_parameters_and_pi(self):
        slot = self.slot(r'{{expression: a*b/2 | positive: a,b}}')
        self.assertEqual(check_slot(slot, 'b*a/2'), 'ok')
        self.assertEqual(check_slot(slot, r'\sqrt{a^2}b/2'), 'ok')
        circle = self.slot(r'{{expression: \pi R^2 | positive: R}}')
        self.assertEqual(check_slot(circle, r'R^2\pi'), 'ok')
        self.assertEqual(check_slot(circle, '3.14R^2'), 'wrong')

    def test_bad_reference_and_untrusted_input(self):
        for mask in ('{{expression: a | positive: b}}',
                     '{{expressions: a;;b}}', '{{expression: 1/0}}',
                     '{{expression: a | positive: a>0}}'):
            with self.subTest(mask=mask):
                self.assertFalse(parse_mask(mask, validate_references=True).is_valid)
        slot = self.slot('{{expression: a}}')
        self.assertEqual(check_slot(slot, '__import__("os").getcwd()'), 'unknown')

    def test_render_does_not_expose_reference_or_assumptions(self):
        spec = parse_mask(r'Диагонали: {{expressions: a\sqrt{3};2a | positive: a}}')
        html = render_to_string('assignments/_mask.html', {
            'fragments': render_fragments(spec, 'test'), 'editable': True})
        self.assertIn('<math-field', html)
        self.assertIn('выражения в любом порядке', html)
        self.assertNotIn('positive:', html)
        self.assertNotIn(r'\sqrt{3}', html)

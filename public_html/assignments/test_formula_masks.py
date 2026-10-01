"""Контекстная эквивалентность длин, площадей и наборов диагоналей."""
from unittest.mock import patch, Mock
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
        with patch.object(formulas, '_spawn') as worker:
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
            with self.assertRaisesMessage(TextbookImportError, 'Повторите загрузку позже'):
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
                    patch.object(formulas, '_spawn') as worker:
                with self.assertRaises(formulas.FormulaUnavailable):
                    formulas.check('47+a', reference)
                worker.assert_not_called()
        finally:
            for _ in range(formulas.WORKER_PARALLEL):
                formulas._worker_slots.release()
        # Занятость не запоминается как сбой ввода: следующая проверка идёт
        self.assertEqual(formulas.check('47+a', reference), 'ok')

    def test_draft_wait_policy_is_local_and_restored(self):
        from contextvars import Context
        from assignments.checks.mask import draft_mask
        formulas._checked.cache_clear()
        formulas._failed_inputs.clear()
        with patch.object(formulas, '_worker_slots') as slots, \
                patch.object(formulas, '_spawn') as worker:
            slots.acquire.return_value = False
            self.assertEqual(draft_mask('a+137'), '')
            slots.acquire.assert_called_once_with(timeout=0)
            with self.assertRaises(formulas.FormulaBusy):
                formulas._run_worker({'payload': 'a+139'})
            self.assertEqual(slots.acquire.call_args.kwargs, {'timeout': formulas.WORKER_WAIT})
            with formulas.without_worker_wait():
                with self.assertRaises(formulas.FormulaBusy):
                    Context().run(formulas._run_worker, {'payload': 'a+149'})
                self.assertEqual(slots.acquire.call_args.kwargs, {'timeout': formulas.WORKER_WAIT})
            worker.assert_not_called()

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
        # Прежний вердикт цел, к нему добавлен только счётчик сбоев ввода
        self.assertEqual(submission.check_json, {name: 'ok', formulas.UNAVAILABLE_KEY: 1})
        self.assertEqual(submission.checked_at, checked_at)
        self.assertTrue(submission.check_unavailable)

    def test_repeated_failure_of_same_input_goes_to_manual_check(self):
        from assignments.models import Submission
        spec = parse_mask('{{expression: a+25}}')
        name = spec.slots[0].name
        submission = Submission(answer_json={name: '25+a'})
        formulas._checked.cache_clear()
        formulas._failed_inputs.clear()
        # Занятость воркеров — не сбой ввода: счётчик не растёт
        with patch.object(formulas, '_run_worker', side_effect=formulas.FormulaBusy('занято')):
            self.assertFalse(submission.run_check(spec=spec))
        self.assertTrue(submission.check_unavailable)
        self.assertEqual(submission.check_json, {formulas.UNAVAILABLE_KEY: 0})
        with patch.object(formulas, '_run_worker',
                          side_effect=subprocess.TimeoutExpired('worker', 3)):
            self.assertFalse(submission.run_check(spec=spec))
            self.assertEqual(submission.check_json, {formulas.UNAVAILABLE_KEY: 1})
            self.assertIsNone(submission.checked_at)
            # Повторный сбой того же ввода — не временная недоступность:
            # ответ уходит в ручную проверку и больше не пересверяется.
            self.assertTrue(submission.run_check(spec=spec))
        self.assertFalse(submission.check_unavailable)
        self.assertEqual(submission.auto_check, 'unknown')
        self.assertEqual(submission.check_json, {'s1': 'unknown', formulas.UNAVAILABLE_KEY: 2})
        self.assertIsNotNone(submission.checked_at)

    def test_check_mask_reuses_results_of_unchanged_slots(self):
        from assignments.checks import check_mask
        spec = parse_mask('{{expression: a+26}}; {{number: 3}}')
        formulas._checked.cache_clear()
        with patch.object(formulas, '_run_worker') as worker:
            overall, per_slot = check_mask(spec, {'s1': '26+a', 's2': '3'},
                                           known={'s1': 'wrong'})
            worker.assert_not_called()
        self.assertEqual((overall, per_slot), ('wrong', {'s1': 'wrong', 's2': 'ok'}))

    def test_parser_memory_failure_reaches_worker_as_temporary(self):
        from assignments.checks import expressions, formula_worker
        from lark.exceptions import VisitError
        parser, transformer = expressions._lark()
        for target, method, error in (
            (parser.parser, 'parse', MemoryError()),
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

    def test_raw_tree_does_not_change_sympy_parser_transformation(self):
        from assignments.checks import expressions
        from sympy.parsing.latex import parse_latex
        from sympy import Symbol
        self.assertEqual(parse_latex('x+1', backend='lark'), Symbol('x') + 1)
        self.assertTrue(expressions._is_tree(expressions.raw_tree('x+1')))
        self.assertEqual(parse_latex('x+1', backend='lark'), Symbol('x') + 1)

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


class FormulaForkTests(SimpleTestCase):
    def test_preloaded_process_preserves_equivalence_and_missing_points(self):
        from assignments.checks import formula_fork
        cases = (('6a/8', 'ok'), ('0.75a', 'ok'), ('3sqrt(a^2)/4', 'ok'),
                 ('3a^2/(4a)', 'ok'), ('3a*(a-1)/(4*(a-1))', 'wrong'),
                 ('3a/2', 'wrong'))
        for value, expected in cases:
            with self.subTest(value=value):
                result = formula_fork.run_worker(json.dumps({
                    'payload': '3a/4 | positive: a', 'multiple': False,
                    'mode': 'expression', 'value': value}), 3)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)['status'], expected)

    def test_failed_warmup_waits_then_retries(self):
        from assignments.checks import formula_fork
        with patch.object(formula_fork, '_ready', False), \
                patch.object(formula_fork, '_failed_until', 0), \
                patch.object(formula_fork.time, 'monotonic', side_effect=[100, 100, 105, 111]), \
                patch.object(formula_fork, '_run_process', side_effect=[
                    subprocess.CompletedProcess('worker', 0, '{"unavailable":true}'),
                    subprocess.CompletedProcess('worker', 0, '{"display":"x"}')]) as run:
            with self.assertRaises(formula_fork.FormulaStartupUnavailable):
                formula_fork.warmup()
            self.assertFalse(formula_fork._ready)
            with self.assertRaises(formula_fork.FormulaStartupUnavailable):
                formula_fork.warmup()
            self.assertEqual(run.call_count, 1)
            formula_fork.warmup()
            self.assertTrue(formula_fork._ready)
            self.assertEqual(run.call_count, 2)

    def test_requests_do_not_queue_behind_warmup(self):
        from assignments.checks import formula_fork
        with patch.object(formula_fork, '_ready', False), \
                patch.object(formula_fork, '_run_process') as run:
            with formula_fork._startup_lock:
                with self.assertRaises(formula_fork.FormulaStartupUnavailable):
                    formula_fork.warmup()
            run.assert_not_called()

    def test_startup_failure_does_not_block_input_or_take_worker_slot(self):
        from assignments.checks import formula_fork
        payload = {'payload': '3a/4', 'multiple': False}
        for error in (OSError('forkserver'), ValueError('json'),
                      subprocess.TimeoutExpired('startup', 10),
                      formula_fork.FormulaStartupUnavailable('startup')):
            with self.subTest(error=type(error).__name__), \
                    patch.object(formulas.sys, 'platform', 'linux'), \
                    patch.object(formula_fork, 'warmup', side_effect=error), \
                    patch.object(formula_fork, 'run_worker') as run, \
                    patch.object(formulas, '_worker_slots') as slots, \
                    patch.object(formulas, '_remember_failure') as remember:
                with self.assertRaises(formulas.FormulaBusy) as failure:
                    formulas._run_worker(payload)
                # Отложенный запуск не расходует попытки автоматической
                # проверки и не отправляет неизменённый ответ на ручную.
                self.assertEqual(formulas.unavailable_count({}, failure.exception), 0)
                self.assertEqual(formulas.unavailable_count({'_unavailable': 1}, failure.exception), 1)
                slots.acquire.assert_not_called()
                slots.release.assert_not_called()
                remember.assert_not_called()
                run.assert_not_called()
                self.assertFalse(formulas._recently_failed(json.dumps(payload, sort_keys=True)))
        with patch.object(formulas.sys, 'platform', 'linux'), \
                patch.object(formula_fork, 'warmup'), \
                patch.object(formula_fork, 'run_worker', return_value=
                             subprocess.CompletedProcess('worker', 0, '{"display":"ok"}')):
            self.assertEqual(formulas._run_worker(payload), {'display': 'ok'})

    def test_start_failure_is_normalized_and_closes_connections(self):
        from assignments.checks import formula_fork
        for error in (EOFError('unexpected EOF'), RuntimeError('forkserver')):
            with self.subTest(error=type(error).__name__):
                context = Mock()
                receiver, sender, child = Mock(), Mock(), Mock()
                context.Pipe.return_value = (receiver, sender)
                context.Process.return_value = child
                child.start.side_effect = error
                with patch.object(formula_fork.multiprocessing, 'get_context', return_value=context), \
                        patch.object(formula_fork, '_ready', True), \
                        patch.object(formula_fork, '_failed_until', 0):
                    with self.assertRaises(formula_fork.FormulaStartupUnavailable) as failure:
                        formula_fork._run_process('{}', 3)
                self.assertIs(failure.exception.__cause__, error)
                receiver.close.assert_called_once()
                sender.close.assert_called_once()
                child.close.assert_called_once()
                child.kill.assert_not_called()
                child.join.assert_not_called()

    def test_forkserver_eof_during_warmup_is_busy_and_retryable(self):
        from assignments.checks import formula_fork
        context = Mock()
        receiver, sender, child = Mock(), Mock(), Mock()
        context.Pipe.return_value = (receiver, sender)
        context.Process.return_value = child
        child.start.side_effect = EOFError('unexpected EOF')
        with patch.object(formulas.sys, 'platform', 'linux'), \
                patch.object(formula_fork, '_ready', False), \
                patch.object(formula_fork, '_failed_until', 0), \
                patch.object(formula_fork.time, 'monotonic', return_value=100), \
                patch.object(formula_fork.multiprocessing, 'get_context', return_value=context), \
                patch.object(formulas, '_worker_slots') as slots, \
                patch.object(formulas, '_remember_failure') as remember:
            with self.assertRaises(formulas.FormulaBusy) as failure:
                formulas._run_worker({'payload': 'x', 'multiple': False})
            self.assertEqual(formulas.unavailable_count({}, failure.exception), 0)
            self.assertFalse(formula_fork._ready)
            self.assertEqual(formula_fork._failed_until, 110)
            slots.acquire.assert_not_called()
            remember.assert_not_called()

    def test_failed_restart_does_not_remember_or_count_the_answer(self):
        from assignments.checks import formula_fork
        context = Mock()
        receiver, sender, child = Mock(), Mock(), Mock()
        context.Pipe.return_value = (receiver, sender)
        context.Process.return_value = child
        child.start.side_effect = EOFError('unexpected EOF')
        with patch.object(formulas.sys, 'platform', 'linux'), \
                patch.object(formula_fork, '_ready', True), \
                patch.object(formula_fork, '_failed_until', 0), \
                patch.object(formula_fork.time, 'monotonic', return_value=100), \
                patch.object(formula_fork.multiprocessing, 'get_context', return_value=context), \
                patch.object(formulas, '_worker_slots') as slots, \
                patch.object(formulas, '_remember_failure') as remember:
            with self.assertRaises(formulas.FormulaBusy) as failure:
                formulas._run_worker({'payload': 'x', 'multiple': False})
            self.assertEqual(formulas.unavailable_count({'_unavailable': 1}, failure.exception), 1)
            self.assertFalse(formula_fork._ready)
            self.assertEqual(formula_fork._failed_until, 110)
            slots.acquire.assert_called_once()
            slots.release.assert_called_once()
            remember.assert_not_called()

    def test_server_restart_time_does_not_consume_calculation_budget(self):
        from assignments.checks import formula_fork
        context = Mock()
        receiver, sender, child = Mock(), Mock(), Mock()
        context.Pipe.return_value = (receiver, sender)
        context.Process.return_value = child
        now = [100]
        child.start.side_effect = lambda: now.__setitem__(0, now[0] + 5)
        child.is_alive.return_value = False
        child.exitcode = 0
        receiver.poll.return_value = True
        receiver.recv.return_value = '{"display":"x"}'
        with patch.object(formula_fork.multiprocessing, 'get_context', return_value=context), \
                patch.object(formula_fork.time, 'monotonic', side_effect=lambda: now[0]):
            result = formula_fork._run_process('{}', 3)
        self.assertEqual(result.returncode, 0)
        receiver.poll.assert_called_once_with(3)
        self.assertEqual(child.join.call_args_list[0].args, (3,))

    def test_timeout_kills_and_reaps_the_child(self):
        from assignments.checks import formula_fork
        context = Mock()
        receiver, sender, child = Mock(), Mock(), Mock()
        context.Pipe.return_value = (receiver, sender)
        context.Process.return_value = child
        receiver.poll.return_value = False
        child.is_alive.return_value = True
        with patch.object(formula_fork.multiprocessing, 'get_context', return_value=context):
            with self.assertRaises(subprocess.TimeoutExpired):
                formula_fork._run_process('{}', 0.01)
        child.kill.assert_called_once()
        child.join.assert_called_once()
        child.close.assert_called_once()
        receiver.close.assert_called_once()

    def test_child_keeps_original_linux_resource_limits(self):
        from assignments.checks import formula_worker
        resource = Mock()
        with patch.object(formula_worker.sys, 'platform', 'linux'), \
                patch.dict('sys.modules', {'resource': resource}), \
                patch.object(formula_worker.sys, 'stdin', StringIO('{"payload":"x","multiple":false}')), \
                patch.object(formulas, '_parse_reference', return_value=(None, 'x')), \
                redirect_stdout(StringIO()):
            formula_worker.main()
        self.assertEqual(resource.setrlimit.call_args_list[0].args,
                         (resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2)))
        self.assertEqual(resource.setrlimit.call_args_list[1].args,
                         (resource.RLIMIT_CPU, (2, 3)))

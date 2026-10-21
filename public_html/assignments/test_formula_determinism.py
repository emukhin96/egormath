"""Один и тот же ответ — один и тот же вердикт в любом процессе.

Expr.equals и simplify в SymPy берут случайные точки из общего генератора
sympy.core.random, а порядок обхода множеств зависит от PYTHONHASHSEED.
Вычислитель засевает генератор в каждом вызове и запускается с
фиксированным зерном хэшей. Уравнения (``equation``) решают в процессе
приложения только точными преобразованиями, численное сравнение — в
вычислителе: сначала пробы в фиксированных точках, затем Expr.equals.
"""
import json
import os
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from django.test import SimpleTestCase

from .checks import formula_fork, formula_worker, formulas
from .checks.mask import check_mask, check_slot, parse_mask


class WorkerSeedTests(SimpleTestCase):
    def test_worker_reseeds_sympy_generator_on_every_call(self):
        from sympy.core import random as sympy_random
        from sympy.core.cache import clear_cache
        states = []
        for prior in (1, 41):
            sympy_random.seed(prior)
            clear_cache()
            # Протокол настоящего worker без лимитов текущего процесса.
            with patch.object(formula_worker.sys, 'platform', 'test'), \
                 patch.object(formula_worker.sys, 'stdin', StringIO(json.dumps({
                     'payload': r'\sqrt{x}', 'multiple': False, 'value': 'x^{1/2}'}))), \
                 redirect_stdout(StringIO()):
                formula_worker.main()
            states.append((sympy_random.rng.getstate(),
                           sympy_random._assumptions_rng.getstate()))
        self.assertEqual(states[0], states[1])

    def test_subprocess_worker_gets_fixed_hash_seed(self):
        with patch.object(formulas.sys, 'platform', 'darwin'), \
             patch.object(formulas.subprocess, 'run') as run:
            formulas._spawn('{}')
        self.assertEqual(run.call_args.kwargs['env']['PYTHONHASHSEED'],
                         formula_worker.HASH_SEED)

    def test_forkserver_starts_with_fixed_hash_seed(self):
        class FailingProcess:
            def __init__(self, target, args):
                pass

            def start(self):
                raise OSError('forkserver не запустился')

            def close(self):
                pass

        class Context:
            Process = FailingProcess

            def set_forkserver_preload(self, modules):
                pass

            def Pipe(self, duplex):
                return StringIO(), StringIO()

        environ = {k: v for k, v in os.environ.items() if k != 'PYTHONHASHSEED'}
        with patch.dict(os.environ, environ, clear=True), \
             patch.object(formula_fork, '_ready', False), \
             patch.object(formula_fork, '_failed_until', 0), \
             patch.object(formula_fork.multiprocessing, 'get_context', return_value=Context()):
            with self.assertRaises(formula_fork.FormulaStartupUnavailable):
                formula_fork._run_process('{}', 3)
            self.assertEqual(os.environ['PYTHONHASHSEED'], formula_worker.HASH_SEED)


class EquationDeterminismTests(SimpleTestCase):
    def setUp(self):
        formulas._checked.cache_clear()
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    def slot(self, payload):
        spec = parse_mask('{{equation: ' + payload + '}}', validate_references=True)
        self.assertTrue(spec.is_valid, spec.errors)
        return spec.slots[0]

    def test_rational_equations_are_decided_without_worker(self):
        # Раньше У43.7 получал «неверно» или «не распознано» в зависимости
        # от PYTHONHASHSEED процесса приложения.
        cases = ((r'R=\frac{3 h^{2}+a^{2}}{6 h}', (
                     (r'R=\frac{4 h^{2}+a^{2}}{6 h}', 'wrong'),
                     (r'6R=\frac{3h^2+a^2}{h}', 'ok'),
                     (r'R-\frac{h}{2}=\frac{a^2}{6h}', 'ok'))),
                 ('a=2', (('a=3', 'wrong'), ('2a=4', 'ok'))),
                 ('x-3y=2', (('x-3y=-2', 'wrong'), (r'y=\frac{x-2}{3}', 'ok'))))
        with patch.object(formulas, '_spawn') as spawn:
            for reference, verdicts in cases:
                slot = self.slot(reference)
                for value, expected in verdicts:
                    with self.subTest(reference=reference, value=value):
                        self.assertEqual(check_slot(slot, value), expected)
            spawn.assert_not_called()

    def test_identities_are_compared_by_worker(self):
        # sin²x + cos²x = 1 точными преобразованиями не видно: решает
        # Expr.equals в вычислителе.
        slot = self.slot(r'y=\sin^{2} x')
        with patch.object(formulas, '_spawn', wraps=formulas._spawn) as spawn:
            self.assertEqual(check_slot(slot, r'y=1-\cos^{2} x'), 'ok')
            self.assertEqual(check_slot(slot, r'y=\cos^{2} x'), 'wrong')
        self.assertEqual(spawn.call_count, 2)

    def test_trigonometric_wrong_answer_is_wrong_in_every_process(self):
        # 1990.ФФ.4 Ткачука: в процессе приложения неверный ответ получал
        # «не распознано» при пяти значениях PYTHONHASHSEED из шести.
        slot = self.slot(r'r=\frac{b \sin \alpha}{4 \sin (\alpha+\beta) \sin \beta}')
        for _ in range(2):
            formulas._checked.cache_clear()
            self.assertEqual(check_slot(
                slot, r'r=\frac{b \sin \alpha}{5 \sin (\alpha+\beta) \sin \beta}'), 'wrong')

    def test_numeric_refutation_skips_expensive_equals(self):
        # У26.3: раньше «не распознано» после секунды simplify в Expr.equals.
        from .checks import expressions
        reference = expressions.parse_expr(r'R=\frac{a b c}{4 \sqrt{p(p-a)(p-b)(p-c)}}')
        with patch.object(expressions, 'equal', side_effect=AssertionError('equals не нужен')):
            self.assertEqual(expressions.check_equation(
                r'R=\frac{a b c}{5 \sqrt{p(p-a)(p-b)(p-c)}}', reference), 'wrong')

    def test_numeric_refutation_keeps_principal_branch_identities(self):
        # Пробы — в (0; 1), как и у Expr.equals: arcsin(sin x) = x там верно.
        from .checks import expressions
        reference = expressions.parse_expr(r'y=\arcsin(\sin x)')
        self.assertNotEqual(expressions.check_equation('y=x', reference), 'wrong')
        self.assertEqual(expressions.check_equation('y=2x', reference), 'wrong')

    def test_failed_worker_keeps_exact_equation_verdicts(self):
        spec = parse_mask(r'{{expression: \sqrt{x}}} {{equation: a=2}} '
                          r'{{equation: y=\sin^{2} x}}')
        self.assertTrue(spec.is_valid, spec.errors)
        values = {'s1': 'x^{1/2}', 's2': 'a=3', 's3': r'y=1-\cos^{2} x'}
        with patch.object(formulas, '_spawn',
                          side_effect=formulas.FormulaUnavailable('занято')) as spawn:
            with self.assertRaises(formulas.FormulaUnavailable) as caught:
                check_mask(spec, values)
            spawn.assert_called_once()
        self.assertEqual(caught.exception.slot_checks,
                         {'s1': 'unknown', 's2': 'wrong', 's3': 'unknown'})

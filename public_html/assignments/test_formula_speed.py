"""Тяжёлые формульные маски: готовые деревья эталона и численный отказ."""
from contextlib import redirect_stdout
from io import StringIO
import json
import subprocess
from unittest.mock import patch

from django.test import SimpleTestCase

from assignments.check_answer import OK, UNKNOWN, WRONG
from assignments.checks import expressions, formula_worker, formulas, numeric_collections

# Длинные эталоны книги Ткачука: разбор эталона — до половины лимита вызова.
SOLID = (r'\frac{6 \sin (\alpha / 2)\left(1-\frac{4}{3} \sin ^{2}(\alpha / 2)\right)}'
         r'{\left(2 \sin (\alpha / 2)+\sqrt{1-\frac{4}{3} \sin ^{2}(\alpha / 2)}\right)^{2}}')
RIGHT_TRIANGLE = r'\frac{a b \sqrt{a^{2}+b^{2}}}{(a+b)\left(a+b+\sqrt{a^{2}+b^{2}}\right)} | positive: a,b'


def run_worker(payload):
    """Настоящий протокол worker в процессе теста, без лимитов Linux."""
    output = StringIO()
    with patch.object(formula_worker.sys, 'platform', 'test'), \
            patch.object(formula_worker.sys, 'stdin', StringIO(json.dumps(payload))), \
            redirect_stdout(output):
        formula_worker.main()
    return json.loads(output.getvalue())


class ReferenceTreeTests(SimpleTestCase):
    def setUp(self):
        formulas._reference_response.cache_clear()
        formulas._checked.cache_clear()
        with formulas._failed_lock:
            formulas._failed_inputs.clear()

    tearDown = setUp

    def test_tree_data_round_trip_keeps_meaning_and_domains(self):
        for text in (SOLID, r'2\ln 2-1', r'|a|b/(a+b)', r'\sin x\cos x',
                     r'x_{1}+\alpha_{2}', r'\sqrt[3]{x^{2}}+\frac{1}{x-1}', 'Q^{-2}'):
            with self.subTest(text=text):
                tree = expressions.resolved_tree(formulas._prepare(text))
                data = json.loads(json.dumps(expressions.tree_to_data(tree)))
                copy = expressions.tree_from_data(data)
                self.assertEqual(expressions.tree_to_data(copy), expressions.tree_to_data(tree))
                self.assertEqual(expressions.evaluate(copy), expressions.evaluate(tree))
                self.assertEqual(formulas._components(copy), formulas._components(tree))
                self.assertEqual(formulas._denominators(copy), formulas._denominators(tree))
        self.assertIsNone(expressions.tree_from_data(None))
        for broken in ({'d': 'add'}, ['SYMBOL'], [1, 'x'], 'x', {'d': 1, 'c': []}):
            with self.assertRaises(ValueError):
                expressions.tree_from_data(broken)

    def test_parse_memory_is_off_outside_worker(self):
        self.assertIsNone(expressions._resolved_trees)
        run_worker({'payload': 'a+31', 'multiple': False, 'value': '31+a'})
        self.assertIsNone(expressions._resolved_trees)

    def test_worker_exports_reference_trees_and_reuses_them(self):
        reference = run_worker({'payload': SOLID, 'multiple': False, 'mode': 'simplify'})
        self.assertNotIn('error', reference)
        self.assertIsInstance(reference['trees'], str)
        wrong = SOLID.replace('{4}{3}', '{5}{3}', 1)
        plain = run_worker({'payload': SOLID, 'multiple': False, 'mode': 'simplify',
                            'value': wrong})
        parsed = []
        original = expressions.raw_tree

        def raw_tree(text):
            parsed.append(text)
            return original(text)

        with patch.object(expressions, 'raw_tree', side_effect=raw_tree):
            ready = run_worker({'payload': SOLID, 'multiple': False, 'mode': 'simplify',
                                'value': wrong, 'trees': reference['trees']})
            exact = run_worker({'payload': SOLID, 'multiple': False, 'mode': 'simplify',
                                'value': SOLID, 'trees': reference['trees']})
        self.assertEqual(plain['status'], WRONG)
        self.assertEqual(ready, plain)
        self.assertEqual(exact['status'], OK)
        # Эталон и его имена не разбираются заново: только новый ввод
        # ученика, а совпавший с эталоном ввод — ни разу.
        self.assertEqual(len(parsed), 1)
        self.assertIn('5', parsed[0])
        # Проверка ответа деревья не отдаёт: ввод ученика не кэшируется.
        self.assertNotIn('trees', ready)

    def test_collection_reference_trees_are_reused(self):
        payload = r'\frac{\pi}{\sqrt{\pi^{2}+16}};-\frac{\sqrt{\pi^{2}+16}}{4}'
        reference = run_worker({'payload': payload, 'multiple': False, 'mode': 'set',
                                'numeric': True})
        self.assertIsInstance(reference['trees'], str)
        with patch.object(expressions, 'raw_tree', side_effect=AssertionError('разбор эталона')):
            result = run_worker({'payload': payload, 'multiple': False, 'mode': 'set',
                                 'numeric': True, 'trees': reference['trees'],
                                 'value': r'-\frac{\sqrt{\pi^{2}+16}}{4};\frac{\pi}{\sqrt{\pi^{2}+16}}'})
        self.assertEqual(result['status'], OK)

    def test_broken_or_large_trees_fall_back_to_parsing(self):
        for trees in ('{', '[]', json.dumps({'x': ['SYMBOL']}), 7):
            with self.subTest(trees=trees):
                result = run_worker({'payload': 'a+31', 'multiple': False,
                                     'value': '31+a', 'trees': trees})
                self.assertEqual(result['status'], OK)
        # Деревья до TREES_LIMIT читаются целиком, без обрезки JSON.
        padding = json.dumps({'x' * 50 + str(n): ['SYMBOL', 'x'] for n in range(700)})
        self.assertLess(len(padding), formula_worker.TREES_LIMIT)
        result = run_worker({'payload': 'a+31', 'multiple': False,
                             'value': '31+a', 'trees': padding})
        self.assertEqual(result['status'], OK)
        with patch.object(formula_worker, 'TREES_LIMIT', 10):
            self.assertIsNone(run_worker({'payload': SOLID, 'multiple': False})['trees'])

    def test_only_long_references_are_prepared_and_cached(self):
        calls = []

        def worker(payload):
            calls.append(payload)
            if 'value' not in payload:
                return {'display': payload['payload'], 'trees': '{"x":["SYMBOL","x"]}'}
            return {'status': OK}

        long_spec = formulas.FormulaSpec(SOLID, False, 'simplify')
        short_spec = formulas.FormulaSpec('a+17', False)
        with patch.object(formulas, '_run_worker', side_effect=worker):
            self.assertEqual(formulas.check('a', long_spec), OK)
            self.assertEqual(formulas.check('b', long_spec), OK)
            self.assertEqual(formulas.check('17+a', short_spec), OK)
        self.assertEqual([('value' in c, c.get('trees')) for c in calls], [
            (False, None), (True, '{"x":["SYMBOL","x"]}'),
            (True, '{"x":["SYMBOL","x"]}'), (True, None)])
        self.assertEqual(calls[0]['mode'], 'simplify')

    def test_failed_preparation_is_one_retryable_failure(self):
        spec = formulas.FormulaSpec(SOLID, False, 'simplify')
        with patch.object(formulas, '_spawn',
                          side_effect=subprocess.TimeoutExpired('worker', 3)) as spawn:
            with self.assertRaises(formulas.FormulaUnavailable):
                formulas.check('a', spec)
            spawn.assert_called_once()
            # Подготовка этого эталона недавно не удалась: не форкаем снова.
            with self.assertRaises(formulas.FormulaBusy):
                formulas.check('b', spec)
            spawn.assert_called_once()

    def test_failure_memory_ignores_trees(self):
        payload = {'payload': 'a+17', 'multiple': False, 'value': '17+a', 'trees': '{}'}
        with patch.object(formulas, '_spawn', side_effect=subprocess.TimeoutExpired('worker', 3)):
            with self.assertRaises(formulas.FormulaUnavailable):
                formulas._run_worker(payload)
        with patch.object(formulas, '_spawn') as spawn:
            with self.assertRaises(formulas.FormulaBusy):
                formulas._run_worker({**payload, 'trees': '{"x":["SYMBOL","x"]}'})
            spawn.assert_not_called()
        self.assertNotIn('trees', next(iter(formulas._failed_inputs)))


class NumericRejectionTests(SimpleTestCase):
    def check(self, value, payload, mode='expression', *, numeric=False, fast=True):
        reference, _ = formulas._parse_reference(payload, numeric=numeric)
        if fast:
            return formulas._check(value, reference, False, mode, numeric=numeric)
        with patch.object(formulas, '_differs', return_value=False):
            return formulas._check(value, reference, False, mode, numeric=numeric)

    def test_wrong_formula_is_rejected_without_simplify(self):
        wrong = (r'\frac{a b \sqrt{a^{2}+b^{2}}}{(a+b)\left(a+b+\sqrt{a^{2}+2b^{2}}\right)}',
                 r'\frac{a b}{a+b}', r'\frac{a+b}{2}')
        with patch('sympy.simplify', side_effect=AssertionError('simplify для неверного ответа')):
            for value in wrong:
                with self.subTest(value=value):
                    self.assertEqual(self.check(value, RIGHT_TRIANGLE, 'simplify'), WRONG)
            self.assertEqual(self.check(SOLID.replace('{4}{3}', '{5}{3}', 1), SOLID, 'simplify'), WRONG)
            number = r'\frac{2 \cos ^{2} \frac{\pi}{7} \sin \frac{2 \pi}{7}}{\frac{7}{4} \cot \frac{\pi}{7}-2 \cos ^{2} \frac{\pi}{7} \sin \frac{2 \pi}{7}}'
            self.assertEqual(self.check(number.replace('{7}{4}', '{8}{4}'), number, numeric=True), WRONG)

    def test_rejection_matches_full_comparison(self):
        cases = (
            (RIGHT_TRIANGLE, r'\frac{a b \sqrt{a^{2}+b^{2}}}{(a+b)^{2}+(a+b) \sqrt{a^{2}+b^{2}}}', 'expression'),
            (RIGHT_TRIANGLE, r'\frac{a b}{a+b+\sqrt{a^{2}+b^{2}}}', 'expression'),
            # Равны только на области эталона: вне её точки не годятся.
            (r'\sqrt{x}\cdot\sqrt{x}', '|x|', 'expression'),
            (r'\sqrt{x}\cdot\sqrt{x}', '-x', 'expression'),
            (r'\frac{a^{2}-1}{a-1}', 'a+1', 'expression'),
            (r'\frac{a^{2}-1}{a-1}', 'a-1', 'expression'),
            (r'\arcsin x', r'\frac{\pi}{2}-\arccos x', 'expression'),
            (r'\arcsin x', r'\arccos x', 'expression'),
            (r'\ln(x-2)+\ln(x+2)', r'\ln(x^{2}-4)', 'expression'),
            (r'\sqrt{a-2 b} | positive: a,b', r'\sqrt{a-2b}+0\cdot\sqrt{b-a}', 'expression'),
            (r'\frac{\sin 2 x}{\cos x}', r'2\sin x', 'expression'),
            (r'h/\cos\alpha | positive: h,\alpha | angle: \alpha<90', r'h\sqrt{1+\tan^{2}\alpha}', 'expression'),
            (r'h/\cos\alpha | positive: h,\alpha | angle: \alpha<90', r'h\sqrt{1+\sin^{2}\alpha}', 'expression'),
        )
        for payload, value, mode in cases:
            with self.subTest(payload=payload, value=value):
                full = self.check(value, payload, mode, fast=False)
                fast = self.check(value, payload, mode)
                # Численный отказ только ускоряет «неверно» и решает за
                # учителя лишь доказанно неверное: верный не становится иным.
                self.assertEqual(fast, full if full != UNKNOWN else fast)
                if full == UNKNOWN:
                    self.assertIn(fast, (UNKNOWN, WRONG))

    def test_sample_points_lie_in_reference_domain(self):
        reference, _ = formulas._parse_reference(r'\sqrt{a-2 b}+\arcsin\frac{b}{a} | positive: a,b')
        samples = formulas._sample_points(reference)
        self.assertTrue(samples)
        for point, values in samples:
            a, b = (point[s] for s in reference.symbols)
            self.assertGreater(a - 2 * b, 0)
            self.assertTrue(all(value.is_real for value in values.values()))
        # Область x > 2 у параметра без positive тоже находится.
        logarithms, _ = formulas._parse_reference(r'\ln(x-2)+\ln(x+2)')
        samples = formulas._sample_points(logarithms)
        self.assertTrue(samples)
        self.assertTrue(all(point[logarithms.symbols[0]] > 2 for point, _ in samples))
        # Два параметра без positive: есть точки с одинаковыми знаками.
        product, _ = formulas._parse_reference(r'\frac{2 R \sqrt{R r}}{R-r}')
        samples = formulas._sample_points(product)
        self.assertEqual(len(samples), formulas._SAMPLE_ENOUGH)
        self.assertTrue(all(point[product.symbols[0]] * point[product.symbols[1]] > 0
                            for point, _ in samples))
        # Число без параметров — одна точка, и большое число не «полюс».
        for text in (r'\sqrt{2}+\pi', r'3 \cdot 2^{1000}-4'):
            number, _ = formulas._parse_reference(text, numeric=True)
            self.assertEqual([point for point, _ in formulas._sample_points(number)], [{}])
        # Область эталона |x| ≤ 0,1 не содержит ни одной пробной точки:
        # отказа нет, решает полная проверка.
        narrow, _ = formulas._parse_reference(r'\sqrt{\frac{1}{100}-x^{2}}')
        self.assertEqual(formulas._sample_points(narrow), [])
        self.assertEqual(formulas._check('x', narrow), WRONG)

    def test_signed_collection_items_share_one_parse(self):
        for text, expected in ((r'x_{2}=-\frac{\pi}{\sqrt{\pi^{2}+16}}', ('-', r'\frac{\pi}{\sqrt{\pi^{2}+16}}')),
                               (r'+\sqrt[3]{2}', ('+', r'\sqrt[3]{2}')),
                               (r'-(1+\sqrt{2})', ('-', r'(1+\sqrt{2})')),
                               (r'-\frac{1}{2}^{2}', None), (r'-\frac{1}{2}+1', None),
                               (r'-\cos\frac{\pi}{3}', None), (r'-\sqrt{2}\sqrt{3}', None),
                               (r'\frac{1}{2}', None), (r'-\frac{1}{2', None)):
            with self.subTest(text=text):
                self.assertEqual(numeric_collections._signed_group(text), expected)
        parsed = []
        original = expressions.raw_tree

        def raw_tree(text):
            parsed.append(text)
            return original(text)

        with patch.object(expressions, 'raw_tree', side_effect=raw_tree):
            result = run_worker({'payload': r'\pm\frac{\pi}{\sqrt{\pi^{2}+16}}', 'multiple': False,
                                 'mode': 'set', 'numeric': True,
                                 'value': r'-\frac{\pi}{\sqrt{\pi^{2}+16}};\frac{\pi}{\sqrt{\pi^{2}+16}}'})
        self.assertEqual(result['status'], OK)
        self.assertEqual([text for text in parsed if len(text) > 1], [r'\frac{Q}{\sqrt{Q^{2}+16}}'])
        # Знак не скрывает недопустимую операцию внутри группы.
        self.assertEqual(numeric_collections.check(r'-\frac{1}{0};2', '1;2', kind='set'), WRONG)

    def test_collection_numbers_differ_without_simplify(self):
        from sympy import pi, sqrt
        with patch('sympy.simplify', side_effect=AssertionError('simplify для различных чисел')):
            self.assertFalse(numeric_collections._equal(sqrt(2) + sqrt(3), sqrt(5) + 1))
            self.assertFalse(numeric_collections._equal(pi / sqrt(pi**2 + 16), -pi / sqrt(pi**2 + 16)))
        self.assertTrue(numeric_collections._equal(sqrt(2) * sqrt(3), sqrt(6)))
        self.assertTrue(numeric_collections._equal(sqrt(3 + 2 * sqrt(2)), 1 + sqrt(2)))

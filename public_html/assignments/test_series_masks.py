"""Серии корней тригонометрических уравнений: arc-функции и (-1)^n."""
from django.test import SimpleTestCase
from .checks import parse_mask, check_slot
from .checks import series


class SeriesArcTests(SimpleTestCase):
    def assertEqualSeries(self, left, right, expected):
        with self.subTest(left=left, right=right):
            a, b = series.parse(left), series.parse(right)
            self.assertIsNotNone(a)
            self.assertIsNotNone(b)
            self.assertIs(series.equal(a, b), expected)

    def test_arc_constants(self):
        # Книжная запись и её равносильные формы: π - arccos x, arctg вместо arcctg.
        self.assertEqualSeries(r'\pm \arccos\left(-\frac{1}{5}\right)+2 n \pi, n \in \mathbf{Z}',
                               r'\pi-\arccos\frac15+2\pi k; -\pi+\arccos\frac{1}{5}+2\pi k', True)
        self.assertEqualSeries(r'\operatorname{arcctg} \frac{5 \pm \sqrt{33}}{2}+n \pi',
                               r'\operatorname{arctg}\frac{2}{5+\sqrt{33}}+\pi n; '
                               r'\operatorname{arctg}\frac{2}{5-\sqrt{33}}+\pi n', True)
        self.assertEqualSeries(r'\operatorname{arctg} 2+n\pi', r'\frac{\pi}{2}-\mathrm{arctg}\frac12+\pi n', True)
        self.assertEqualSeries(r'\arccos\frac{1}{5}+2\pi n', r'arctg(2\sqrt6)+2\pi n', True)
        self.assertEqualSeries(r'\frac{1}{2}\arcsin\frac{2}{3}+\frac{\pi n}{2}',
                               r'\frac12\arcsin\frac23+\pi n; \frac12\arcsin\frac23+\frac{\pi}{2}+\pi n', True)
        # Табличный угол сводится к рациональному кратному π.
        self.assertEqualSeries(r'\arcsin\frac{\sqrt3}{2}+2\pi n', r'\frac{\pi}{3}+2\pi n', True)
        self.assertEqualSeries(r'\operatorname{arctg} 2+n\pi, \operatorname{arctg}3+n\pi',
                               r'\operatorname{arctg}3+\pi n; \operatorname{arctg}2+\pi n', True)

    def test_arc_wrong(self):
        self.assertEqualSeries(r'\pm \arccos\left(-\frac{1}{5}\right)+2 n \pi',
                               r'\arccos\left(-\frac15\right)+2\pi n', False)
        self.assertEqualSeries(r'\pm\arccos\frac15+2\pi n', r'\pm\arccos\left(-\frac15\right)+2\pi n', False)
        self.assertEqualSeries(r'\operatorname{arctg} 2+n\pi', r'\operatorname{arctg}3+\pi n', False)
        self.assertEqualSeries(r'\operatorname{arctg} 2+n\pi', r'\operatorname{arctg}2+2\pi n', False)

    def test_dependent_constants_unknown(self):
        # arctg 3 = 3π/4 - arctg 2: разные записи констант с рациональной
        # разностью кратной π не сравниваются — решает учитель.
        a = series.parse(r'\operatorname{arctg}3+\pi n')
        b = series.parse(r'\frac{3\pi}{4}-\operatorname{arctg}2+\pi n')
        self.assertIsNone(series.equal(a, b))

    def test_sign_power(self):
        self.assertEqualSeries(r'(-1)^{n} \frac{\pi}{4}-\frac{\pi}{4}+n \pi, n \in \mathbf{Z}',
                               r'2\pi n; \frac{\pi}{2}+2\pi n', True)
        self.assertEqualSeries(r'x=(-1)^{n+1} \pi / 4+\pi n', r'-\pi/4+2\pi n; 5\pi/4+2\pi n', True)
        self.assertEqualSeries(r'(-1)^k\arcsin\frac13+\pi k',
                               r'\arcsin\frac13+2\pi n; \pi-\arcsin\frac13+2\pi n', True)
        self.assertEqualSeries(r'(-1)^n\arcsin\frac13+\pi n', r'\arcsin\frac13+\pi n', False)
        # (-1)^n в числителе дроби и в скобке.
        self.assertEqualSeries(r'\frac{(-1)^{n}}{2} \arcsin \frac{3}{4}+\frac{n \pi}{2}',
                               r'\frac12\arcsin\frac34+\pi n; \frac{\pi}{2}-\frac12\arcsin\frac34+\pi n', True)
        self.assertEqualSeries(r'\left((-1)^{n}-1\right) \frac{\pi}{8}+\frac{n \pi}{2}',
                               r'\pi n; \frac{\pi}{4}+\pi n', True)

    def test_several_pm(self):
        # Независимые знаки ± — все сочетания; пара ±/∓ — верхний с верхним.
        self.assertEqualSeries(r'\pm \arccos \left(\pm \frac{\sqrt{2}-1}{2}\right)+2 n \pi',
                               r'\pm\arccos\frac{\sqrt2-1}{2}+\pi n', True)
        self.assertEqualSeries(r'\pm\frac{\pi}{4}\mp\frac{\pi}{12}+2\pi n',
                               r'\frac{\pi}{6}+2\pi n; -\frac{\pi}{6}+2\pi n', True)
        self.assertEqualSeries(r'\pm\frac{\pi}{4}\pm\frac{\pi}{12}+2\pi n',
                               r'\frac{\pi}{6}+2\pi n; -\frac{\pi}{6}+2\pi n', False)
        self.assertIsNone(series.parse(r'\pm\pi\pm\pi\pm\pi\pm\pi+2\pi n'))

    def test_integer_clauses(self):
        self.assertEqualSeries(r'\pi+2 \pi n, \frac{\pi}{2}+\pi k, n, k \in \mathbf{Z}',
                               r'\pi+2\pi n; \pi/2+\pi n', True)
        self.assertEqualSeries(r'5 \pi / 6+2 \pi n\ (n \in \mathbf{Z})', r'5\pi/6+2\pi n', True)
        self.assertEqualSeries(r'\frac{\pi}{2}+\pi n, n \in \mathbf{Z} ; \pm \frac{\pi}{6}+\pi k, k \in \mathbf{Z}',
                               r'\pi/2+\pi n; \pi/6+\pi n; -\pi/6+\pi n', True)

    def test_letters_and_spacing(self):
        # Так набирает MathLive: буква параметра вплотную к \pi.
        self.assertEqualSeries(r'2k\pi', r'2\pi n', True)
        self.assertEqualSeries(r'(-1)^{k}\frac{\pi}{6}+k\pi', r'\frac{\pi}{6}+2\pi n; \frac{5\pi}{6}+2\pi n', True)
        self.assertEqualSeries(r'\frac{k\pi}{2}', r'\frac{\pi n}{2}', True)
        # Книжная запись дроби через пробел.
        self.assertEqualSeries(r'\frac{2}{5} n \pi', r'\frac{2\pi n}{5}', True)
        # После (-1)^n — явное умножение или деление.
        self.assertEqualSeries(r'(-1)^n*\pi/6+\pi n', r'\frac{\pi}{6}+2\pi n; \frac{5\pi}{6}+2\pi n', True)
        self.assertEqualSeries(r'(-1)^n/2\cdot\arcsin\frac34+\frac{\pi n}{2}',
                               r'\frac12\arcsin\frac34+\pi n; \frac{\pi}{2}-\frac12\arcsin\frac34+\pi n', True)

    def test_dependent_constants_same_record(self):
        # Корни a sin x + b cos x = c: две константы связаны, но одинаковая
        # запись всё равно совпадает сама с собой.
        text = r'2\operatorname{arctg}\frac{10\pm\sqrt{87}}{\sqrt{29}-4}+2n\pi'
        self.assertEqualSeries(text, text, True)

    def test_rejects_unsupported(self):
        for value in (r'\arcsin 2+\pi n', r'\arcsin x+\pi n', r'2^n\pi', r'(-1)^n(-1)^n\pi',
                      # Степени не разбираются: 9^{9^9} считалась бы без лимита времени.
                      r'9^{9^{9}}+\pi n', r'2^{10^{10}}\pi+\pi n', r'\pi^{2}+\pi n',
                      # Много корней в аргументе — minimal_polynomial большой степени.
                      r'\operatorname{arctg}(\sqrt2+\sqrt3+\sqrt5+\sqrt7+\sqrt{11})+\pi n',
                      r'\arcsin\frac{\sqrt[3]{2}}{2}+\pi n',
                      r'\sin 1+\pi n', r'\operatorname{arctg}(n)+\pi n', r'\log 2+\pi n'):
            with self.subTest(value=value):
                self.assertIsNone(series.parse(value))

    def test_mask_slot(self):
        spec = parse_mask(r'$x =$ {{series: \pm \arccos\left(-\frac{1}{5}\right)+2 n \pi}}, $n \in \mathbb{Z}$',
                          validate_references=True)
        self.assertTrue(spec.is_valid)
        slot = spec.slots[0]
        self.assertEqual(check_slot(slot, r'\pm\arccos\left(-\frac{1}{5}\right)+2\pi n'), 'ok')
        self.assertEqual(check_slot(slot, r'\pi-\arccos\frac15+2\pi k;\arccos\frac15-\pi+2\pi k'), 'ok')
        self.assertEqual(check_slot(slot, r'\pm\arccos\frac{1}{5}+2\pi n'), 'wrong')
        self.assertEqual(check_slot(slot, r'\arcsin\frac15+2\pi n'), 'wrong')
        spec = parse_mask(r'{{series: (-1)^{n} \frac{\pi}{6}+n \pi}}', validate_references=True)
        slot = spec.slots[0]
        self.assertEqual(check_slot(slot, r'\frac{\pi}{6}+2\pi n; \frac{5\pi}{6}+2\pi n'), 'ok')
        self.assertEqual(check_slot(slot, r'(-1)^{k}\frac{\pi}{6}+\pi k'), 'ok')
        self.assertEqual(check_slot(slot, r'\pm\frac{\pi}{6}+2\pi n'), 'wrong')

    def test_slot_is_formula_field(self):
        # π, дроби и (-1)^n набираются в поле формулы, а не в поле «число».
        from django.template.loader import render_to_string
        from .checks import render_fragments, slot_display
        spec = parse_mask(r'$x =$ {{series: \frac{\pi}{4}+\pi n}}')
        html = render_to_string('assignments/_mask.html', {
            'fragments': render_fragments(spec, 'p1'), 'editable': True})
        self.assertIn('<math-field data-mirror="p1_s1"', html)
        self.assertNotIn('placeholder="число"', html)
        self.assertEqual(slot_display(spec.slots[0], r'\frac{\pi}{4}+\pi n'), r'$\frac{\pi}{4}+\pi n$')

"""Равносильные записи школьных числовых множеств и линейных неравенств."""
from unittest.mock import patch

from django.test import SimpleTestCase

from .checks.mask import check_slot, parse_mask
from .checks.sets import parse_range, parse_set, ranges_equal


class RangeNotationTests(SimpleTestCase):
    def assertEquivalent(self, actual, reference):
        parsed = parse_range(actual)
        self.assertIsNotNone(parsed, actual)
        self.assertTrue(ranges_equal(parsed, parse_range(reference)), actual)

    def test_finite_commas_are_not_decimals(self):
        for value in ('{0,1}', r'\{0,1\}', r'\left\{0,1\right\}', '{1,0,1}',
                      r'\displaystyle\{0,1\}', r'\displaystyle {0,1}',
                      r'\,\{0,1\}', r'(\{0,1\})',
                      r'\left(\left\{0,1\right\}\right)'):
            with self.subTest(value=value):
                self.assertEquivalent(value, '0;1')
                self.assertFalse(ranges_equal(parse_range(value), parse_range('0.1')))
                self.assertEqual(set(parse_set(value)), {0, 1})
        self.assertEquivalent('{0,2}', '0;2')
        self.assertEquivalent('{(0,5);1}', '0.5;1')
        self.assertEquivalent(r'{\left(0,5\right);1}', '0.5;1')
        self.assertIsNone(parse_range(r'\frac{\{0,1\}}2'))
        self.assertEquivalent('0,5', '0.5')
        self.assertEquivalent(r'\{0{,}5;1{,}5\}', '0.5;1.5')
        self.assertEquivalent(r'\{\frac{0,5}{2};1\}', '0.25;1')
        self.assertEquivalent('{0,1}∪{2,3}', '0;1;2;3')
        self.assertEquivalent('x∈{0,1}', '0;1')

    def test_complement_of_finite_set(self):
        expected = '(-∞;0)∪(0;1)∪(1;∞)'
        for value in (r'R\setminus\{0;1\}',
                      r'x\in\mathbb{R}\backslash\left\{0,1\right\}',
                      r'\mathbb R\setminus{1,0}', 'ℝ∖{0;1}'):
            with self.subTest(value=value):
                self.assertEquivalent(value, expected)
        self.assertEquivalent(r'R\setminus{}', 'R')
        self.assertEquivalent(r'R\setminus{0;1} и x>=0', '(0;1)∪(1;∞)')
        self.assertEquivalent(r'R\setminus{0}∪{0}', 'R')
        self.assertEquivalent(r'R\setminus{-\sqrt2;\sqrt2}', r'(-∞;-\sqrt2)∪(-\sqrt2;\sqrt2)∪(\sqrt2;∞)')
        for value in (r'Z\setminus{0}', r'R\setminus Q', r'R\setminus{a}'):
            with self.subTest(value=value):
                self.assertIsNone(parse_range(value))

    def test_plus_minus_inside_one_item(self):
        self.assertEquivalent(r'1;(-1±\sqrt5)/2', r'1;(-1+\sqrt5)/2;(-1-\sqrt5)/2')
        self.assertEquivalent(r'2;3;\frac{5\pm\sqrt{89}}{2}',
                              r'2;3;(5+\sqrt{89})/2;(5-\sqrt{89})/2')
        self.assertEquivalent(r'x=\pm3', '-3;3')
        self.assertEquivalent('±0', '0')
        for value in ('1/(1±1)', '1±2±3'):
            self.assertIsNone(parse_range(value), value)

    def test_transformed_affine_inequalities(self):
        groups = {
            'm<-2': ['2m<-4', 'm+2<0', '-4>2m', '2(m+1)<-2'],
            'a<=1': ['-a>=-1', '2a-3<=-1', '(a+1)/2<=1',
                     r'\frac{a+1}{2}<=1'],
            'a<2': [r'\frac24a<1', '0,5a<1'],
            'R': ['m-m<1', 'm-m=0'],
            '∅': ['m-m>1', 'm-m!=0'],
            '(-3;-2)': ['2m<-4 и m>-3'],
            '(-2;2]': ['x+1<2x+3<=7'],
            '2': ['2x=4'],
            '(-∞;2)∪(2;∞)': ['2x!=4'],
        }
        for reference, values in groups.items():
            for value in values:
                with self.subTest(value=value):
                    self.assertEquivalent(value, reference)
        for value in ('x^2<1', '1/x>0', 'x/x>0', 'x+y<1',
                      '(x-1)/(x-1)>0', 'x<y', 'x/0>1',
                      'x<x/x', 'x<=x/x', r'x<\sqrt{x}^2-x+1', 'x<y=2'):
            with self.subTest(value=value):
                self.assertIsNone(parse_range(value))

    def test_mask_accepts_alternatives_and_rejects_wrong_boundaries(self):
        cases = [
            ('{{range: 0;1}}', '{0,1}', 'ok'),
            ('{{range: 0;1}}', '0.1', 'wrong'),
            ('{{set: 0;1}}', '{0,1}', 'ok'),
            ('{{range: m<-2}}', '2(m+1)<-2', 'ok'),
            ('{{range: m<-2}}', '2m<=-4', 'wrong'),
            ('{{range: a<=1}}', '-a>=-1', 'ok'),
            ('{{range: a<=1}}', '-a>-1', 'wrong'),
            ('{{range: (-∞;0)∪(0;∞)}}', r'R\setminus{0}', 'ok'),
            ('{{range: (-∞;0)∪(0;∞)}}', 'R', 'wrong'),
            ('{{range: -3;3}}', '±3', 'ok'),
            ('{{range: -3;3}}', '3', 'wrong'),
        ]
        for mask, answer, expected in cases:
            with self.subTest(mask=mask, answer=answer):
                spec = parse_mask(mask)
                self.assertTrue(spec.is_valid, spec.errors)
                self.assertEqual(check_slot(spec.slots[0], answer), expected)

    def test_reserved_markers_and_size_limits(self):
        for value in ('\x00999\x00', '1'*2001,
                      '{'*17+'1'+'}'*17, ';'.join(['1']*65)):
            with self.subTest(value=repr(value)):
                with patch('assignments.checks.sets.numeric_value',
                           side_effect=AssertionError('До вычислителя доходить не должно')):
                    self.assertIsNone(parse_range(value))

    def test_plus_minus_expansion_limit(self):
        for parser in (parse_set, parse_range):
            self.assertIsNone(parser(';'.join('±'+str(i) for i in range(1, 65))))
            self.assertEqual(len(parser(';'.join('±'+str(i) for i in range(1, 33)))), 64)

    def test_bounds_with_nested_brackets_and_quad(self):
        # Эталоны методического пособия Шабунина (партия 45): корни n-й
        # степени, скобки и \quad внутри записи промежутка.
        groups = {
            r'[-\sqrt{5};-\sqrt[3]{10})\cup(0;\sqrt{5})':
                [r'[-\sqrt5;-10^{1/3})∪(0;\sqrt{5})',
                 r'x\in\left[-\sqrt{5};-\sqrt[3]{10}\right)\cup\left(0;\sqrt{5}\right)'],
            r'\left[-\frac{4}{9};\frac{\sqrt[3]{9}-1}{2}\right]':
                [r'[-4/9;(9^{1/3}-1)/2]'],
            r'[-2;0,5(\sqrt{17}+5))': [r'[-2;\frac{\sqrt{17}+5}{2})'],
            r'[0;(\log_3 2)^2)\cup(1,5;+\infty)':
                [r'[0;(\log_{3}2)^{2})\cup(1.5;\infty)', r'[0;(\log_3 2)^2) \cup (\frac32;+∞)'],
            r'(-\infty;-1) \quad \cup \quad (0,5;+\infty)':
                [r'(-∞;-1)∪(0,5;+∞)', r'(-\infty;-1)\qquad\cup\qquad(0.5;+\infty)',
                 r'x<-1 или x>0,5'],
        }
        for reference, values in groups.items():
            self.assertIsNotNone(parse_range(reference), reference)
            for value in values:
                with self.subTest(value=value):
                    self.assertEquivalent(value, reference)
        for value, reference in (
                (r'[-\sqrt{5};-\sqrt[3]{9})\cup(0;\sqrt{5})',
                 r'[-\sqrt{5};-\sqrt[3]{10})\cup(0;\sqrt{5})'),
                (r'(-\sqrt{5};-\sqrt[3]{10})\cup(0;\sqrt{5})',
                 r'[-\sqrt{5};-\sqrt[3]{10})\cup(0;\sqrt{5})'),
                (r'[-2;0,5(\sqrt{17}+3))', r'[-2;0,5(\sqrt{17}+5))'),
                (r'[0;(\log_3 2)^3)\cup(1,5;+\infty)',
                 r'[0;(\log_3 2)^2)\cup(1,5;+\infty)')):
            with self.subTest(value=value):
                parsed = parse_range(value)
                self.assertIsNotNone(parsed, value)
                self.assertFalse(ranges_equal(parsed, parse_range(reference)))
        # Разделитель «;» — только на верхнем уровне и ровно один;
        # скобки внутри границы должны быть сбалансированы.
        for value in (r'[0;(1;2))', r'[0;1;2]', r'[0;(2)', r'[0;\sqrt[3{2}]',
                      r'(0;\quadrilateral)', '(;1)', '(1;)'):
            with self.subTest(value=value):
                self.assertIsNone(parse_range(value))

    def test_mask_with_nested_bounds(self):
        cases = [
            (r'{{range: [-\sqrt{5};-\sqrt[3]{10})\cup(0;\sqrt{5})}}',
             r'[-\sqrt{5};-\sqrt[3]{10})\cup(0;\sqrt{5})', 'ok'),
            (r'{{range: [-\sqrt{5};-\sqrt[3]{10})\cup(0;\sqrt{5})}}',
             r'[-\sqrt{5};-\sqrt[3]{10}]\cup(0;\sqrt{5})', 'wrong'),
            (r'{{range: \left[-\frac{4}{9};\frac{\sqrt[3]{9}-1}{2}\right]}}',
             r'\left[-\frac{4}{9};\frac{\sqrt[3]{9}-1}{2}\right]', 'ok'),
            (r'{{range: \left[-\frac{4}{9};\frac{\sqrt[3]{9}-1}{2}\right]}}',
             r'\left[-\frac{4}{9};\frac{\sqrt[3]{9}+1}{2}\right]', 'wrong'),
            (r'{{range: [-2;0,5(\sqrt{17}+5))}}', r'[-2;\frac{\sqrt{17}+5}{2})', 'ok'),
            (r'{{range: [-2;0,5(\sqrt{17}+5))}}', r'[-2;\frac{\sqrt{17}-5}{2})', 'wrong'),
            (r'{{range: [0;(\log_3 2)^2)\cup(1,5;+\infty)}}',
             r'[0;(\log_3 2)^2)\cup(1,5;+\infty)', 'ok'),
            (r'{{range: [0;(\log_3 2)^2)\cup(1,5;+\infty)}}',
             r'[0;\log_3 2)\cup(1,5;+\infty)', 'wrong'),
            (r'{{range: (-\infty;-1) \quad \cup \quad (0,5;+\infty)}}',
             r'(-\infty;-1)\cup(0,5;+\infty)', 'ok'),
            (r'{{range: (-\infty;-1) \quad \cup \quad (0,5;+\infty)}}',
             r'(-\infty;-1]\cup(0,5;+\infty)', 'wrong'),
        ]
        for mask, answer, expected in cases:
            with self.subTest(mask=mask, answer=answer):
                spec = parse_mask(mask)
                self.assertTrue(spec.is_valid, spec.errors)
                self.assertEqual(check_slot(spec.slots[0], answer), expected)


class ExcludedPointTests(SimpleTestCase):
    """«A, x ≠ k» — выколотая точка, а не объединение со всей прямой."""

    def assertEquivalent(self, actual, reference):
        parsed = parse_range(actual)
        self.assertIsNotNone(parsed, actual)
        self.assertTrue(ranges_equal(parsed, parse_range(reference)), actual)

    def test_excluded_point_after_comma(self):
        # Эталоны Ткачука (партия 43): 1974.ММ.2, 1973.ГФ.4, 1985.ММ.2, 1989.ПЧ.3.
        groups = {
            '[-1;1)∪(1;3]': [r'-1 \leqslant x \leqslant 3, x \neq 1', '-1<=x<=3, x≠1',
                             r'x\in[-1;3], x\ne 1', '[-1;3]; x!=1', 'x≠1, [-1;3]'],
            r'(\frac12;1)∪(1;\frac32)∪(\frac32;2)':
                [r'\frac{1}{2}<x<2, x \neq 1, x \neq \frac{3}{2}'],
            r'(-∞;-1)∪[-\frac13;1)∪(1;∞)': [r'x \geqslant-\frac{1}{3}, x<-1, x \neq 1'],
            r'(-2;-1)∪(-1;-\frac12)∪(0;4]':
                [r'-2<x<-\frac{1}{2}, x \neq-1, 0<x \leqslant 4'],
            '(-∞;1)∪(1;2)∪(2;∞)': ['x≠1, x≠2', r'x \neq 1; x \neq 2'],
            '(-∞;2)∪(2;∞)': ['x≠2', 'x<2, x>2', 'x<2 или x>2'],
            '[0;3]': ['0<=x<=3, x≠5'],
            '(-∞;-1)∪(1;∞)': ['x<-1, x>1'],
            '(0;1)∪(1;∞)': ['x>0 и x≠1', 'x>0, x≠1'],
            r'(-∞;-\sqrt2)∪(-\sqrt2;1]': [r'x\le 1, x\neq-\sqrt{2}'],
            # Точка выкалывается из всего множества, даже если ∪ стоит раньше.
            '(0;1)∪(1;3)∪(5;6)': ['(0;3)∪(5;6), x≠1'],
            # «или» и ∪ — по-прежнему объединение, и рядом с ≠.
            'R': ['x≠1 или x=1', 'x>0 или x≠1', r'x \neq 1 \cup [0;2]', 'x≠1 or x≠2'],
            '(-∞;2)∪(2;∞)': ['x≠2 или x>3'],
        }
        for reference, values in groups.items():
            for value in values:
                with self.subTest(value=value):
                    self.assertEquivalent(value, reference)
        for value in (r'-1 \leqslant x \leqslant 3, x \neq 1', 'x>=-2, x≠-1'):
            with self.subTest(value=value):
                self.assertFalse(ranges_equal(parse_range(value), parse_range('R')))

    def test_mask_with_excluded_point(self):
        book = r'{{range: -1 \leqslant x \leqslant 3, x \neq 1}}'
        union = r'{{range: [-1;1)\cup(1;3]}}'
        log = r'{{range: a \leqslant \frac{1}{5} \log _{3} 15, a \neq-\frac{1}{2}}}'
        cases = [
            (book, r'[-1;1)\cup(1;3]', 'ok'),
            (book, r'-1 \le x<1 или 1<x \le 3', 'ok'),
            (book, r'-1 \le x \le 3, x \ne 1', 'ok'),
            (book, r'\mathbb{R}', 'wrong'),
            (book, '[-1;3]', 'wrong'),
            (union, r'-1 \leqslant x \leqslant 3, x \neq 1', 'ok'),
            (union, r'-1 \leqslant x \leqslant 3, x \neq 2', 'wrong'),
            (log, r'(-\infty;-0.5)\cup(-0.5;\log_{3}\sqrt[5]{15}]', 'ok'),
            (log, r'(-\infty;\frac{1}{5}\log_{3}15]', 'wrong'),
        ]
        for mask, answer, expected in cases:
            with self.subTest(mask=mask, answer=answer):
                spec = parse_mask(mask)
                self.assertTrue(spec.is_valid, spec.errors)
                self.assertEqual(check_slot(spec.slots[0], answer), expected)

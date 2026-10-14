"""Подпункты «а)» — на левом краю текста задачи (docs/PIPELINE.md).

Базовое ``ol.subitems`` не должно сдвигать подпункты вправо: каждый новый
экран, забывший своё переопределение, иначе показывает их с отступом
(так было трижды, в последний раз — в каталоге задач).
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

INPUT_CSS = Path(settings.BASE_DIR) / 'static' / 'css' / 'input.css'


class SubitemAlignmentTests(SimpleTestCase):
    def base_rule(self):
        css = INPUT_CSS.read_text(encoding='utf-8')
        # Первое правило ровно для «ol.subitems {» — базовое
        match = re.search(r'(?m)^\s*ol\.subitems\s*\{([^}]*)\}', css)
        self.assertIsNotNone(match, 'нет базового правила ol.subitems')
        return match.group(1)

    def test_base_subitems_have_no_left_offset(self):
        rule = self.base_rule()
        margin = re.search(r'margin\s*:\s*([^;]+);', rule)
        self.assertIsNotNone(margin)
        parts = margin.group(1).split()
        # margin: верх [право [низ [лево]]] — левое значение по правилам CSS
        left = parts[{1: 0, 2: 1, 3: 1, 4: 3}[len(parts)]]
        self.assertIn(left, ('0', '0px'), f'подпункты сдвинуты вправо: margin: {margin.group(1)}')
        self.assertNotRegex(rule, r'margin-left\s*:')
        padding = re.search(r'padding\s*:\s*([^;]+);', rule)
        self.assertEqual(padding.group(1).strip(), '0')
        self.assertNotRegex(rule, r'padding-left\s*:')

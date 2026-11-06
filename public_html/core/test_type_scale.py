"""Шкала шрифтов интерфейса — вариант A, выбран Егором 04.11.2026 (ревизия
03.11, G6): 12 / 13 / 14 / 16 / 22 px и 20 px для логотипа и крупных чисел.

В input.css и screens/*.css font-size задаётся только переменной --fs-*,
относительной величиной (em, %, inherit) или — для значков-глифов (×, +, ⠿,
индексы оценок) — числом из списка исключений ниже.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Значки и подписи внутри svg/шкал: их размер — про форму глифа, не про текст
GLYPH_SELECTORS = (
    '.dialog-heading .icon-btn', '.progress-mark', ' sub', '.cart-btn', '.icon-btn', '.drag-handle',
    'math-field', '.image-zoom-close', '.sidebar-close', '.copy-mark', '.ws-text-memo::before',
    '.mask-order-move', '.nl-label',
)
SCALE = {'--fs-xs': 0.75, '--fs-sm': 0.8125, '--fs-md': 0.875, '--fs-lg': 1, '--fs-xl': 1.25, '--fs-h1': 1.375}
RULE = re.compile(r'([^{}]*)\{([^{}]*)\}')
SIZE = re.compile(r'font-size:\s*([^;}\n]+)')


def css_files():
    css = Path(settings.BASE_DIR) / 'static' / 'css'
    return [css / 'input.css'] + sorted((css / 'screens').glob('*.css'))


class TypeScaleTests(SimpleTestCase):
    def test_sizes_come_from_scale(self):
        found = []
        for path in css_files():
            text = re.sub(r'/\*.*?\*/', '', path.read_text(encoding='utf-8'), flags=re.DOTALL)
            for match in RULE.finditer(text):
                selector = ' ' + ' '.join(match.group(1).split())
                for value in SIZE.findall(match.group(2)):
                    value = re.sub(r'\s*!important$', '', value.strip())
                    if value.startswith('var(--fs-') or value.endswith(('em', '%')) and not value.endswith('rem'):
                        continue
                    if value in ('inherit', 'smaller', 'larger', '0'):
                        continue
                    if any(glyph in selector for glyph in GLYPH_SELECTORS):
                        continue
                    found.append(f'{path.name}: {selector.strip()[-70:]} {{ font-size: {value} }}')
        self.assertEqual(found, [], 'Размер шрифта не из шкалы: используйте var(--fs-xs … --fs-h1)')

    def test_scale_tokens_defined(self):
        text = (Path(settings.BASE_DIR) / 'static' / 'css' / 'input.css').read_text(encoding='utf-8')
        for name, rem in SCALE.items():
            with self.subTest(token=name):
                self.assertRegex(text, rf'{name}:\s*{rem:g}rem')

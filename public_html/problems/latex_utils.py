"""Утилиты для работы с LaTeX-текстом задач."""

import re

# Спецсимволы LaTeX для экранирования "обычного" текста (заголовки и т.п.)
_LATEX_ESCAPE = {
    '\\': r'\textbackslash{}',
    '&': r'\&',
    '%': r'\%',
    '$': r'\$',
    '#': r'\#',
    '_': r'\_',
    '{': r'\{',
    '}': r'\}',
    '~': r'\textasciitilde{}',
    '^': r'\textasciicircum{}',
}

_escape_re = re.compile('|'.join(re.escape(c) for c in _LATEX_ESCAPE))


def escape_latex(text):
    """Экранирует спецсимволы LaTeX в обычном тексте (не в тексте задач!)."""
    if not text:
        return ''
    return _escape_re.sub(lambda m: _LATEX_ESCAPE[m.group()], text)


_ITEM_RE = re.compile(r'\\item\b')


def split_items(text):
    """Разбивает LaTeX-текст подпунктов по \\item; текст до первого \\item
    (если есть) считается первым подпунктом. Служебные хвостовые знаки
    срезаются (см. strip_subitem_punct): фрагменты перечисления хранятся
    без знака, законченные предложения — со своим знаком."""
    chunks = [strip_subitem_punct(c) for c in _ITEM_RE.split(text)]
    return [c for c in chunks if c]


def strip_subitem_punct(text):
    """Срезает знак препинания в конце подпункта — если он «служебный».

    Подпункт-предложение (начинается с заглавной буквы и заканчивается
    «.» или «?») сохраняет свой знак: «Приведите пример.» — законченная
    фраза, а не фрагмент перечисления. Фрагменты (начинаются со строчной
    буквы, цифры или формулы) хранятся без знака — «;»/«.»/«?» срезаются,
    система расставляет пунктуацию сама при выводе.
    """
    text = text.strip()
    if not text:
        return text
    if text[0].isupper() and text.endswith(('.', '?')):
        return text
    if text.endswith((';', '.', '?')):
        text = text[:-1].rstrip()
    return text


def strip_latex(text):
    """
    Грубо "раздевает" LaTeX-текст до обычного текста для поиска по ключевым
    словам: убирает команды, скобки, окружения; математику оставляет как есть
    (внутри могут быть значимые числа).
    """
    if not text:
        return ''
    s = text
    s = re.sub(r'\\begin\{[^}]*\}|\\end\{[^}]*\}', ' ', s)
    s = re.sub(r'\\[a-zA-Z@]+\*?', ' ', s)   # команды
    s = re.sub(r'[{}\[\]$&%#_^~]', ' ', s)   # структурные символы
    s = re.sub(r'\\\\|\\[,;!:]', ' ', s)     # переносы и пробелы LaTeX
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

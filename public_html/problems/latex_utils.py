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

"""Локальный конвейер импорта авторских листков 5–11.

Команды ничего не пишут в рабочую базу: сначала inventory/parse/classify
кладёт JSON в var/worksheets-import/, загрузка — отдельный шаг после сверки.
"""

from .paths import CORPUS_ROOTS, OUTPUT_DIR

__all__ = ['CORPUS_ROOTS', 'OUTPUT_DIR']

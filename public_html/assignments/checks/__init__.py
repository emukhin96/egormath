"""Проверка ответов ученика по маске: грамматика слотов (``mask``),
числовые слоты (``sets``), выражения через sympy (``expressions``).
Старые свободные ответы по-прежнему сверяет ``assignments.check_answer``."""
from .mask import (HELP, KINDS, PRESETS, MaskSpec, MaskTable, Slot,  # noqa: F401
                   check_mask, check_slot, collect_values, draft_mask, filled_text,
                   has_values, parse_mask, reference_text, render_fragments,
                   slot_display)

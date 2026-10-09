#!/usr/bin/env python3
"""Черновой ETL для OCR-LaTeX математических задач.

Команда ничего не пишет в Django DB. Она выделяет задачи и авторские
ответы/решения в проверяемый JSON, а также формирует TSV и Markdown-отчёт.
Профили отражают структуру конкретных семейств книг; сомнительные случаи
остаются в warnings и требуют ручной проверки.
"""

from __future__ import annotations

import argparse
import contextvars
import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .latex_utils import (
    ensure_displaystyle_fractions, heal_split_math_dollars, wrap_bare_math)


SCHEMA_VERSION = 1
SHESTAKOV_STRUCTURE = {
    1: ("Глава 1. Числовые выражения", {
        1: "§1. Действия с целыми числами",
        2: "§2. Действия с дробями",
        3: "§3. Действия с корнями",
    }),
    2: ("Глава 2. Буквенные выражения", {
        1: "§1. Действия с многочленами",
        2: "§2. Действия с алгебраическими дробями",
        3: "§3. Действия с иррациональными выражениями",
    }),
    3: ("Глава 3. Уравнения", {
        1: "§1. Целые алгебраические уравнения",
        2: "§2. Дробно-рациональные уравнения",
        3: "§3. Иррациональные уравнения",
    }),
    4: ("Глава 4. Неравенства", {
        1: "§1. Целые алгебраические неравенства",
        2: "§2. Дробно-рациональные неравенства",
        3: "§3. Иррациональные неравенства",
    }),
    5: ("Глава 5. Системы уравнений", {
        1: "§1. Системы целых алгебраических уравнений",
        2: "§2. Системы рациональных уравнений",
        3: "§3. Системы иррациональных уравнений",
    }),
    6: ("Глава 6. Системы неравенств", {
        1: "§1. Системы целых алгебраических неравенств",
        2: "§2. Системы дробно-рациональных неравенств",
        3: "§3. Системы иррациональных неравенств",
    }),
    7: ("Глава 7. Функции и графики", {
        1: "§1. Чтение графиков",
        2: "§2. Построение графиков",
        3: "§3. Исследование функций",
    }),
    8: ("Глава 8. Текстовые задачи", {
        1: "§1. Задачи на движение и работу",
        2: "§2. Задачи на проценты, части, доли",
        3: "§3. Задачи на свойства целых чисел",
    }),
    9: ("Глава 9. Прогрессии", {1: "§1. Прогрессии"}),
    10: ("Приложение 1. Задачи по геометрии", {
        1: "§1. Отрезки, углы, треугольники",
        2: "§2. Многоугольники",
        3: "§3. Окружности",
    }),
    11: ("Приложение 2. Теория вероятностей и статистика", {
        1: "§1. Задачи по теории вероятностей и статистике",
    }),
}
ANSWER_HEADING_RE = re.compile(
    r"\\section\*?\{\s*ОТВЕТЫ\s*,?\s*(?:УКАЗАН\s*ИЯ|УКАЗАНИЯ)?\s*,?\s*"
    r"(?:РЕШЕНИЯ)?\s*\}",
    re.IGNORECASE,
)
SECTION_COMMAND_RE = re.compile(r"\\(?P<level>section|subsection|subsubsection)\*?\{")
ALPHA_ITEM_RE = re.compile(r"\\item\[\s*(?P<label>[a-zа-яё0-9]+)\s*\)\s*\]", re.I)
PLAIN_ALPHA_ITEM_RE = re.compile(
    r"(?im)(?:^|(?<=\\\\)|(?<=\n))[ \t]*"
    r"(?P<label>[a-zа-яё0-9]+)\)(?![\^_])[\s~]*")
# В решебниках подпункты часто идут в одну строку: ``а) ...; б) ...``.
# Граница — конец предыдущего пункта. OCR часто ставит ``;`` внутри
# формулы и закрывает её перед следующей меткой: ``...;\) б)`` / ``...;$ б)``.
# Lookbehind фиксированной ширины: в 3.10 нельзя смешивать 1 и 2 символа.
# «6)» — OCR «б)», но не десятичная «(0,6)».
INLINE_ALPHA_ITEM_RE = re.compile(
    r"(?i)(?:(?<=[;.?:,$])|(?<=\\\))|(?<=\\\]))"
    r"(?<![0-9],)[ \t]*(?P<label>а|б|в|г|д|е|ж|з|a|b|c|d|6)\)[\s~]*")
# Mathpix часто рисует «б)» как жирную шестёрку: «\boldsymbol{6})»,
# «\mathbf{6}\right)». Не трогаем голую «(0 ; 6)» — это конец интервала.
_OCR_BOLD_SIX_ITEM_RE = re.compile(
    r"(?i)(?P<lead>(?:^|[;.?:,$]|\\\)|\\\]|\n)[ \t]*)"
    r"(?:\\(?:boldsymbol|mathbf|textbf|boldsymbol)\s*\{6\}"
    r"|\\(?:boldsymbol|mathbf|textbf|boldsymbol)\s+6)"
    r"(?:\\right)?\)"
)
LEAKED_BOOK_TAIL_RE = re.compile(
    r"(?:\\\\|\s)*§\d+\.[\s\S]*?(?:Уровень\s+[A-DА-Г]\s*)?$",
    re.I)
# Заголовок следующего варианта, темы или типа работ, прилипший
# к хвосту условия. Не берём голые «самостоятельную работу» внутри фразы.
LEAKED_STRUCTURAL_TAIL_RE = re.compile(
    r"(?im)"
    r"(?:^|\\\\|\n|(?<=[.!?\)])[ \t]+)"
    r"(?:"
    r"\\(?:sub)*section\*?\{[^{}]*\}"
    r"|Вариант\s+\d+"
    r"|(?:Самостоятельн|Контрольн|Проверочн)\w*\s+работ"
    r")")
BLOCK_WRAPPER_RE = re.compile(
    r"\\(?:begin|end)\{(?:itemize|enumerate|document)\}")
LIST_ENV_RE = re.compile(
    r"\\(?P<action>begin|end)\{(?:itemize|enumerate)\}")
EMPTY_ITEM_RE = re.compile(r"\\item\[\s*\]")
ANY_ITEM_RE = re.compile(
    r"\\item(?:\[\s*(?P<label>[^]]+?)\s*\])?[ \t]*")
# OCR Mathpix часто оставляет незакрытую {uuid и ломает optional-аргумент
# вроде [alt={}$,$max width=\textwidth]. Путь — до пробела/скобки/команды.
RAW_IMAGE_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^]]*\])?\s*\{(?P<path>[^{}\s\\]+)\}?")
TASK_IMAGE_RE = re.compile(
    r"\\(?P<command>includegraphics|taskpic)\s*(?:\[[^]]*\])?\s*"
    r"\{(?P<path>[^{}\s\\]+)\}?")
ORPHAN_MATH_TASKPIC_RE = re.compile(r"\$\\taskpic\{")
FLOAT_WRAPPER_RE = re.compile(
    r"\\(?:begin|end)\{(?:figure|center)\}(?:\[[^]]*\])?")
FLOAT_META_COMMAND_RE = re.compile(
    r"\\(?:captionsetup|caption)\s*\{")
STRUCTURAL_HEADING_RE = re.compile(
    r"\\(?:sub)*section\*?\{[^{}]*\}")
OCR_FIGURE_WRAPPER_RE = re.compile(
    r"\\textbackslash\s+(?:begin|end)\\?\{figure\\?\}(?:\\\\)?")

# Стиль меток подпунктов текущего профиля. Зив, Галицкий и Шестаков нумеруют
# пункты буквами «а) б) в)», поэтому цифры «3» и «6» считаются OCR-ошибками
# для «з» и «б». Мерзляк нумерует пункты цифрами «1) 2) 3)»: в этом режиме
# цифра — настоящая метка, а буквенная эвристика выключена. Контекст
# устанавливает профильный парсер (``with numeric_subitem_labels():``).
SUBITEM_LABEL_STYLE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "subitem_label_style", default="letters")


class numeric_subitem_labels:
    """Контекст-менеджер: пункты задач и ответов нумеруются цифрами."""

    def __enter__(self):
        self._token = SUBITEM_LABEL_STYLE.set("numeric")
        return self

    def __exit__(self, *exc_info):
        SUBITEM_LABEL_STYLE.reset(self._token)
        return False


def _numeric_labels() -> bool:
    return SUBITEM_LABEL_STYLE.get() == "numeric"


# Метка «2)» в строке ответа или условия при цифровой нумерации пунктов:
# после «;», «:», точки, вопроса, закрытой формулы или в начале строки.
# Координаты «(1; 2)» и формулы отсеивает ``_numeric_inline_markers``.
_INLINE_NUMERIC_ITEM_RE = re.compile(
    r"(?:^|(?<=[;:.?!])|(?<=\\\))|(?<=\\\])|(?<=\n))"
    r"[ \t]*(?P<label>\d{1,2})\)(?=[\s~]|$)")


@dataclass
class SubitemDraft:
    label: str
    text_latex: str
    author_answer_latex: str = ""
    author_solution_latex: str = ""


@dataclass
class TaskDraft:
    external_id: str
    source_number: str
    source_path: list[str]
    collection_key: str
    collection_title: str
    topic_original: str
    text_latex: str
    stars: int = 0
    subitems: list[SubitemDraft] = field(default_factory=list)
    author_answer_latex: str = ""
    answer_mask: str = ""
    author_solution_latex: str = ""
    images: list[str] = field(default_factory=list)
    exam_item_codes: list[str] = field(default_factory=list)
    grade_band_codes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    review_status: str = "needs_review"
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportBundle:
    schema_version: int
    profile: str
    source: dict
    tasks: list[TaskDraft]
    diagnostics: dict


@dataclass(frozen=True)
class Marker:
    start: int
    end: int
    external_id: str
    kind: str = ""


@dataclass(frozen=True)
class Section:
    start: int
    end: int
    level: str
    title: str


def read_group(text: str, open_pos: int) -> tuple[str, int]:
    """Читает сбалансированную {...}; команды и escaped braces учитываются."""
    if open_pos >= len(text) or text[open_pos] != "{":
        raise ValueError("Ожидалась открывающая фигурная скобка")
    depth = 1
    i = open_pos + 1
    start = i
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    raise ValueError(f"Незакрытая группа в позиции {open_pos}")


def remove_group_commands(text: str, pattern: re.Pattern) -> str:
    """Удаляет команды со сбалансированным {...} целиком."""
    spans = []
    for match in pattern.finditer(text):
        try:
            _, end = read_group(text, match.end() - 1)
        except ValueError:
            continue
        spans.append((match.start(), end))
    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    return text


def sections(text: str) -> list[Section]:
    result = []
    for match in SECTION_COMMAND_RE.finditer(text):
        try:
            title, end = read_group(text, match.end() - 1)
        except ValueError:
            continue
        result.append(Section(match.start(), end, match.group("level"), clean_heading(title)))
    return result


def clean(value: str) -> str:
    value = re.sub(r"%\s*\n", "\n", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    # \\task пакета egor имеет не-long опциональные
    # аргументы: пустая строка в подпункте обрывает сборку PDF.
    value = re.sub(r"\n\s*\n+", "\n", value)
    return normalize_imported_text(value.strip())


def strip_heading_dot(value: str) -> str:
    """Убирает точку в конце названия раздела или темы."""
    value = str(value or '').strip()
    if value.endswith(('...', '…')):
        return value
    return value.rstrip('.').rstrip()


def strip_imported_answer_punct(value: str) -> str:
    """Точка в конце ответа только у законченного предложения."""
    value = str(value or '').rstrip()
    if not value:
        return value
    if value.endswith(('?', '!')):
        return value
    if not value.endswith('.') or value.endswith('\\right.'):
        return value
    # «0. 2.» / «n=7. 7.» — точка держит номер следующей задачи.
    if re.search(r'\d{1,2}\s*\.\s*\d{1,2}\.$', value):
        return value
    if value[0].isupper():
        return value
    return value[:-1].rstrip()


_TRAILING_ORPHAN_PAREN_RE = re.compile(
    r'(?:\\right(?:[.).\]]|\\\}|\\\))|\\\})\s*\\?\)$')


def _strip_trailing_orphan_paren(value: str) -> str:
    """Срезает хвостовую ``)`` после уже закрытого ``\\right`` / ``\\}``.

    OCR Зива часто оставляет ``\\right\\})`` или ``\\}$)$`` от предыдущей
    формулы, когда номер следующей задачи вклеен в тот же абзац.
    """
    value = str(value or '').rstrip()
    if _TRAILING_ORPHAN_PAREN_RE.search(value):
        return re.sub(r'\s*\\?\)$', '', value)
    return value


def _close_unbalanced_inline_math(value: str) -> str:
    """Закрывает одинокую ``\\(``, которую OCR обрезал вместе с хвостом."""
    value = str(value or '')
    if value.count('\\(') == value.count('\\)') + 1 and not value.rstrip().endswith('\\)'):
        return value.rstrip() + '\\)'
    return value


def heal_ocr_six_item_labels(value: str) -> str:
    """Пишет «б)» вместо OCR-метки «\\boldsymbol{6})» / «\\mathbf{6})»."""
    return _OCR_BOLD_SIX_ITEM_RE.sub(r"\g<lead>б)", str(value or ""))


# OCR Зива: «\mathbf{3 .}», «\boldsymbol{3$ .$}» вместо номера следующей задачи.
_OCR_BOLD_TASK_NUM_RE = re.compile(
    r'(?:\$\s*)?(?:\\(?:mathbf|boldsymbol|textbf|boldsymbol)\s*\{?\s*)'
    r'(?P<num>\d{1,2})\s*\}?\s*(?:\$\s*)?\.\s*(?:\$\s*)?'
)
# «n=7.7 .-1» / «0.2 . \frac» / «1.4 .2 км» — ответ и номер задачи слиплись.
# Не берём «5.1. Решение»: там 5 — номер задачи, 1 — начало ответа.
_OCR_GLUED_INT_TASK_RE = re.compile(
    r'(?<=\d)\.(?P<num>[1-8])\s*\.\s*(?=[\\$+\-(]|\d)'
)
# «4. 0. 5.1. Решение» / «4.0 \leqslant» — после номера сразу цифра ответа.
_OCR_TASK_THEN_ANSWER_DIGIT_RE = re.compile(
    r'(?<![0-9.,])(?P<num>[1-9]\d?)\.(?P<lead>\d)'
    r'(?:[.~\s]+|(?=\s*\\(?:leqslant|geqslant|leq|geq|neq)))'
    r'(?=[A-ZА-Я\\<≤≥])'
)
# «5 .(2;3)» — пробел между номером и точкой перед скобкой.
_OCR_SPACED_DOT_TASK_RE = re.compile(
    r'(?<![0-9.,])(?P<num>[1-9]\d?)\s+\.\s*(?=[(\[\\$])'
)
# «2$ км/ч$» — wrap отрезал число от единиц.
_BROKEN_UNIT_DOLLAR_RE = re.compile(
    r'(?P<num>\d+)\$\s*(?P<unit>(?:км|м|см|мм)(?:/ч|/с|/мин)?)\s*\$'
)
_EMPTY_MATH_TAIL_RE = re.compile(
    r'(?:\s*\$\\displaystyle\$|\s*\$\s*\$|\s*\\\(\s*\\\)?)\s*$'
)
# OCR рвёт заголовок: «Решени е», «P е шени е».
_SOLUTION_HEADING_RE = (
    r"(?:Решени\s*[ея]|[PР]\s*е\s*ш\s*е\s*н\s*и\s*[ея]|Доказательство)"
)
# «\cdot 5 \cdot(-3 ;-1)» — OCR поставил точки умножения вместо «5.»
_OCR_CDOT_TASK_NUM_RE = re.compile(
    r'(?:\\cdot|\\times)\s*(?P<num>[1-8])\s*(?:\\cdot|\\times)'
)
# «m<0.6$. (-3;9)» — доллар между номером задачи и точкой.
_OCR_DOLLAR_TASK_NUM_RE = re.compile(
    r'(?<=\d)\.(?P<num>[1-8])\s*\$\s*\.'
)
# «5$. (-3;1)» — номер после wrap оказался перед «$.»
_OCR_BARE_DOLLAR_TASK_RE = re.compile(
    r'(?<![0-9.,])(?P<num>[1-8])\s*\$\s*\.\s*(?=\s*[(\-\\$])'
)
# «$\displaystyle 6 . \cos» — номер задачи внутри той же формулы.
_OCR_MATH_CMD_TASK_RE = re.compile(
    r'(?<![0-9.,])(?P<num>[1-8])\s*\.\s*(?=\\(?:cos|sin|tan|tg|ctg|operatorname|frac|left))'
)


def heal_ocr_task_number_labels(value: str) -> str:
    """Отделяет номер следующей задачи от ответа и жирного OCR."""
    value = _OCR_BOLD_TASK_NUM_RE.sub(r' \g<num>. ', str(value or ''))
    value = _OCR_CDOT_TASK_NUM_RE.sub(r' \g<num>. ', value)
    value = _OCR_DOLLAR_TASK_NUM_RE.sub(r'. \g<num>. ', value)
    value = _OCR_BARE_DOLLAR_TASK_RE.sub(r' \g<num>. ', value)
    value = _OCR_MATH_CMD_TASK_RE.sub(r' \g<num>. ', value)
    value = _OCR_SPACED_DOT_TASK_RE.sub(r' \g<num>. ', value)
    value = _OCR_TASK_THEN_ANSWER_DIGIT_RE.sub(r' \g<num>. \g<lead>. ', value)
    value = _OCR_GLUED_INT_TASK_RE.sub(r'. \g<num>. ', value)
    return re.sub(r'[ \t]{2,}', ' ', value)


def _strip_empty_math_tail(value: str) -> str:
    """Срезает пустой ``$\\displaystyle$`` / ``\\(`` после разреза номера."""
    return _EMPTY_MATH_TAIL_RE.sub('', str(value or '')).rstrip()


def _heal_broken_unit_dollars(value: str) -> str:
    """Собирает ``2$ км/ч$`` обратно в ``$2$ км/ч``."""
    value = str(value or '')
    spans = [match.span() for match in _MATH_SPAN_RE.finditer(value)]

    def heal(match):
        # В корректном «$300$ см$^{2}$» число уже обёрнуто: доллар перед
        # степенью начинает другую формулу, а не закрывает единицу.
        if any(start <= match.start() < end for start, end in spans):
            return match.group(0)
        return f"${match.group('num')}$ {match.group('unit')}"

    return _BROKEN_UNIT_DOLLAR_RE.sub(heal, value)


def _balance_odd_dollars(value: str) -> str:
    """Закрывает осколок ``$…`` после разреза по метке пункта."""
    value = str(value or "")
    if value.count("$") % 2 == 0:
        return value
    if value.startswith("$"):
        return value + "$"
    if value.endswith("$"):
        return "$" + value
    return value + "$"


def canonicalize_answer_math(value: str) -> str:
    """Сводит смешанные ``$`` / ``\\(`` к одному контуру для KaTeX.

    Типичный брак OCR+wrap: ``$\\(\\{-2\\pm\\sqrt{2}\\}$\\)`` и хвостовая
    ``\\)`` после уже закрытого ``$...$``. Сначала снимаем вложенность,
    потом непарные ``\\)``, затем ``\\(…\\)`` превращаем в ``$…$``.
    """
    value = str(value or '')
    value = value.replace(r'$\(', '$').replace(r'$\)', '$')
    while value.count(r'\)') > value.count(r'\('):
        stripped = re.sub(r'\\\)(\$?)\s*$', r'\1', value).rstrip()
        if stripped == value:
            break
        value = stripped
    value = _close_unbalanced_inline_math(value)

    def to_dollar(match):
        raw = match.group(0)
        if raw.startswith(r'\(') and raw.endswith(r'\)') and len(raw) >= 4:
            return '$%s$' % raw[2:-2]
        return raw

    return _MATH_SPAN_RE.sub(to_dollar, value)


def apply_imported_answer(value: str) -> str:
    """Нормализует импортированный ответ и срезает служебную точку."""
    value = heal_ocr_task_number_labels(heal_ocr_six_item_labels(value))
    value = re.sub(r'\\setcounter\{enum[ivxl]+\}\{\d+\}', '', value)
    value = _heal_broken_unit_dollars(value)
    value = _strip_empty_math_tail(value)
    value = _balance_odd_dollars(canonicalize_answer_math(value))
    value = _strip_trailing_orphan_paren(heal_split_math_dollars(value))
    value = _close_unbalanced_inline_math(value)
    value = _heal_broken_unit_dollars(value)
    return strip_imported_answer_punct(apply_imported_math(value))


def clean_heading(value: str) -> str:
    """Как ``clean``, плюс точка в конце названия раздела."""
    return strip_heading_dot(clean(value))


# Формулы, которые уже в разделителях KaTeX. Тот же набор, что в latex_utils.
_MATH_SPAN_RE = re.compile(
    r'\$\$.*?\$\$|\\\[.*?\\\]|\$.*?\$|\\\(.*?\\\)', re.S)
# Бинарные операторы и отношения, которые OCR дублирует на переносе строки.
_OCR_LINEBREAK_OP_RE = re.compile(
    r'\\(?:leqslant|geqslant|subseteq|subset|cdot|times|neq|leq|geq|'
    r'cup|cap|in|pm|mp)\b|[+\-=]')
_OCR_GAP_RE = re.compile(r'(?:\\\\|\\newline|\\par|\\,|~|\s|-)*')
_MATH_ATOM_RE = re.compile(
    r'\\[a-zA-Z]+\*?(?:\s*\[[^]]*\])?(?:\s*\{[^{}]*\})*'
    r'|\d+(?:[.,]\d+)?'
    r'|[A-Za-z](?:_\{?[A-Za-z0-9]+\})?')


def _strip_imported_text(value: str) -> str:
    """Убирает хвостовые переносы OCR и пробел перед конечной пунктуацией."""
    value = str(value or '')
    value = re.sub(r'(?i)^item\s+', '', value)
    value = re.sub(r'(?:\\\\\s*)+$', '', value).rstrip()
    value = re.sub(r'\s+([?!,.;:])\s*$', r'\1', value)
    return re.sub(r'[,;]+$', '', value).rstrip()


def normalize_imported_text(value: str) -> str:
    """Чистит OCR-текст: переносы, разорванные формулы, тире вне математики."""
    value = _heal_ocr_linebreak_math(_strip_imported_text(value))
    return _replace_spaced_hyphen_with_emdash(value)


def apply_imported_math(value: str) -> str:
    """Нормализует импортированный TeX и оборачивает голые формулы в ``$…$``."""
    # Сначала склеиваем уже обёрнутые `\(…\)`, затем wrap, затем ещё раз:
    # wrap может обернуть хвост `+1` в `$+1$`, и его тоже надо влить в формулу.
    # Em dash — только после wrap, иначе минус в голом TeX станет тире.
    value = heal_split_math_dollars(value)
    value = _heal_ocr_linebreak_math(_strip_imported_text(value))
    value = wrap_bare_math(value)
    value = _heal_ocr_linebreak_math(value)
    value = _replace_spaced_hyphen_with_emdash(value)
    return ensure_displaystyle_fractions(value)


def _unwrap_math_span(raw: str) -> tuple[str, str, str]:
    if raw.startswith('$$') and raw.endswith('$$') and len(raw) >= 4:
        return '$$', raw[2:-2], '$$'
    if raw.startswith('\\[') and raw.endswith('\\]') and len(raw) >= 4:
        return '\\[', raw[2:-2], '\\]'
    if raw.startswith('\\(') and raw.endswith('\\)') and len(raw) >= 4:
        return '\\(', raw[2:-2], '\\)'
    if raw.startswith('$') and raw.endswith('$') and len(raw) >= 2:
        return '$', raw[1:-1], '$'
    return '', raw, ''


def _trailing_linebreak_op(inner: str) -> str:
    stripped = inner.rstrip()
    match = None
    for match in _OCR_LINEBREAK_OP_RE.finditer(stripped):
        pass
    if match is None or match.end() != len(stripped):
        return ''
    return match.group(0)


def _split_leading_linebreak_op(inner: str) -> tuple[str, str]:
    match = _OCR_LINEBREAK_OP_RE.match(inner.lstrip())
    if not match:
        return '', inner
    leading = len(inner) - len(inner.lstrip())
    return match.group(0), inner[leading + match.end():]


def _is_ocr_formula_gap(gap: str) -> bool:
    return _OCR_GAP_RE.fullmatch(gap or '') is not None


def _is_hyphen_formula_gap(gap: str) -> bool:
    return '-' in (gap or '') and _is_ocr_formula_gap(gap)


def _try_merge_split_math(open_d: str, inner: str, close_d: str,
                          gap: str, right_raw: str) -> str | None:
    if not _is_ocr_formula_gap(gap):
        return None
    _, right_inner, _ = _unwrap_math_span(right_raw)
    left_op = _trailing_linebreak_op(inner)
    right_op, right_rest = _split_leading_linebreak_op(right_inner)
    if left_op and right_op and left_op == right_op:
        return open_d + inner.rstrip() + right_rest.lstrip() + close_d
    if _is_hyphen_formula_gap(gap) and right_op == '-':
        return open_d + inner.rstrip() + '-' + right_rest.lstrip() + close_d
    if _is_hyphen_formula_gap(gap):
        return open_d + inner.rstrip() + ' - ' + right_inner.lstrip() + close_d
    return None


def _try_absorb_operator_tail(inner: str, after: str) -> tuple[str, str] | None:
    left_op = _trailing_linebreak_op(inner)
    if not left_op:
        return None
    match = re.match(
        r'((?:\\\\|\\newline|\\par|\\,|~|\s|-)*)'
        + re.escape(left_op)
        + r'\s*('
        + _MATH_ATOM_RE.pattern
        + r')',
        after,
    )
    if not match:
        return None
    return inner.rstrip() + match.group(2), after[match.end():]


def _heal_ocr_linebreak_math(text: str) -> str:
    """Склеивает формулу, разорванную OCR на бинарном операторе.

    Типичные следы переноса в книге: ``\\(…+\\) +1``, ``\\(…+\\) \\(+…\\)``,
    ``\\(…=\\) \\(=…\\)``, ``\\(…\\) - \\(-…\\)``.
    """
    if not text or not _MATH_SPAN_RE.search(text):
        return text
    for _ in range(16):
        pieces = []
        last = 0
        matches = list(_MATH_SPAN_RE.finditer(text))
        changed = False
        index = 0
        while index < len(matches):
            match = matches[index]
            if match.start() > last:
                pieces.append(text[last:match.start()])
            open_d, inner, close_d = _unwrap_math_span(match.group(0))
            nxt = matches[index + 1] if index + 1 < len(matches) else None
            gap = text[match.end():nxt.start()] if nxt else text[match.end():]
            if nxt is not None:
                merged = _try_merge_split_math(
                    open_d, inner, close_d, gap, nxt.group(0))
                if merged is not None:
                    pieces.append(merged)
                    last = nxt.end()
                    index += 2
                    changed = True
                    continue
            absorbed = _try_absorb_operator_tail(inner, gap)
            if absorbed is not None:
                new_inner, rest = absorbed
                pieces.append(open_d + new_inner + close_d + rest)
                last = nxt.start() if nxt is not None else len(text)
                index += 1
                changed = True
                continue
            pieces.append(match.group(0))
            last = match.end()
            index += 1
        if last < len(text):
            pieces.append(text[last:])
        text = ''.join(pieces)
        if not changed:
            break
    return text


def _replace_spaced_hyphen_with_emdash(text: str) -> str:
    """Вне математики заменяет `` - `` на типографское тире."""
    if ' - ' not in text:
        return text
    parts = []
    last = 0
    for match in _MATH_SPAN_RE.finditer(text):
        parts.append(text[last:match.start()].replace(' - ', ' — '))
        parts.append(match.group(0))
        last = match.end()
    parts.append(text[last:].replace(' - ', ' — '))
    return ''.join(parts)


def strip_leading_subitem_label(text: str, label: str) -> str:
    """Не оставляет метку подпункта внутри его текста: она хранится отдельно."""
    text = str(text or '')
    if not label:
        return text
    match = re.match(
        r'(?is)^(?:\\item\[\s*)?(?P<label>[a-zа-яё0-9]+)\s*\)\s*',
        text)
    if not match:
        return text
    if _normalized_subitem_label(match.group('label')) != \
            _normalized_subitem_label(label):
        return text
    return text[match.end():]


def collapse_repeated_lead(value: str) -> str:
    """Склеивает OCR-повтор начала фразы: «Найдите …: Найдите …:»."""
    text = str(value or '').strip()
    changed = True
    while changed:
        changed = False
        for sep in (':', '.'):
            left, found, rest = text.partition(sep)
            if not found or not left.strip() or not rest.strip():
                continue
            right, found_again, tail = rest.lstrip().partition(sep)
            if found_again and left.strip() == right.strip():
                suffix = tail.strip()
                text = f'{left.strip()}{sep}' + (f' {suffix}' if suffix else '')
                changed = True
                break
    return text


def strip_outer_lists(value: str, *, flatten_items: bool = True) -> str:
    value = BLOCK_WRAPPER_RE.sub("", value)
    value = EMPTY_ITEM_RE.sub("", value)
    if flatten_items:
        value = ANY_ITEM_RE.sub(
            lambda match: (
                " " + clean(match.group("label") or "") + "~"
                if match.group("label") else " "),
            value,
        )
    return clean(value)


def strip_subitem_punct(value: str) -> str:
    """Нормализует хвостовую пунктуацию как импорт листка из ``.tex``.

    Законченное предложение с заглавной буквы сохраняет точку, а вопрос —
    вопросительный знак. У фрагментов перечисления служебные ``;``, ``,``
    и ``.`` удаляются: порядок подпунктов и последний элемент позже могут
    меняться.
    """
    value = clean(value)
    if not value:
        return value
    if value.endswith('?'):
        return value
    if value[0].isupper() and value.endswith('.'):
        return value
    if value.endswith('\\right.'):
        # Точка — часть ``\right.`` формулы без закрывающего «$».
        return value
    if value.endswith((';', '.', ',')):
        return value[:-1].rstrip()
    return value


def path_at(all_sections: Sequence[Section], pos: int) -> list[str]:
    """Возвращает стек смысловых заголовков по уровням LaTeX."""
    ignored = {
        "УПРАЖНЕНИЯ", "УРОВЕНЬ А", "УРОВЕНЬ В", "УРОВЕНЬ B",
        "УРОВЕНЬ С", "УРОВЕНЬ C", "УРОВЕНЬ D", "ГЛАВА",
    }
    level_index = {"section": 0, "subsection": 1, "subsubsection": 2}
    stack: list[str | None] = [None, None, None]
    for item in all_sections:
        if item.start >= pos:
            break
        normalized = re.sub(r"\s+", " ", item.title).strip().upper()
        if normalized in ignored or normalized.isdigit():
            continue
        if "ОГЛАВЛЕНИ" in normalized or "ПРЕДИСЛОВ" in normalized:
            continue
        index = level_index[item.level]
        stack[index] = item.title
        for deeper in range(index + 1, len(stack)):
            stack[deeper] = None
    return [title for title in stack if title]


def _open_paren_depth(prefix: str) -> int:
    """Глубина незакрытых скобок; промежутки «(a; b]» и «[a; b)» закрыты."""
    depth = 0
    for char in prefix:
        if char in "([":
            depth += 1
        elif char in ")]" and depth:
            depth -= 1
    return depth


def _numeric_inline_markers(body: str) -> list[tuple[int, int, str]]:
    """Цифровые метки «1) … 2) …» вне формул и вне незакрытых скобок."""
    spans = [(match.start(), match.end())
             for match in _MATH_SPAN_RE.finditer(body)]
    result = []
    for match in _INLINE_NUMERIC_ITEM_RE.finditer(body):
        start = match.start("label")
        if any(span_start < start < span_end for span_start, span_end in spans):
            continue
        # «(1; 2)» — координаты, а не метка «2)». Закрывающая скобка
        # самих меток «1)» на глубину не влияет: ниже нуля не уходим.
        if _open_paren_depth(body[:start]) > 0:
            continue
        result.append((match.start(), match.end(), match.group("label")))
    return result


def _numeric_marker_sequence(marker_data):
    """Возрастающая цепочка цифровых меток независимо от вложенности списков.

    OCR Мерзляка заворачивает часть пунктов во вложенный ``\\item[]``,
    поэтому глубина списка ничего не значит: берём метки по порядку номеров.
    """
    result = []
    previous = 0
    for start, end, label, _depth in marker_data:
        if not label.isdigit():
            continue
        number = int(label)
        if number <= previous:
            if result:
                break
            continue
        result.append((start, end, label))
        previous = number
    return result


def _subitem_marker_data(body: str) -> list[tuple[int, int, str, int]]:
    numeric = _numeric_labels()
    markers = [
        (match.start(), match.end(), match.group("label"))
        for match in ALPHA_ITEM_RE.finditer(body)
        if not numeric or match.group("label").isdigit()
    ]
    for match in PLAIN_ALPHA_ITEM_RE.finditer(body):
        if numeric and not match.group("label").isdigit():
            continue
        start = match.start()
        if body[max(0, start - 2):start] == r"\\":
            start -= 2
        markers.append((start, match.end(), match.group("label")))
    inline = (_numeric_inline_markers(body) if numeric else [
        (match.start(), match.end(), match.group("label"))
        for match in INLINE_ALPHA_ITEM_RE.finditer(body)])
    seen_starts = {marker[0] for marker in markers} if numeric else set()
    for marker in inline:
        if marker[0] not in seen_starts:
            markers.append(marker)
    markers.sort(key=lambda item: item[0])
    events = list(LIST_ENV_RE.finditer(body))
    event_index = 0
    depth = 0
    markers_with_depth = []
    for marker in markers:
        while (event_index < len(events)
               and events[event_index].start() < marker[0]):
            if events[event_index].group("action") == "begin":
                depth += 1
            else:
                # Блок задачи может начинаться внутри внешнего itemize,
                # открытого до её маркера: не уходим в отрицательную глубину.
                depth = max(0, depth - 1)
            event_index += 1
        markers_with_depth.append((*marker, depth))
    return markers_with_depth


def split_leaked_structural_tail(text: str) -> tuple[str, str]:
    """Отрезает прилипший заголовок следующего варианта, темы или §."""
    text = str(text or "")
    if not text:
        return text, ""
    matches = [
        match for match in (
            LEAKED_BOOK_TAIL_RE.search(text),
            LEAKED_STRUCTURAL_TAIL_RE.search(text),
        ) if match
    ]
    if not matches:
        return text, ""
    start = min(match.start() for match in matches)
    return text[:start], text[start:]


def reconstruct_imported_body(text_latex: str, subitems) -> str:
    """Собирает условие и подпункты обратно в один блок для повторного разбора."""
    parts = []
    lead = str(text_latex or "").strip()
    if lead:
        parts.append(lead)
    for item in subitems or []:
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            text = str(item.get("text_latex") or "")
        else:
            label = str(getattr(item, "label", "") or "").strip()
            text = str(getattr(item, "text_latex", "") or "")
        if not text.strip():
            continue
        parts.append(f"{label}) {text}" if label else text)
    return "\n".join(parts)


def _ziv_embedded_stem(body: str):
    """Вторая формулировка («Решите уравнения:») внутри уже собранного условия."""
    for match in ZIV_BARE_STEM_RE.finditer(body):
        prefix = re.sub(r'(?i)^item\s+', '', body[:match.start()]).strip()
        if prefix:
            return match
    return None


def draft_has_ziv_leak(text_latex: str, subitems) -> bool:
    """Есть ли в черновике хвост другого варианта, setcounter или вторая задача."""
    if re.match(r'(?i)^item\s+', str(text_latex or '').lstrip()):
        return True
    body = reconstruct_imported_body(text_latex, subitems)
    if split_leaked_structural_tail(body)[1].strip():
        return True
    if ZIV_ENUMI_RE.search(body):
        return True
    return _ziv_embedded_stem(body) is not None


_LEAD_STAR_RE = re.compile(r"^\s*(?:\*{1,3}|\\star(?:s)?)\s+")
_NUMBERED_PART_RE = re.compile(
    re.escape(r'\item[') + r'\s*(?P<item>\d{1,2})\s*\)\s*' + re.escape(']')
    + r'|(?:(?:^|\\\\|\n)[ \t]*(?P<plain>[1-9]\d?)\s*\))'
)


def _strip_leading_difficulty_star(text: str) -> tuple[int, str]:
    """Зив помечает сложную задачу ведущей ``*``, это не часть условия."""
    match = _LEAD_STAR_RE.match(text or "")
    if not match:
        return 0, text or ""
    raw = match.group(0)
    stars = min(3, raw.count("*") or 1)
    return stars, (text or "")[match.end():]


_NUMBERED_ANSWER_SPLIT_RE = re.compile(
    r'(?:^|\\\\|\n|;)\s*(?:\\item\[\s*)?(?P<num>[1-9]\d?)\s*\)\s*\]?'
)


def _numbered_answer_chunks(body: str) -> list[tuple[str, str]]:
    """Режет «а) … 2) а) … 3) …» на ответы нумерованных частей."""
    body = str(body or "")
    matches = list(_NUMBERED_ANSWER_SPLIT_RE.finditer(body))
    if not matches:
        return []
    chunks: list[tuple[str, str]] = []
    first_num = int(matches[0].group("num"))
    lead = body[:matches[0].start()]
    if first_num >= 2 and re.search(r"(?i)[aа]\)", lead):
        chunks.append(("1", lead))
    expected = int(chunks[-1][0]) + 1 if chunks else first_num
    for index, match in enumerate(matches):
        number = match.group("num")
        if int(number) != expected:
            break
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunks.append((number, body[match.end():stop]))
        expected += 1
    return chunks if len(chunks) >= 2 else []


def distribute_numbered_part_answers(task) -> bool:
    """Раскладывает компактный «а) … 2) а)» по подпунктам 1/2/3."""
    items = list(getattr(task, "subitems", None) or [])
    if len(items) < 2:
        return False
    labels = [_subitem_get(item, "label").strip() for item in items]
    if labels != [str(index) for index in range(1, len(items) + 1)]:
        return False
    blob = (
        getattr(task, "author_answer_latex", "")
        or getattr(task, "author_solution_latex", "")
        or ""
    )
    if not blob.strip():
        blob = _subitem_get(items[0], "author_answer_latex")
    chunks = _numbered_answer_chunks(blob)
    if not chunks:
        return False
    by_num = {number: text for number, text in chunks}
    changed = False
    rows = [dict(item) if isinstance(item, dict) else item for item in items]
    for row in rows:
        label = _subitem_get(row, "label").strip()
        text = (by_num.get(label) or "").strip()
        if text and not _subitem_get(row, "author_answer_latex").strip():
            _subitem_set(row, "author_answer_latex", apply_imported_answer(text))
            changed = True
    if changed:
        task.subitems = rows
        task.author_answer_latex = ""
        if getattr(task, "author_solution_latex", "") and blob == (
                getattr(task, "author_solution_latex", "") or ""):
            task.author_solution_latex = ""
    return changed


def _numbered_part_chunks(body: str) -> list[tuple[str, str]]:
    """Режет ``1) … \\item[2)] …`` на нумерованные части одной задачи."""
    matches = []
    for match in _NUMBERED_PART_RE.finditer(body or ""):
        number = match.group("item") or match.group("plain")
        matches.append((match.start(), match.end(), number))
    if len(matches) < 2 or matches[0][2] != "1":
        return []
    lead = BLOCK_WRAPPER_RE.sub("", body[:matches[0][0]])
    # «1)» / «\item[1)]» внутри а) — шаги решения, не части задачи.
    if re.search(r"\S", lead):
        return []
    expected = 1
    kept = []
    for start, end, number in matches:
        if not number.isdigit() or int(number) != expected:
            break
        kept.append((start, end, number))
        expected += 1
    if len(kept) < 2:
        return []
    chunks = []
    for index, (start, end, number) in enumerate(kept):
        stop = kept[index + 1][0] if index + 1 < len(kept) else len(body)
        chunks.append((number, body[end:stop]))
    return chunks


def split_subitems(
        body: str, *, normalize_punctuation: bool = True,
        minimum_items: int = 2, allow_numbered_parts: bool = True,
) -> tuple[str, list[SubitemDraft]]:
    numeric = _numeric_labels()
    if not numeric:
        body = heal_ocr_six_item_labels(body)
    if allow_numbered_parts and not numeric:
        parts = _numbered_part_chunks(body)
        if parts:
            items = []
            for number, chunk in parts:
                _parent, subs = split_subitems(
                    chunk, normalize_punctuation=normalize_punctuation,
                    minimum_items=minimum_items, allow_numbered_parts=False)
                if subs:
                    inner = []
                    if _parent.strip():
                        inner.append(_parent.strip())
                    inner.extend(
                        f"{cyrillic_item_label(item.label)}) {item.text_latex}"
                        for item in subs)
                    items.append(SubitemDraft(number, "\n".join(inner)))
                else:
                    text = strip_outer_lists(chunk)
                    if normalize_punctuation:
                        text = strip_subitem_punct(text)
                    else:
                        text = normalize_imported_text(text)
                    if text:
                        items.append(SubitemDraft(number, text))
            if len(items) >= 2:
                return "", items
    marker_data = _subitem_marker_data(body)
    markers = []
    if marker_data and numeric:
        markers = _numeric_marker_sequence(marker_data)
    elif marker_data:
        min_depth = min(marker[3] for marker in marker_data)
        markers = [marker[:3] for marker in marker_data
                   if marker[3] == min_depth]
        letter_markers = [
            marker for marker in marker_data
            if marker[2].isalpha() or marker[2] in {"3", "6"}
        ]
        if letter_markers:
            letter_depth = min(marker[3] for marker in letter_markers)
            shallow_letters = [
                marker for marker in letter_markers
                if marker[3] == letter_depth
            ]
            # OCR иногда ошибочно вкладывает б) в список
            # числовых пунктов а); поднимаем один уровень, только
            # если на минимальной глубине нет пары буквенных меток.
            deeper_letters = [
                marker for marker in letter_markers
                if marker[3] == letter_depth + 1
            ]
            pair_by_position = sorted(
                shallow_letters + deeper_letters,
                key=lambda marker: marker[0])
            can_promote_pair = (
                len(shallow_letters) == 1
                and len(deeper_letters) == 1
                and pair_by_position[0][2].lower() in {"a", "а"}
                and pair_by_position[1][2].lower() in {"b", "б", "6"}
            )
            chosen_letters = (
                shallow_letters if len(shallow_letters) >= 2
                else pair_by_position
                if can_promote_pair else []
            )
            if chosen_letters and len(shallow_letters) >= 2:
                orphans = [
                    marker for marker in letter_markers
                    if marker[3] > letter_depth
                    and marker[0] < shallow_letters[0][0]
                ]
                if orphans and orphans[0][2].lower() in {"a", "а"}:
                    chosen_letters = [orphans[0]] + chosen_letters
            if len(chosen_letters) >= 2 and (
                    letter_depth == min_depth
                    or chosen_letters[0][3] != letter_depth):
                markers = [marker[:3] for marker in chosen_letters]
    # Один item часто является оболочкой OCR, а не настоящим подпунктом.
    if len(markers) < minimum_items:
        return strip_outer_lists(body), []
    parent = strip_outer_lists(body[:markers[0][0]])
    items = []
    for i, (start, marker_end, label) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(body)
        text = strip_outer_lists(body[marker_end:end])
        text = strip_leading_subitem_label(text, label)
        if normalize_punctuation:
            text = strip_subitem_punct(text)
        else:
            text = normalize_imported_text(text)
        if text:
            items.append(SubitemDraft(label, text))
    parent = collapse_repeated_lead(parent)
    if items:
        items[-1].text_latex = normalize_imported_text(
            split_leaked_structural_tail(items[-1].text_latex)[0])
        if not items[-1].text_latex:
            items = items[:-1]
        items = order_letter_subitems(items)
    else:
        parent = normalize_imported_text(
            split_leaked_structural_tail(parent)[0])
    return parent, items


def detach_column_tail(body: str) -> tuple[str, str]:
    """Отделяет вложенный хвост соседней колонки после пары а/б."""
    marker_data = _subitem_marker_data(body)
    if not marker_data:
        return body, ""
    min_depth = min(marker[3] for marker in marker_data)
    top = [marker for marker in marker_data if marker[3] == min_depth]
    if len(top) < 2:
        return body, ""
    detachable_labels = {"a", "b", "а", "б", "6"}
    top_labels = {
        marker[2].lower() for marker in top
        if marker[2].lower() in detachable_labels
    }
    for start, marker_end, label, depth in marker_data:
        if (start > top[-1][0] and depth > min_depth
                and label.lower() in top_labels):
            container_start = body.rfind(
                r"\begin{itemize}", top[-1][1], start)
            if container_start < 0:
                container_start = start
            detached = strip_outer_lists(body[container_start:])
            detached = ALPHA_ITEM_RE.sub(
                lambda match: r"\\ " + match.group("label") + ") ",
                detached)
            return body[:container_start], detached
    return body, ""


def _is_numbered_taskpic(match: re.Match) -> bool:
    """\\taskpic{N} — уже нумерованная ссылка, а не имя файла."""
    return (
        match.groupdict().get("command") == "taskpic"
        and match.group("path").isdigit()
    )


def extract_images(body: str) -> list[str]:
    found: list[str] = []
    for match in TASK_IMAGE_RE.finditer(body or ""):
        if _is_numbered_taskpic(match):
            continue
        path = match.group("path")
        if path not in found:
            found.append(path)
    return found


def normalize_imported_graphics(body: str) -> str:
    """Оставляет \\taskpic{имя}, убирает OCR-обёртки figure/caption."""
    if not body:
        return body
    body = FLOAT_WRAPPER_RE.sub("", body)
    body = OCR_FIGURE_WRAPPER_RE.sub("", body)
    body = remove_group_commands(body, FLOAT_META_COMMAND_RE)
    body = RAW_IMAGE_RE.sub(
        lambda match: rf"\taskpic{{{match.group('path')}}}", body)
    body = ORPHAN_MATH_TASKPIC_RE.sub(r"\\taskpic{", body)
    return re.sub(r"\n{3,}", "\n\n", body)


def normalize_task_images(body: str) -> tuple[str, list[str]]:
    """Заменяет OCR-float на штатные \\taskpic{N}."""
    images = extract_images(body)
    positions = {path: index + 1 for index, path in enumerate(images)}

    def replace(match: re.Match) -> str:
        if _is_numbered_taskpic(match):
            return match.group(0)
        return rf"\taskpic{{{positions[match.group('path')]}}}"

    body = TASK_IMAGE_RE.sub(replace, body)
    body = FLOAT_WRAPPER_RE.sub("", body)
    body = OCR_FIGURE_WRAPPER_RE.sub("", body)
    body = remove_group_commands(body, FLOAT_META_COMMAND_RE)
    body = ORPHAN_MATH_TASKPIC_RE.sub(r"\\taskpic{", body)
    return body, images


def _subitem_get(item, key: str) -> str:
    if isinstance(item, dict):
        return str(item.get(key) or "")
    return str(getattr(item, key, "") or "")


def _subitem_set(item, key: str, value: str) -> None:
    if isinstance(item, dict):
        item[key] = value
    else:
        setattr(item, key, value)


_DRAFT_LATEX_KEYS = (
    "text_latex", "author_answer_latex", "author_solution_latex",
    "answer_latex", "solution_latex")


def finalize_draft_images(task) -> bool:
    """Собирает рисунки из всех полей и ставит \\taskpic{N}.

    Принимает и dataclass парсера, и сохранённый TextbookTaskDraft.
    """
    changed = False
    images = list(getattr(task, "images", None) or [])
    subitems = list(getattr(task, "subitems", None) or [])
    blobs = [getattr(task, key, "") or "" for key in _DRAFT_LATEX_KEYS]
    for item in subitems:
        blobs.extend(_subitem_get(item, key) for key in _DRAFT_LATEX_KEYS)
    for blob in blobs:
        for path in extract_images(blob):
            if path not in images:
                images.append(path)
    positions = {path: index + 1 for index, path in enumerate(images)}

    def rewrite(value: str) -> str:
        if not value:
            return value

        def replace(match: re.Match) -> str:
            if _is_numbered_taskpic(match):
                return match.group(0)
            path = match.group("path")
            if path in positions:
                return rf"\taskpic{{{positions[path]}}}"
            return match.group(0)

        value = TASK_IMAGE_RE.sub(replace, value)
        return normalize_imported_graphics(value)

    new_values = {
        key: rewrite(getattr(task, key, "") or "")
        for key in _DRAFT_LATEX_KEYS if hasattr(task, key)
    }
    new_subitems = []
    for item in subitems:
        row = dict(item) if isinstance(item, dict) else item
        for key in _DRAFT_LATEX_KEYS:
            if (key in row if isinstance(row, dict) else hasattr(row, key)):
                _subitem_set(row, key, rewrite(_subitem_get(row, key)))
        new_subitems.append(row)

    def _assign(name: str, value) -> None:
        nonlocal changed
        current = getattr(task, name, None)
        if current != value:
            setattr(task, name, value)
            changed = True

    for name, value in new_values.items():
        _assign(name, value)
    _assign("subitems", new_subitems)
    _assign("images", images)
    if _rejoin_false_solution_nouns(task):
        changed = True
    if _place_see_fig_pictures(task):
        changed = True
    return changed


SEE_FIG_NUM_RE = re.compile(
    r"(?i)(?P<head>см\.\s*рис\.?)\s*(?P<num>\d+)\.?"
)
TASKPIC_TOKEN_RE = re.compile(r"\\taskpic\{([^{}]+)\}")
FALSE_SOLUTION_NOUN_RE = re.compile(
    r"(?is)^(?P<noun>решения)\.\s*(?P<rest>.*)$"
)
# OCR Зива часто пишет номер как ``2 .``, ``.2 .``, ``.2 .$``, ``4)[`` или ``5 .(``.
LEAKED_TASK_NUM_RE = re.compile(
    r"(?P<num>\d{1,2})\s*"
    r"(?:\.(?:\s+|(?=[\\$(])|(?=\d)|$)|\)(?=\s*[\[(]))")
LEAKED_TASK_NUM_LEAD_RE = re.compile(
    r"^\d{1,2}\s*"
    r"(?:\.(?:\s+|(?=[\\$(])|(?=\d)|$)|\)(?=\s*[\[(]))")


def _strip_taskpic_tokens(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    for match in TASKPIC_TOKEN_RE.finditer(text or ""):
        token = match.group(1)
        if token not in found:
            found.append(token)
    cleaned = TASKPIC_TOKEN_RE.sub("", text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, found


def _append_taskpics(text: str, tokens: list[str]) -> str:
    body = (text or "").rstrip()
    extras = []
    for token in tokens:
        marker = rf"\taskpic{{{token}}}"
        if marker not in body:
            extras.append(marker)
    if not extras:
        return body
    return (body + "\n" + "\n".join(extras)).strip()


def _normalize_see_fig_refs(text: str) -> str:
    if not text:
        return text
    return SEE_FIG_NUM_RE.sub(r"\g<head>", text)


def _rejoin_false_solution_nouns(task) -> bool:
    """Склеивает «то 2» + «решения.», если заголовок решения сработал ложно."""
    changed = False

    def rejoin(answer: str, solution: str) -> tuple[str, str]:
        match = FALSE_SOLUTION_NOUN_RE.match(solution or "")
        if not match or not (answer or "").strip():
            return answer, solution
        rest = match.group("rest")
        rest_text, _pics = _strip_taskpic_tokens(rest)
        if rest_text.strip():
            return answer, solution
        if not re.search(r"\d\s*$", answer.strip()):
            return answer, solution
        joined = f"{answer.rstrip()} {match.group('noun')}."
        return joined, rest

    new_answer, new_solution = rejoin(
        getattr(task, "author_answer_latex", "") or "",
        getattr(task, "author_solution_latex", "") or "")
    if (new_answer != (getattr(task, "author_answer_latex", "") or "")
            or new_solution != (getattr(task, "author_solution_latex", "") or "")):
        task.author_answer_latex = new_answer
        task.author_solution_latex = new_solution
        changed = True
    items = list(getattr(task, "subitems", None) or [])
    new_items = []
    for item in items:
        row = dict(item) if isinstance(item, dict) else item
        answer, solution = rejoin(
            _subitem_get(row, "author_answer_latex"),
            _subitem_get(row, "author_solution_latex"))
        if (answer != _subitem_get(row, "author_answer_latex")
                or solution != _subitem_get(row, "author_solution_latex")):
            _subitem_set(row, "author_answer_latex", answer)
            _subitem_set(row, "author_solution_latex", solution)
            changed = True
        new_items.append(row)
    if new_items != items:
        task.subitems = new_items
    return changed


def _place_see_fig_pictures(task) -> bool:
    """Вешает \\taskpic на ответ с «см. рис. N» и убирает номер рисунка."""
    slots: list[tuple[str, object, str, str]] = []
    slots.append((
        "parent", None,
        getattr(task, "author_answer_latex", "") or "",
        getattr(task, "author_solution_latex", "") or "",
    ))
    items = list(getattr(task, "subitems", None) or [])
    for item in items:
        row = dict(item) if isinstance(item, dict) else item
        slots.append((
            "sub", row,
            _subitem_get(row, "author_answer_latex"),
            _subitem_get(row, "author_solution_latex"),
        ))

    refs: list[tuple[int, int]] = []
    pics: list[str] = []
    cleaned_slots = []
    for index, (kind, handle, answer, solution) in enumerate(slots):
        for match in SEE_FIG_NUM_RE.finditer(answer or ""):
            refs.append((index, int(match.group("num"))))
        answer, answer_pics = _strip_taskpic_tokens(answer)
        solution, solution_pics = _strip_taskpic_tokens(solution)
        for token in answer_pics + solution_pics:
            if token not in pics:
                pics.append(token)
        cleaned_slots.append((kind, handle, answer, solution))

    if not refs:
        return False

    assignment: dict[int, list[str]] = {index: [] for index, *_ in enumerate(cleaned_slots)}
    if pics:
        ordered_refs = sorted(refs, key=lambda item: item[1])
        for (slot_index, _fig_num), token in zip(ordered_refs, pics):
            assignment[slot_index].append(token)
        leftover = pics[len(ordered_refs):]
        if leftover:
            assignment[ordered_refs[-1][0]].extend(leftover)

    changed = False
    new_items = []
    for index, (kind, handle, answer, solution) in enumerate(cleaned_slots):
        answer = _normalize_see_fig_refs(answer)
        solution = _normalize_see_fig_refs(solution)
        answer = _append_taskpics(answer, assignment.get(index) or [])
        if kind == "parent":
            if (answer != (getattr(task, "author_answer_latex", "") or "")
                    or solution != (
                        getattr(task, "author_solution_latex", "") or "")):
                task.author_answer_latex = answer
                task.author_solution_latex = solution
                changed = True
        else:
            if (answer != _subitem_get(handle, "author_answer_latex")
                    or solution != _subitem_get(handle, "author_solution_latex")):
                changed = True
            _subitem_set(handle, "author_answer_latex", answer)
            _subitem_set(handle, "author_solution_latex", solution)
            new_items.append(handle)
    if new_items:
        task.subitems = new_items
    return changed


def _task_source_number(external_id: str) -> int | None:
    try:
        return int(str(external_id).rsplit("/", 1)[-1])
    except ValueError:
        return None


def _has_author_material(task) -> bool:
    if (getattr(task, "author_answer_latex", "") or "").strip():
        return True
    if (getattr(task, "author_solution_latex", "") or "").strip():
        return True
    for item in getattr(task, "subitems", None) or []:
        if (_subitem_get(item, "author_answer_latex").strip()
                or _subitem_get(item, "author_solution_latex").strip()):
            return True
    return False


def _find_leaked_following_task(text: str, next_number: int) -> int | None:
    """Граница «26. 4. Если…»: 4 — номер следующей задачи, не рисунка."""
    text = heal_ocr_task_number_labels(text or "")
    for match in LEAKED_TASK_NUM_RE.finditer(text):
        if int(match.group("num")) != next_number:
            continue
        before = text[:match.start()]
        after = text[match.end():]
        if re.search(r"(?i)рис\.?\s*$", before[-16:]):
            continue
        # «рис. 31. 4.» — 31 номер рисунка, 4 номер следующей задачи.
        fig_numbered = re.search(r"(?i)рис\.?\s*\d+\.\s*$", before)
        # «-1.2 .» без хвоста — десятичное. «0.2 . \frac» / «n=7.7 .-1» —
        # номер следующей задачи, если после него есть ответ.
        looks_decimal = (
            not fig_numbered
            and before.endswith('.')
            and len(before) >= 2
            and before[-2].isdigit())
        if looks_decimal and not re.search(r"\S", after):
            continue
        if not looks_decimal and not fig_numbered:
            if not re.search(r"(?:[.!?)\];$]|\\\()\s*$", before):
                # «4. 0 \leqslant» — ответ начинается с цифры.
                if not re.match(r"\s*(?:\\|\(|\d)", after):
                    continue
        # «n=7. 7. -1» — первая семёрка это значение, вторая номер.
        # Не путать с «4. 0. \leqslant», где 0 — сам ответ.
        if re.match(r"\s*\d{1,2}\s*\.\s*[-+\d(]", after):
            continue
        return match.start()
    bare = re.search(
        r'(?<=[\s.;])(?P<num>%d)\s*$' % next_number, text)
    if bare and re.search(r'\S', text[:bare.start()]):
        return bare.start()
    return None


def _earliest_leaked_following(text: str, numbers: list[int]) -> tuple[int, int] | None:
    """Самый левый номер следующей задачи в тексте."""
    best = None
    for number in numbers:
        cut = _find_leaked_following_task(text, number)
        if cut is not None and (best is None or cut < best[0]):
            best = (cut, number)
    return best


def _assign_peeled_author_text(task, text: str) -> None:
    """Кладёт отрезанный хвост в ответ и, если есть, в решение."""
    answer, solution = split_answer_solution(text)
    task.author_answer_latex = apply_imported_answer(answer or text)
    if solution and not (getattr(task, "author_solution_latex", "") or "").strip():
        task.author_solution_latex = apply_imported_math(solution)


def _split_stuck_solutions(task) -> bool:
    """Если «Решени е» осталось в ответе, отрезает его в решение."""
    changed = False
    answer = getattr(task, "author_answer_latex", "") or ""
    if answer:
        split_answer, split_solution = split_answer_solution(answer)
        if split_solution and split_answer != answer:
            task.author_answer_latex = apply_imported_answer(split_answer)
            if not (getattr(task, "author_solution_latex", "") or "").strip():
                task.author_solution_latex = apply_imported_math(split_solution)
            changed = True
    items = list(getattr(task, "subitems", None) or [])
    new_items = []
    for item in items:
        row = dict(item) if isinstance(item, dict) else item
        blob = _subitem_get(row, "author_answer_latex")
        if blob:
            split_answer, split_solution = split_answer_solution(blob)
            if split_solution and split_answer != blob:
                _subitem_set(row, "author_answer_latex",
                             apply_imported_answer(split_answer))
                if not _subitem_get(row, "author_solution_latex").strip():
                    _subitem_set(row, "author_solution_latex",
                                 apply_imported_math(split_solution))
                changed = True
        new_items.append(row)
    if new_items != items:
        task.subitems = new_items
    return changed


def _copy_author_fields(source, dest) -> None:
    dest.author_answer_latex = getattr(source, "author_answer_latex", "") or ""
    dest.author_solution_latex = getattr(source, "author_solution_latex", "") or ""


def _clear_author_fields(task) -> None:
    task.author_answer_latex = ""
    task.author_solution_latex = ""


def _looks_like_skipped_first_compute(task) -> bool:
    """Первая «Вычислите» без букв, а ответ уже с переменными — ответ от 2."""
    text = getattr(task, "text_latex", "") or ""
    if not re.match(r"(?i)вычислите", text):
        return False
    body = re.sub(r"(?i)^вычислите\s*", "", text)
    body = re.sub(r"\\[a-zA-Z]+", "", body)
    if re.search(r"[A-Za-zА-Яа-яЁё]", body):
        return False
    answer = getattr(task, "author_answer_latex", "") or ""
    return bool(re.search(r"(?<![A-Za-z])[abcxyzm](?![A-Za-z])", answer))


def shift_skipped_leading_compute_answers(tasks) -> list:
    """Сдвигает ответы на +1, если ключ пропустил первую «Вычислите»."""
    groups: dict[tuple[str, str], list] = {}
    for task in tasks:
        parsed = _ziv_topic_variant(getattr(task, "external_id", "") or "")
        if parsed is None:
            continue
        groups.setdefault(parsed, []).append(task)
    changed = []
    for group in groups.values():
        group.sort(key=lambda item: (
            _task_source_number(item.external_id) or 0, item.external_id))
        if len(group) < 3 or not _looks_like_skipped_first_compute(group[0]):
            continue
        hole = next(
            (i for i, item in enumerate(group[1:], 1)
             if not _has_author_material(item)),
            None)
        if hole is None:
            continue
        for index in range(hole, 0, -1):
            _copy_author_fields(group[index - 1], group[index])
        _clear_author_fields(group[0])
        changed.extend(group[: hole + 1])
    return changed


def reattach_leaked_following_answers(tasks) -> list:
    """Забирает «N. …» из предыдущего ответа, если задача N пуста.

    В ответах Зива OCR часто пишет «см. рис. 26. 4. Если…», а рисунки
    стоят уже после хвоста. Резать по «4.» на этапе обхода нельзя: тогда
    графики уедут в задачу 4. Отрезаем только авторский текст после merge.
    """
    groups: dict[tuple[str, str], list] = {}
    for task in tasks:
        parsed = _ziv_topic_variant(getattr(task, "external_id", "") or "")
        if parsed is None:
            continue
        groups.setdefault(parsed, []).append(task)
    changed = []

    def mark(*rows):
        for row in rows:
            if row not in changed:
                changed.append(row)

    for group in groups.values():
        group.sort(key=lambda item: (
            _task_source_number(item.external_id) or 0, item.external_id))
        for index, task in enumerate(group[:-1]):
            later_rows = [
                (item, number) for item, number in (
                    (item, _task_source_number(item.external_id))
                    for item in group[index + 1:]
                ) if number is not None
            ]
            if not later_rows:
                continue
            later_by_num = {number: item for item, number in later_rows}
            later_nums = [number for _item, number in later_rows]
            _rejoin_false_solution_nouns(task)
            parent_fields = (
                ("author_answer_latex",
                 getattr(task, "author_answer_latex", "") or ""),
                ("author_solution_latex",
                 getattr(task, "author_solution_latex", "") or ""),
            )
            peeled = False
            for field, raw in parent_fields:
                healed = heal_ocr_task_number_labels(raw)
                parent_hit = _earliest_leaked_following(healed, later_nums)
                if parent_hit is None:
                    continue
                parent_cut, next_number = parent_hit
                following = later_by_num[next_number]
                following_has_material = _has_author_material(following)
                kept, tail = healed[:parent_cut], healed[parent_cut:]
                tail_text, pics = _strip_taskpic_tokens(tail)
                tail_text = LEAKED_TASK_NUM_LEAD_RE.sub("", tail_text).strip()
                if not tail_text:
                    continue
                kept = _strip_empty_math_tail(_append_taskpics(kept.rstrip(), pics))
                if field == "author_answer_latex":
                    task.author_answer_latex = apply_imported_answer(kept)
                else:
                    task.author_solution_latex = apply_imported_math(kept)
                if not following_has_material:
                    _assign_peeled_author_text(following, tail_text)
                    mark(task, following)
                else:
                    mark(task)
                peeled = True
                break
            if peeled:
                continue
            rows = [
                dict(item) if isinstance(item, dict) else item
                for item in (getattr(task, "subitems", None) or [])
            ]
            cut_index = None
            found = None
            found_number = None
            for pos in range(len(rows) - 1, -1, -1):
                healed = heal_ocr_task_number_labels(
                    _subitem_get(rows[pos], "author_answer_latex"))
                if healed != _subitem_get(rows[pos], "author_answer_latex"):
                    _subitem_set(rows[pos], "author_answer_latex", healed)
                hit = _earliest_leaked_following(healed, later_nums)
                if hit is not None:
                    found, found_number = hit
                    cut_index = pos
                    break
            if cut_index is None or found is None or found_number is None:
                continue
            following = later_by_num[found_number]
            following_has_material = _has_author_material(following)
            answer = _subitem_get(rows[cut_index], "author_answer_latex")
            kept, tail = answer[:found], answer[found:]
            tail_text, pics = _strip_taskpic_tokens(tail)
            tail_text = LEAKED_TASK_NUM_LEAD_RE.sub("", tail_text).strip()
            if not tail_text:
                continue
            _subitem_set(
                rows[cut_index], "author_answer_latex",
                apply_imported_answer(_strip_empty_math_tail(
                    _append_taskpics(kept.rstrip(), pics))))
            task.subitems = rows
            if not following_has_material:
                _assign_peeled_author_text(following, tail_text)
                mark(task, following)
            else:
                mark(task)
    return changed


def task_from_block(marker: Marker, body: str, source_path: list[str]) -> TaskDraft:
    body, images = normalize_task_images(body)
    text, subitems = split_subitems(body)
    star_count, text = _strip_leading_difficulty_star(text)
    text = apply_imported_math(text)
    for item in subitems:
        item.text_latex = apply_imported_math(item.text_latex)
    source_path = [strip_heading_dot(part) for part in source_path if str(part).strip()]
    topic = source_path[-1] if source_path else ""
    warnings = []
    confidence = 1.0
    if len(re.sub(r"\\\w+|\s+", "", text)) < 8 and not subitems:
        warnings.append("Слишком короткое условие")
        confidence -= 0.35
    # В OCR Шестакова внешний itemize часто обозначает физическую колонку и
    # закономерно начинается в одном блоке задачи, а заканчивается в другом.
    # Проверяем только содержательные окружения нормализованного блока.
    structural_body = BLOCK_WRAPPER_RE.sub("", body)
    begin_envs = Counter(re.findall(r"\\begin\{([^{}]+)\}", structural_body))
    end_envs = Counter(re.findall(r"\\end\{([^{}]+)\}", structural_body))
    if begin_envs != end_envs:
        warnings.append("Несбалансированные LaTeX-окружения внутри блока")
        confidence -= 0.20
    return TaskDraft(
        external_id=marker.external_id,
        source_number=marker.external_id,
        source_path=source_path,
        collection_key="/".join(source_path),
        collection_title=topic,
        topic_original=topic,
        text_latex=text,
        subitems=subitems,
        images=images,
        confidence=max(0.0, confidence),
        stars=star_count,
        warnings=warnings,
    )


def blocks(text: str, markers: Sequence[Marker]) -> Iterator[tuple[Marker, str]]:
    for i, marker in enumerate(markers):
        end = markers[i + 1].start if i + 1 < len(markers) else len(text)
        yield marker, text[marker.end:end]


SH_CODE_RE = re.compile(
    r"(?<![\w.])(?P<chapter>\d{1,2})\.(?P<section>\d{1,2})\.?(?:\\?\]|\})?\s*"
    r"(?P<level>[A-DАВСД])\s*(?P<number>\d{2})(?!\d)", re.I
)
LEVEL_TRANSLATION = str.maketrans({"А": "A", "В": "B", "С": "C", "Д": "D"})
SH_APPENDIX_RE = re.compile(
    r"(?im)^\s*(?:"
    r"\\section\*?\{\s*Приложение\s*3\.\s*"
    r"Примерные варианты экзаменационных работ\s*\}"
    r"|Экзаменационные работы по алгебре "
    r"для общеобразовательных классов)\s*$"
)


def trim_shestakov_appendix(text: str) -> tuple[str, bool]:
    """Отсекает экзаменационные варианты после основного задачника."""
    boundary = SH_APPENDIX_RE.search(text)
    if not boundary:
        return text, False
    return text[:boundary.start()], True


def _shestakov_marker(text: str, match: re.Match) -> Marker:
    level = match.group("level").upper().translate(LEVEL_TRANSLATION)
    code = (
        f'{int(match.group("chapter"))}.{int(match.group("section"))}.'
        f'{level}{match.group("number")}'
    )
    line_start = text.rfind("\n", 0, match.start()) + 1
    prefix = text[line_start:match.start()].strip()
    if re.fullmatch(r"\\(?:sub)*section\*?\{\s*", prefix):
        marker_end = match.end()
        closing = re.match(r"\s*\}", text[marker_end:])
        if closing:
            marker_end += closing.end()
        return Marker(line_start, marker_end, code, "heading")
    if re.fullmatch(r"\\caption\{\s*", prefix):
        figure_start = text.rfind(r"\begin{figure}", 0, line_start)
        prior_figure_end = text.rfind(r"\end{figure}", 0, line_start)
        if figure_start > prior_figure_end:
            # OCR иногда заменяет номер задачи подписью к первому рисунку.
            # Начинаем блок с figure, чтобы изображение осталось у задачи.
            return Marker(figure_start, figure_start, code, "caption")
        itemize_start = text.rfind(r"\begin{itemize}", 0, line_start)
        prior_itemize_end = text.rfind(r"\end{itemize}", 0, line_start)
        marker_end = match.end()
        closing = re.match(r"\s*\}", text[marker_end:])
        if closing:
            marker_end += closing.end()
        if itemize_start > prior_itemize_end:
            # В решебнике caption иногда заменяет заголовок задачи.
            return Marker(itemize_start, marker_end, code, "caption")
    if re.fullmatch(r"\\item\[\s*", prefix):
        return Marker(line_start, match.end(), code, "item")
    return Marker(match.start(), match.end(), code, "direct")


def shestakov_markers(text: str) -> list[Marker]:
    """Маркеры условий: начало строки, task-item или код в caption."""
    result = []
    for match in SH_CODE_RE.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start:match.start()].strip()
        if prefix and not (
                re.fullmatch(r"\\item\[\s*", prefix)
                or re.fullmatch(r"\\caption\{\s*", prefix)):
            continue
        result.append(_shestakov_marker(text, match))
    return result


def shestakov_solution_markers(text: str) -> list[Marker]:
    """В решебнике следующий код может стоять в конце предыдущей строки."""
    result = []
    for match in SH_CODE_RE.finditer(text):
        marker = _shestakov_marker(text, match)
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = len(text)
        prefix = text[line_start:match.start()].strip()
        suffix = text[match.end():line_end].strip()
        is_caption = bool(re.fullmatch(r"\\caption\{\s*", prefix))
        is_direct = not prefix
        is_heading = bool(re.fullmatch(
            r"\\(?:sub)*section\*?\{\s*", prefix))
        is_item_label = bool(re.fullmatch(r"\\item\[\s*", prefix))
        looks_like_reference = bool(re.search(
            r"(?i)\b(?:задач\w*|номер\w*)\s*$", prefix))
        is_inline_transition = (
            (not suffix or bool(re.fullmatch(r"\\\\", suffix)))
            and not looks_like_reference
            and (
                bool(re.match(r"\\item\[", prefix))
                or bool(re.match(
                    r"[a-zа-яё0-9]+\)\s*", prefix, re.I))
                or bool(re.search(r"(?i)\bОтвет\s*:", prefix))
            )
        )
        if not (is_direct or is_heading or is_item_label
                or is_caption or is_inline_transition):
            # Внутритекстовая ссылка на другую задачу не граница.
            continue
        if (is_caption and result
                and not text[result[-1].end:marker.start].strip()):
            # Подпись сразу после номера — рисунок текущего решения, а OCR-код
            # в caption часто ошибочно указывает номер следующей задачи.
            continue
        result.append(marker)
    return result


def shestakov_sort_key(code: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.([A-D])(\d+)", code)
    if not match:
        raise ValueError(f"Неканонический код Шестакова: {code}")
    return (
        int(match.group(1)), int(match.group(2)),
        ord(match.group(3)), int(match.group(4)),
    )


def shestakov_source_path(code: str) -> list[str]:
    """Восстанавливает главу и параграф по каноническому номеру задачи."""
    chapter, paragraph, _, _ = shestakov_sort_key(code)
    structure = SHESTAKOV_STRUCTURE.get(chapter)
    if structure is None:
        return [f"Глава {chapter}", f"§{paragraph}"]
    chapter_title, paragraphs = structure
    return [chapter_title, paragraphs.get(paragraph, f"§{paragraph}")]


def expected_shestakov_ids() -> set[str]:
    """Полная каноническая сетка номеров, заявленная в структуре книги."""
    result = set()
    for chapter in range(1, 9):
        for section in range(1, 4):
            for level in "ABCD":
                for number in range(1, 11):
                    result.add(f"{chapter}.{section}.{level}{number:02d}")
    for level in "ABCD":
        for number in range(1, 11):
            result.add(f"9.1.{level}{number:02d}")
            result.add(f"11.1.{level}{number:02d}")
    for section in range(1, 4):
        for level in "ABCD":
            for number in range(1, 16):
                result.add(f"10.{section}.{level}{number:02d}")
    return result


def numeric_markers(text: str, allowed: set[str] | None = None) -> list[Marker]:
    """Номера вида 1.23 в начале строки или label элемента списка."""
    pattern = re.compile(
        r"(?m)(?:^\s*|\\item\[\s*)(?P<number>\d{1,2}\.\d{1,3})\."
        r"(?:\s*\]|\s+)"
    )
    result = []
    for match in pattern.finditer(text):
        number = match.group("number")
        if allowed is None or number in allowed:
            result.append(Marker(match.start(), match.end(), number))
    return result


def inline_numeric_markers(text: str, allowed: set[str]) -> list[Marker]:
    """Маркеры плотного раздела ответов: ``1.1. 2. 1.2. 69.``."""
    if not allowed:
        return []
    # OCR Галицкого часто печатает границу как ``2 .22 .`` и может приклеить
    # её к точке предыдущего ответа: ``-1.2 .22 .4``. Нормализуем пробелы
    # только после проверки канонического номера по списку задач.
    ordered = sorted(allowed, key=len, reverse=True)
    exact_alternatives = "|".join(re.escape(value) for value in ordered)
    # В OCR-варианте хотя бы с одной стороны внутренней точки есть пробел.
    # Это не даёт принять десятичное ``-1.2 .`` за номер задачи 1.2.
    spaced_alternatives = "|".join(
        re.escape(value).replace(
            r"\.", r"(?:\s+\.\s*|\s*\.\s+)")
        for value in ordered
    )
    exact_pattern = re.compile(
        rf"(?<!\w)(?P<number>{exact_alternatives})\.")
    exact = [
        Marker(match.start(), match.end(), match.group("number"))
        for match in exact_pattern.finditer(text)
    ]
    exact_ids = {marker.external_id for marker in exact}
    # Lookahead нужен для перекрывающихся OCR-кандидатов: в фрагменте
    # ``2 .22 .4 .2 .23 .`` ложный 4.2 иначе съедает настоящий 2.23.
    spaced_pattern = re.compile(
        rf"(?=(?P<marker>(?<!\w)(?P<number>{spaced_alternatives})\s*\.))")
    spaced = []
    for match in spaced_pattern.finditer(text):
        external_id = re.sub(r"\s+", "", match.group("number"))
        if external_id in exact_ids:
            # Повтор уже надёжно найден в обычной записи; чаще всего такой
            # OCR-кандидат является хвостом десятичного ответа.
            continue
        marker = Marker(
            match.start("marker"), match.end("marker"), external_id)
        if any(
                existing.start < marker.end and marker.start < existing.end
                for existing in exact + spaced):
            continue
        spaced.append(marker)
    return sorted(exact + spaced, key=lambda marker: marker.start)


def item_markers(text: str) -> list[Marker]:
    pattern = re.compile(r"\\item\[\s*(?P<number>\d{1,2})\.\s*\]")
    return [Marker(m.start(), m.end(), m.group("number")) for m in pattern.finditer(text)]


def unique_markers(markers: Iterable[Marker]) -> tuple[list[Marker], set[str]]:
    counts = Counter(item.external_id for item in markers)
    duplicates = {key for key, count in counts.items() if count > 1}
    seen = set()
    result = []
    for item in markers:
        if item.external_id in seen:
            continue
        seen.add(item.external_id)
        result.append(item)
    return result, duplicates


def split_answer_solution(body: str) -> tuple[str, str]:
    """Делит компактный ответ и решение без потери исходного LaTeX.

    Редкие авторские указания считаются частью решения: отдельного поля для
    них нет, а порядок «Указание … Решение …» сохраняется как в источнике.
    """
    body = strip_outer_lists(body)
    solution_match = re.search(
        r"(?i)(?<![0-9]\s)(?<![0-9])" + _SOLUTION_HEADING_RE + r"\s*[:.]",
        body)
    hint_match = re.search(r"(?i)У\s*к\s*а\s*з\s*а\s*н\s*и\s*[ея]\s*[:.]", body)
    cut_points = [m.start() for m in (solution_match, hint_match) if m]
    answer_end = min(cut_points) if cut_points else len(body)
    answer = clean(body[:answer_end])
    solution = clean(body[min(cut_points) :]) if cut_points else ""
    # clean() убирает пустые строки ради совместимости с optional-аргументом
    # \task, поэтому заголовок решения тоже обязан завершать явный ответ.
    explicit = re.search(
        r"(?is)\bОтвет\s*:\s*(.+?)(?="
        + _SOLUTION_HEADING_RE + r"\s*[:.]|"
        r"У\s*к\s*а\s*з\s*а\s*н\s*и\s*[ея]\s*[:.]|$)",
        body,
    )
    if explicit:
        answer = clean(explicit.group(1))
    return answer, solution


def _explicit_answers(solution: str) -> list[str]:
    return [
        clean(match.group(1))
        for match in re.finditer(
            r"(?im)\bОтвет\s*:\s*(.+?)(?:\\\\)?\s*$", solution)
        if clean(match.group(1))
    ]


def _compact_labeled_answers(items: Sequence[SubitemDraft]) -> str:
    """Склеивает компактный ответ «а) …; б) …» из размеченных кусков."""
    parts = []
    for item in items:
        answer = clean(getattr(item, "author_answer_latex", "") or "")
        if not answer:
            continue
        label = cyrillic_item_label(getattr(item, "label", "") or "")
        parts.append(f"{label}) {answer}" if label else answer)
    return "; ".join(parts)


def _flatten_solution_items(solution: str) -> str:
    """Делает непарные ``\\item`` безопасным обычным текстом."""
    item_number = 0

    def replace_item(match: re.Match) -> str:
        nonlocal item_number
        item_number += 1
        label = clean(match.group("label") or "")
        prefix = "" if item_number == 1 else r" \mbox{}\\ "
        return prefix + (label + "~" if label else "")

    solution = clean(ANY_ITEM_RE.sub(replace_item, solution))
    # Голые \\ по краям minipage дают `no line here to end`.
    solution = re.sub(r"^(?:\\\\\s*)+", "", solution)
    return re.sub(r"(?:\s*\\\\)+$", "", solution)


def _normalized_subitem_label(label: str) -> str:
    value = clean(label).lower()
    if value.isdigit() and _numeric_labels():
        return value
    aliases = {
        "а": "a", "a": "a",
        "б": "b", "b": "b", "6": "b",
        "в": "c", "c": "c",
        "г": "d", "d": "d",
        "д": "e",
        # В русской последовательности OCR обычно печатает латинское e
        # вместо кириллического е, а цифру 3 — вместо з.
        "е": "f", "e": "f",
        "ж": "g", "g": "g",
        "з": "h", "3": "h", "h": "h",
    }
    return aliases.get(value, value)


_CYR_ITEM_LABELS = {
    "a": "а", "b": "б", "c": "в", "d": "г", "e": "д",
    "f": "е", "g": "ж", "h": "з",
}


def cyrillic_item_label(label: str) -> str:
    """Латинскую OCR-метку ``a)`` показывает как «а», как в PDF."""
    raw = clean(label)
    if raw.isdigit() and _numeric_labels():
        return raw
    return _CYR_ITEM_LABELS.get(_normalized_subitem_label(raw), raw)


_LETTER_ORDER = tuple("abcdefgh")


def order_letter_subitems(items, *, get_label=None):
    """Если метки — перестановка алфавитного префикса, вернуть канонический порядок.

    Двухколоночный OCR Зива часто отдаёт ``а, в, б, г`` (сначала левая
    колонка). Для неполного или числового набора меток порядок не меняем.
    """
    if not items or len(items) < 2:
        return items
    if get_label is None:
        def get_label(item):
            return item.get("label") if isinstance(item, dict) else item.label
    keys = [_normalized_subitem_label(get_label(item)) for item in items]
    if len(set(keys)) != len(keys):
        return items
    expected = set(_LETTER_ORDER[:len(items)])
    if set(keys) != expected:
        return items
    ranked = sorted(
        zip(items, keys), key=lambda pair: _LETTER_ORDER.index(pair[1]))
    return [item for item, _key in ranked]


def _solution_subitem_pairs(
        task_subitems: Sequence[SubitemDraft],
        solution_subitems: Sequence[SubitemDraft],
) -> list[tuple[SubitemDraft, SubitemDraft]] | None:
    """Сопоставляет полный или неполный набор строго по уникальным меткам."""
    if not task_subitems or not solution_subitems:
        return None
    task_by_label = {
        _normalized_subitem_label(item.label): item for item in task_subitems
    }
    solution_by_label = {
        _normalized_subitem_label(item.label): item
        for item in solution_subitems
    }
    if (len(task_by_label) != len(task_subitems)
            or len(solution_by_label) != len(solution_subitems)
            or not solution_by_label.keys() <= task_by_label.keys()):
        return None
    return [
        (task_by_label[label], solution_item)
        for label, solution_item in solution_by_label.items()
    ]


def split_compact_author_material(
        body: str) -> tuple[str, str, list[SubitemDraft], str]:
    """Делит компактный ответ Галицкого и сохраняет частичные подпункты."""
    body = normalize_imported_graphics(body)
    # «рис. 31. 4. а)» — не режем по «а)» до reattach, иначе «4.»
    # останется без точки и следующая задача не заберёт хвост.
    if re.search(r"(?i)рис\.?\s*\d+\.\s*\d+\.", body):
        answer, solution = split_answer_solution(body)
        return answer, solution, [], solution
    parent, subitems = split_subitems(
        body, normalize_punctuation=False, minimum_items=1)
    parent_answer, parent_solution = split_answer_solution(parent)
    if not subitems:
        answer, solution = split_answer_solution(body)
        return answer, solution, [], solution
    for subitem in subitems:
        answer, solution = split_answer_solution(subitem.text_latex)
        subitem.text_latex = ""
        subitem.author_answer_latex = strip_subitem_punct(answer)
        subitem.author_solution_latex = strip_subitem_punct(solution)
    return parent_answer, parent_solution, subitems, parent_solution


def split_full_solution(
        body: str) -> tuple[str, str, list[SubitemDraft], str]:
    """Сохраняет решение и отдельно выделяет его верхние подпункты.

    Метки верхнего уровня нужны только как границы. В текст подпункта они не
    попадают: интерфейс и PDF нумеруют подпункты по их позиции. Вложенные
    числовые списки остаются частью соответствующего решения.
    """
    # Окружения списков пока сохраняем: split_subitems использует их для
    # определения глубины и не должен принять вложенный буквенный список за
    # верхнеуровневые подпункты решения.
    solution = clean(EMPTY_ITEM_RE.sub("", body))
    solution = STRUCTURAL_HEADING_RE.sub("", solution)
    solution = normalize_imported_graphics(solution)
    solution = solution.lstrip("} \t\n")
    parent, subitems = split_subitems(
        solution, normalize_punctuation=False)
    flattened_solution = _flatten_solution_items(
        strip_outer_lists(solution, flatten_items=False))
    if subitems:
        parent = _flatten_solution_items(parent)
        for subitem in subitems:
            subitem_text = _flatten_solution_items(subitem.text_latex)
            subitem.author_answer_latex = "\n".join(
                _explicit_answers(subitem_text))
            subitem.author_solution_latex = strip_subitem_punct(subitem_text)
            subitem.text_latex = ""
        return (
            "\n".join(_explicit_answers(parent)), parent, subitems,
            flattened_solution,
        )
    return (
        "\n".join(_explicit_answers(flattened_solution)),
        flattened_solution,
        [],
        flattened_solution,
    )


def _positional_answer_chunks(text: str, count: int) -> list[str] | None:
    """Режет компактный ответ без меток, если фрагментов ровно столько, сколько пунктов."""
    if not text or count < 2:
        return None
    parts = [
        strip_subitem_punct(part)
        for part in re.split(r"\s*;\s*", text)
        if part.strip()
    ]
    if len(parts) != count:
        return None
    return parts


def _subitem_label_key(item) -> str:
    return _normalized_subitem_label(_subitem_get(item, "label"))


def _author_field_chunk(text: str, field: str) -> str:
    answer, solution = split_answer_solution(text)
    if field == "author_answer_latex":
        return strip_subitem_punct(answer or text)
    return strip_subitem_punct(solution or text)


def _fill_empty_author_field(item, field: str, value: str) -> bool:
    value = str(value or "").strip()
    if not value or _subitem_get(item, field).strip():
        return False
    _subitem_set(item, field, value)
    return True


def _give_leftover_parent_to_unmatched_subitems(task, assigned_labels) -> None:
    """Первый пункт часто без метки: его текст остаётся родителем."""
    leftover_answer = (getattr(task, "author_answer_latex", "") or "").strip()
    leftover_solution = (getattr(task, "author_solution_latex", "") or "").strip()
    if not leftover_answer and not leftover_solution:
        return
    for item in getattr(task, "subitems", None) or []:
        if _subitem_label_key(item) in assigned_labels:
            continue
        if leftover_answer and _fill_empty_author_field(
                item, "author_answer_latex", leftover_answer):
            leftover_answer = ""
            task.author_answer_latex = ""
        if leftover_solution and _fill_empty_author_field(
                item, "author_solution_latex", leftover_solution):
            leftover_solution = ""
            task.author_solution_latex = ""
        if not leftover_answer and not leftover_solution:
            return


def redistribute_glued_subitem_answers(task) -> bool:
    """Если в ответе пункта торчит ``б)``, отрезает его и отдаёт соседу.

    Нужно и при разборе, и для уже сохранённых черновиков, где метка
    следующего пункта приклеилась после закрытой формулы.
    """
    items = list(getattr(task, "subitems", None) or [])
    if len(items) < 2:
        return False
    # Цифровые метки «1) 2) 3)» (Мерзляк) — свой режим разбора, даже если
    # черновик пришёл из базы без профильного контекста.
    if not _numeric_labels() and all(
            str(_subitem_get(item, "label")).strip().isdigit()
            for item in items):
        with numeric_subitem_labels():
            return redistribute_glued_subitem_answers(task)
    rows = [dict(item) if isinstance(item, dict) else item for item in items]
    changed = False

    def split_blob(text: str):
        if not str(text or "").strip():
            return "", []
        # «рис. 31. 4. а)» режет reattach; иначе «4.» потеряет точку.
        if re.search(r"(?i)рис\.?\s*\d+\.\s*\d+\.", text):
            return text, []
        return split_subitems(
            text, normalize_punctuation=False, minimum_items=1)

    def distribute(keep: str, pieces, field: str, start: int) -> bool:
        moved = False
        for piece in pieces:
            # Цифра 6 в OCR — алиас «б». Голый хвост ``$`` после
            # «(0 ; 6)» — закрывающая скобка интервала, не пункт.
            key = _normalized_subitem_label(piece.label)
            piece_text = (piece.text_latex or "").strip()
            if str(piece.label).isdigit():
                if not piece_text or re.fullmatch(r"[.$]+", piece_text):
                    continue
                # При цифровых метках «2)» — настоящий пункт; буквенный
                # фильтр «6 = б» только для профилей с «а) б) в)».
                if not _numeric_labels() and key != "b":
                    continue
            for later in rows[start:]:
                if _subitem_label_key(later) != key:
                    continue
                if _fill_empty_author_field(
                        later, field,
                        apply_imported_answer(
                            _author_field_chunk(piece.text_latex, field))):
                    moved = True
                break
        return moved

    for field in ("author_answer_latex", "author_solution_latex"):
        blob = getattr(task, field, "") or ""
        parent, found = split_blob(blob)
        if not found:
            continue
        keep, rest = parent, found
        if _normalized_subitem_label(found[0].label) == _subitem_label_key(rows[0]):
            keep, rest = found[0].text_latex, found[1:]
        moved = distribute(keep, rest, field, 0)
        if keep and _fill_empty_author_field(
                rows[0], field,
                apply_imported_answer(_author_field_chunk(keep, field))):
            moved = True
        if moved:
            setattr(task, field, "")
            changed = True

    for index, row in enumerate(rows):
        for field in ("author_answer_latex", "author_solution_latex"):
            blob = _subitem_get(row, field)
            parent, found = split_blob(blob)
            if not found:
                continue
            keep, rest = parent, found
            if _normalized_subitem_label(found[0].label) == _subitem_label_key(row):
                keep, rest = found[0].text_latex, found[1:]
            if not distribute(keep, rest, field, index + 1):
                continue
            _subitem_set(
                row, field,
                apply_imported_answer(
                    _author_field_chunk(keep, field) if keep else ""))
            changed = True

    if changed:
        task.subitems = rows
    return changed


def _meaningful_common_author_material(text: str) -> str:
    """Не сохраняет пустую метку ответа/решения как общее введение."""
    remaining = text.strip()
    while remaining:
        remaining = remaining.lstrip(' \t\n.:;,!?—–-…')
        without_heading = re.sub(
            r'(?i)^(?:ответ|решение|указани[ея])\b\s*[:.]?\s*',
            '', remaining)
        if without_heading == remaining:
            break
        remaining = without_heading
    return text if remaining else ''


def merge_solutions(
        tasks: list[TaskDraft], solution_text: str, marker_factory,
        *, full_solutions: bool = False, missing_ok: bool = False) -> dict:
    raw_solution_markers = marker_factory(solution_text)
    task_ids = {task.external_id for task in tasks}
    ignored_solution_code_refs = sorted({
        marker.external_id for marker in raw_solution_markers
        if marker.external_id not in task_ids
    })
    allowed_markers = [marker for marker in raw_solution_markers
                       if marker.external_id in task_ids]
    all_solution_markers = []
    for marker in raw_solution_markers:
        if (all_solution_markers
                and all_solution_markers[-1].external_id == marker.external_id
                and all_solution_markers[-1].kind == "caption"
                and marker.kind == "caption"):
            # Повтор caption с тем же кодом — продолжение того же решения.
            continue
        all_solution_markers.append(marker)
    counts = Counter(
        marker.external_id for marker in all_solution_markers
        if marker.external_id in task_ids)
    duplicate_solutions = {
        key for key, count in counts.items() if count > 1
    }
    solution_map = {}
    # Повторный маркер всё равно участвует в границах блока: иначе его текст
    # будет ошибочно приклеен к предыдущему решению. Для самого ключа
    # консервативно сохраняем первое вхождение и отправляем дубль на проверку.
    for marker, body in blocks(solution_text, all_solution_markers):
        if marker.external_id not in task_ids:
            continue
        images = extract_images(body)
        body = normalize_imported_graphics(body)
        if full_solutions:
            (answer, solution, solution_subitems,
             flattened_solution) = split_full_solution(body)
        else:
            (answer, solution, solution_subitems,
             flattened_solution) = split_compact_author_material(body)
        solution_map.setdefault(
            marker.external_id,
            (answer, solution, images, solution_subitems,
             flattened_solution),
        )
    matched = 0
    for task in tasks:
        if task.external_id in duplicate_solutions:
            task.warnings.append(
                "Повторный маркер авторского ответа/решения: "
                "проверить полноту сопоставления")
            task.confidence = max(0.0, task.confidence - 0.35)
        found = solution_map.get(task.external_id)
        if not found:
            if not missing_ok:
                task.warnings.append("Не найден авторский ответ/решение")
                task.confidence = max(0.0, task.confidence - 0.15)
            continue
        (task.author_answer_latex, task.author_solution_latex,
         solution_images, solution_subitems, flattened_solution) = found
        distributed_to_subitems = False
        common_author_material = None
        if solution_subitems:
            solution_pairs = _solution_subitem_pairs(
                task.subitems, solution_subitems)
            if solution_pairs is not None:
                if len(solution_pairs) == len(task.subitems):
                    # Все метки уже сопоставлены: вводный текст не может
                    # быть решением пропущенного пункта. Сохраняем общее
                    # указание отдельно от распределённых решений.
                    common_author_material = (
                        _meaningful_common_author_material(
                            task.author_answer_latex),
                        _meaningful_common_author_material(
                            task.author_solution_latex))
                assigned = set()
                for task_subitem, solution_subitem in solution_pairs:
                    task_subitem.author_answer_latex = (
                        solution_subitem.author_answer_latex)
                    task_subitem.author_solution_latex = (
                        solution_subitem.author_solution_latex)
                    assigned.add(_normalized_subitem_label(task_subitem.label))
                _give_leftover_parent_to_unmatched_subitems(task, assigned)
                distributed_to_subitems = True
            elif not task.subitems:
                if full_solutions:
                    # Нумерованные шаги доказательства у задачи без
                    # подпунктов — часть общего решения, не подпункты.
                    task.author_solution_latex = flattened_solution
                    task.author_answer_latex = "\n".join(
                        _explicit_answers(task.author_solution_latex))
                else:
                    # Компактный ответ Зива: «а) 1; б) -1» при условии без
                    # подпунктов. Нельзя звать _explicit_answers — там нет
                    # строки «Ответ:», и поле обнулялось.
                    task.author_answer_latex = (
                        task.author_answer_latex
                        or _compact_labeled_answers(solution_subitems))
            else:
                # При несовпадении границ не обнуляем ответ: у Зива часто
                # «1) а) … 2) а)» против нумерованных частей условия.
                compact = (
                    task.author_answer_latex
                    or _compact_labeled_answers(solution_subitems))
                explicit = "\n".join(
                    _explicit_answers(flattened_solution))
                task.author_answer_latex = explicit or compact
                task.author_solution_latex = flattened_solution
                task.warnings.append(
                    "Не совпали подпункты условия и решения")
                task.confidence = max(0.0, task.confidence - 0.25)
        if (task.subitems and found and not distributed_to_subitems
                and not any(
                    "Не совпали подпункты" in warning
                    for warning in task.warnings)):
            compact = (task.author_answer_latex or flattened_solution or "")
            chunks = _positional_answer_chunks(compact, len(task.subitems))
            if chunks:
                for subitem, chunk in zip(task.subitems, chunks):
                    if not subitem.author_answer_latex:
                        subitem.author_answer_latex = chunk
                distributed_to_subitems = True
        if (not any(
                "Не совпали подпункты" in warning
                for warning in task.warnings)
                and redistribute_glued_subitem_answers(task)):
            distributed_to_subitems = True
        if task.subitems and distributed_to_subitems:
            # Убираем распределённый материал, но не общее введение,
            # которое парсер отделил от всех подпунктов.
            (task.author_answer_latex, task.author_solution_latex) = (
                common_author_material or ("", ""))
        elif (task.subitems and found and not any(
                "Не совпали подпункты" in warning
                for warning in task.warnings)):
            # Компактный ответ оставляем у родителя, чтобы редактор его видел.
            task.warnings.append(
                "Авторский материал не удалось распределить по подпунктам")
            task.confidence = max(0.0, task.confidence - 0.25)
        task.images.extend(
            image for image in solution_images if image not in task.images)
        image_numbers = {
            image: task.images.index(image) + 1 for image in solution_images}

        def renumber_taskpics(value: str) -> str:
            return re.sub(
                r"\\taskpic\{([^{}]+)\}",
                lambda match: (
                    rf"\taskpic{{{image_numbers[match.group(1)]}}}"
                    if match.group(1) in image_numbers else match.group(0)),
                value,
            )

        task.author_answer_latex = apply_imported_answer(renumber_taskpics(
            task.author_answer_latex))
        task.author_solution_latex = apply_imported_math(renumber_taskpics(
            task.author_solution_latex))
        for subitem in task.subitems:
            subitem.author_answer_latex = apply_imported_answer(
                renumber_taskpics(subitem.author_answer_latex))
            subitem.author_solution_latex = apply_imported_math(
                renumber_taskpics(subitem.author_solution_latex))
        matched += 1
    return {
        "solution_marker_occurrences": len(allowed_markers),
        "solution_boundaries": len(all_solution_markers),
        "solution_markers": len(solution_map),
        "duplicate_solution_ids": sorted(duplicate_solutions),
        "matched_solutions": matched,
        # Старое поле сохраняем для потребителей отчёта; более точное имя
        # ignored_solution_code_refs объясняет, почему эти коды не смержены.
        "unmatched_solution_ids": ignored_solution_code_refs,
        "ignored_solution_code_refs": ignored_solution_code_refs,
        "tasks_without_solution_ids": sorted(task_ids - set(solution_map)),
    }


def parse_shestakov(tasks_text: str, solutions_text: str) -> tuple[list[TaskDraft], dict]:
    tasks_text, tasks_truncated = trim_shestakov_appendix(tasks_text)
    solutions_text, solutions_truncated = trim_shestakov_appendix(
        solutions_text)
    all_markers = shestakov_markers(tasks_text)
    marker_counts = Counter(marker.external_id for marker in all_markers)
    duplicate_tasks = {
        key for key, count in marker_counts.items() if count > 1
    }
    raw_blocks = [[marker, body]
                  for marker, body in blocks(tasks_text, all_markers)]
    detached_column_fragments = []
    for index in range(1, len(raw_blocks)):
        previous_marker, previous_body = raw_blocks[index - 1]
        marker, body = raw_blocks[index]
        if (shestakov_sort_key(marker.external_id)
                >= shestakov_sort_key(previous_marker.external_id)):
            continue
        main, detached = detach_column_tail(body)
        if not detached:
            continue
        previous_body = re.sub(
            r"\\begin\{itemize\}\s*$", "", previous_body)
        raw_blocks[index - 1][1] = previous_body + "\n" + detached
        raw_blocks[index][1] = main
        detached_column_fragments.append({
            "from": marker.external_id,
            "to": previous_marker.external_id,
        })
    merged_blocks = []
    block_by_id = {}
    for marker, body in raw_blocks:
        if marker.external_id in block_by_id:
            block_by_id[marker.external_id][1] += "\n" + body
            continue
        merged = [marker, body]
        block_by_id[marker.external_id] = merged
        merged_blocks.append(merged)
    tasks = []
    for marker, body in merged_blocks:
        task = task_from_block(
            marker, body, shestakov_source_path(marker.external_id))
        if marker.external_id in duplicate_tasks:
            task.warnings.append(
                "Повторный маркер условия: объединённые OCR-фрагменты "
                "нужно сверить вручную")
            task.confidence = max(0.0, task.confidence - 0.35)
        tasks.append(task)
    # Падение номера в линейном потоке часто означает склейку двух колонок OCR.
    previous = None
    previous_task = None
    physical_order_break_ids = []
    physical_order_affected_ids = set()
    for task in tasks:
        key = shestakov_sort_key(task.external_id)
        if previous is not None and key < previous:
            physical_order_break_ids.append(task.external_id)
            physical_order_affected_ids.update(
                [previous_task.external_id, task.external_id])
        previous = key
        previous_task = task
    boundary_warning = (
        "Нарушен порядок номеров рядом с задачей: проверить границу колонок OCR")
    for task in tasks:
        if task.external_id in physical_order_affected_ids:
            task.warnings.append(boundary_warning)
            task.confidence = max(0.0, task.confidence - 0.25)
    tasks.sort(key=lambda task: shestakov_sort_key(task.external_id))
    parsed_ids = {task.external_id for task in tasks}
    expected_ids = expected_shestakov_ids()
    diagnostics = {
        "task_marker_occurrences": len(all_markers),
        "unique_tasks": len(tasks),
        "duplicate_task_ids": sorted(duplicate_tasks),
        "physical_order_break_ids": physical_order_break_ids,
        "physical_order_affected_ids": sorted(
            physical_order_affected_ids, key=shestakov_sort_key),
        "detached_column_fragments": detached_column_fragments,
        "missing_task_ids": sorted(
            expected_ids - parsed_ids, key=shestakov_sort_key),
        "unexpected_task_ids": sorted(
            parsed_ids - expected_ids, key=shestakov_sort_key),
        "tasks_truncated_before_exam_variants": tasks_truncated,
        "solutions_truncated_before_exam_variants": solutions_truncated,
    }
    solution_diagnostics = merge_solutions(
        tasks, solutions_text, shestakov_solution_markers,
        full_solutions=True)
    diagnostics.update(solution_diagnostics)
    raw_solution_ids = {
        marker.external_id for marker in shestakov_solution_markers(
            solutions_text)
    }
    unbounded_next_ids = set(solution_diagnostics[
        "tasks_without_solution_ids"])
    unbounded_next_ids.update(
        (expected_ids - parsed_ids) - raw_solution_ids)
    by_key = sorted(
        ((shestakov_sort_key(task.external_id), task) for task in tasks),
        key=lambda item: item[0],
    )
    suspicious_predecessors: dict[str, list[str]] = {}
    for missing_id in sorted(unbounded_next_ids, key=shestakov_sort_key):
        missing_key = shestakov_sort_key(missing_id)
        prior = [task for key, task in by_key if key < missing_key]
        if not prior or not prior[-1].author_solution_latex:
            continue
        suspicious_predecessors.setdefault(
            prior[-1].external_id, []).append(missing_id)
    task_by_id = {task.external_id: task for task in tasks}
    for prior_id, next_ids in suspicious_predecessors.items():
        task = task_by_id[prior_id]
        task.warnings.append(
            "У следующего номера нет границы решения ("
            + ", ".join(next_ids)
            + "): проверить окончание авторского решения")
        task.confidence = max(0.0, task.confidence - 0.20)
    diagnostics["solution_boundary_review_predecessors"] = {
        key: value for key, value in sorted(
            suspicious_predecessors.items(),
            key=lambda item: shestakov_sort_key(item[0]))
    }
    for task in tasks:
        finalize_draft_images(task)
    return tasks, diagnostics


def parse_galitsky(text: str) -> tuple[list[TaskDraft], dict]:
    answer_heading = ANSWER_HEADING_RE.search(text)
    if not answer_heading:
        raise ValueError("Не найден раздел ответов Галицкого")
    task_text = text[: answer_heading.start()]
    answer_text = text[answer_heading.end() :]
    all_markers = numeric_markers(task_text)
    markers, duplicate_tasks = unique_markers(all_markers)
    headings = sections(task_text)
    tasks = [
        task_from_block(marker, body, path_at(headings, marker.start))
        for marker, body in blocks(task_text, markers)
    ]
    allowed = {task.external_id for task in tasks}
    diagnostics = {
        "task_marker_occurrences": len(all_markers),
        "unique_tasks": len(tasks),
        "duplicate_task_ids": sorted(duplicate_tasks),
    }
    diagnostics.update(merge_solutions(
        tasks, answer_text,
        lambda value: inline_numeric_markers(value, allowed),
        missing_ok=True,
    ))
    for task in tasks:
        finalize_draft_images(task)
    return tasks, diagnostics


ZIV_VARIANT_RE = re.compile(
    r"(?im)(?:^|(?<=\\\\)|(?<=\}))\s*(?:\\section\*?\{\s*)?"
    r"Вариант\s+(\d+)\s*\}?\.?\s*(?:\\\\)?"
)
ZIV_INLINE_VARIANT_RE = re.compile(
    r"(?im)Вариант\s+(\d+)\s*\.\s+(?=\d{1,2}\.[~\s])"
)
ZIV_TOPIC_RE = re.compile(r"^(?P<num>\d+)\.\s+(?P<title>.+)$")
ZIV_INLINE_NUM_RE = re.compile(
    r"(?:^|(?<=[\n.\\\\;])|(?<=\()|(?<=\))|(?<=ldots)|(?<=\.\.\.)|(?<=…))"
    r"\s*(?P<number>\d{1,2})\s*\.(?:"
    r"[~\s]+"
    r"|(?=\d\.(?:\s*(?:Решен|Указан|[А-ЯA-Z\\])))"
    r"|(?=\s*[(\[\\$])"
    r")"
)
ZIV_ENUMI_RE = re.compile(r"\\setcounter\{enum[ivxl]+\}\{(\d+)\}")
ZIV_PR_TOPIC_RE = re.compile(
    r"(?im)(?:^|(?<=\n)|(?<=\\\\))\s*Проверочная работа\s*№\s*(?P<num>\d+)"
)
# OCR теряет \item, но оставляет формулировку с двоеточием.
# «Найдите промежутки, на которых …» — продолжение, не новая задача.
ZIV_BARE_STEM_RE = re.compile(
    r"(?m)(?:^[ \t]*|(?<=[.!?;])[ \t]+|(?<=\\\\)\s*|(?<=\))[ \t]+"
    r"|(?<=Вариант \d)[ \t\\]+|(?<=Вариант \d\d)[ \t\\]+)"
    r"(?P<stem>"
    r"(?:Исследуйте|Выясните|Определите|Сравните|Упростите|Вычислите|"
    r"Выполните|Постройте|Решите|Разложите|Докажите|"
    r"Не строя графиков|"
    r"Найдите области|Найдите значение|Найдите корень|"
    r"Принадлежит ли"
    r")[^\n.]{0,70}:)"
)
ZIV_TASK_BOUNDARY_KINDS = frozenset(
    {"section", "variant", "pr_topic", "item", "inline", "enumi", "stem",
     "bare", "group_stem"}
)
ZIV_SECTION_VARIANT_RE = re.compile(r"(?i)^вариант\s+(\d+)\s*$")
ZIV_BARE_ITEM_RE = re.compile(r"\\item(?!\[)")
ZIV_WORK_NUM_RE = re.compile(r"№\s*(?P<num>\d+)")


def _ziv_work_code(title: str) -> str | None:
    """Тип работ. Нумерованная тема («7. Итоговая контрольная») — не глава."""
    cleaned = re.sub(r"\s+", " ", title).strip()
    if re.match(r"\d+\.", cleaned) or ZIV_WORK_NUM_RE.search(cleaned):
        return None
    if re.search(r"(?i)самостоятельн", cleaned):
        return "sr"
    if re.search(r"(?i)контрольн", cleaned):
        return "kr"
    if re.search(r"(?i)проверочн", cleaned):
        return "pr"
    return None


def _ziv_topic_parts(title: str) -> tuple[int, str]:
    cleaned = re.sub(r"\s+", " ", title).strip()
    if ZIV_SECTION_VARIANT_RE.match(cleaned):
        return 0, ""
    match = ZIV_TOPIC_RE.match(cleaned)
    if match:
        return int(match.group("num")), clean_heading(match.group("title"))
    numbered = ZIV_WORK_NUM_RE.search(cleaned)
    if numbered:
        return int(numbered.group("num")), clean_heading(cleaned)
    if cleaned.isdigit():
        return int(cleaned), "Тема"
    return 0, clean_heading(title)


def _ziv_item_topic_heading(number: str, body: str) -> tuple[int, str] | None:
    """OCR часто пишет «\\item[10.] Четность…» вместо \\section темы."""
    if not str(number).isdigit():
        return None
    topic_num = int(number)
    # Обычные задачи Зива — номера 1–7; 8+ в OCR — это заголовок следующей темы.
    if topic_num < 8 or topic_num > 30:
        return None
    first = re.split(r"(?:\\\\|\n)", str(body or ""), 1)[0]
    first = re.sub(r"\\item\[[^\]]*\]", "", first)
    if not _ziv_looks_like_topic_title(first):
        return None
    return topic_num, clean_heading(first)


def _ziv_effective_variant(topic_num: int, variant: int) -> int:
    if variant > 0:
        return variant
    return 1 if topic_num > 0 else 0


def _ziv_locator(work: str, topic_num: int, variant: int, number: str) -> str:
    return f"{work}/{topic_num:02d}/v{variant}/{number}"


def _ziv_known_topics(walked) -> list[tuple[str, int, str]]:
    known = []
    seen: set[tuple[str, int]] = set()
    for marker, path, _key, _body in walked:
        parts = marker.external_id.split("/")
        if len(parts) < 3:
            continue
        work, topic = parts[0], parts[1]
        try:
            topic_num = int(topic)
        except ValueError:
            continue
        if topic_num <= 0:
            continue
        identity = (work, topic_num)
        if identity in seen:
            continue
        seen.add(identity)
        title = path[1] if len(path) > 1 else ""
        known.append((work, topic_num, title))
    return known


def _ziv_match_known_topic(title: str, work: str, known) -> tuple[int, str] | None:
    cleaned = re.sub(r"\s+", " ", title).strip().lower()
    if not cleaned or cleaned == "тема":
        return None
    best = None
    best_len = -1
    for kwork, knum, ktitle in known:
        if kwork != work:
            continue
        other = ktitle.lower()
        if not other:
            continue
        if other == cleaned or other in cleaned or (
                len(cleaned) >= 8 and cleaned in other):
            score = min(len(other), len(cleaned))
            if score > best_len:
                best = (knum, ktitle)
                best_len = score
    return best


def _ziv_follows_marker(text: str, pos: int, spans: list[tuple[int, int]]) -> bool:
    """Формулировка сразу после \\item / номера / setcounter — не новая задача."""
    return any(
        end <= pos and not re.search(r"\S", text[end:pos])
        for _start, end in spans
    )


def _ziv_state_events(text: str) -> list[tuple[int, str, object]]:
    events: list[tuple[int, str, object]] = []
    for section in sections(text):
        events.append((section.start, "section", section))
    variant_spans: list[tuple[int, int]] = []
    for match in ZIV_VARIANT_RE.finditer(text):
        events.append((match.start(), "variant", int(match.group(1))))
        variant_spans.append((match.start(), match.end()))
    for match in ZIV_INLINE_VARIANT_RE.finditer(text):
        start, end = match.start(), match.end()
        if any(start >= lo and start < hi for lo, hi in variant_spans):
            continue
        events.append((start, "variant", int(match.group(1))))
    task_spans: list[tuple[int, int]] = []
    for marker in item_markers(text):
        events.append((marker.start, "item", marker))
        task_spans.append((marker.start, marker.end))
    pos = 0
    while True:
        match = ZIV_INLINE_NUM_RE.search(text, pos)
        if match is None:
            break
        start = match.start()
        if any(lo <= start < hi for lo, hi in task_spans):
            pos = match.end()
            continue
        prefix = text[max(0, start - 12):start]
        if re.search(r"(?i)рис\.?\s*$", prefix):
            # Номер рисунка, не задачи. Следующий «4.» режет
            # reattach_leaked_following_answers — иначе графики уедут в 4.
            pos = match.end()
            continue
        number = match.group("number")
        # «б) 0. 2.» — ноль это ответ, не задача; если съесть «0.»,
        # у «2.» пропадёт lookbehind.
        if number == "0":
            pos = match.start() + 1
            continue
        # «5.1. Решение» — единица это ответ, не задача 1.
        prefix = text[max(0, start - 8):start]
        after = text[match.end():]
        if (re.search(r"\d\.\s*$", prefix)
                and re.match(r"(?:Решен|Указан|[А-ЯA-Z])", after.lstrip())):
            pos = match.end()
            continue
        marker = Marker(start, match.end(), number)
        events.append((start, "inline", marker))
        task_spans.append((start, match.end()))
        pos = match.end()
    for match in ZIV_PR_TOPIC_RE.finditer(text):
        events.append((match.start(), "pr_topic", int(match.group("num"))))
    for match in ZIV_ENUMI_RE.finditer(text):
        skip = re.match(r"[\s\\]+", text[match.end():])
        start = match.end() + (skip.end() if skip else 0)
        marker = Marker(start, start, str(int(match.group(1)) + 1))
        events.append((match.start(), "enumi", marker))
        task_spans.append((match.start(), start))
    for match in ZIV_BARE_STEM_RE.finditer(text):
        start = match.start("stem")
        if _ziv_follows_marker(text, start, task_spans):
            continue
        # «Решите уравнения 1-5:» / «Решите системы 1-5:» — общая формулировка.
        after = text[match.end():]
        if re.match(r"(?:\s|\\\\)*1\.[~\s]", after) or re.match(
                r"(?:\s|\\\\)*\\item\[1\.", after) or re.match(
                r"(?:\s|\\\\)*\\begin\{(?:enumerate|itemize)\}", after):
            events.append((start, "group_stem", match.group("stem")))
            continue
        marker = Marker(start, start, "")
        events.append((start, "stem", marker))
        task_spans.append((start, match.end()))
    for match in ZIV_BARE_ITEM_RE.finditer(text):
        start = match.start()
        if any(lo <= start < hi for lo, hi in task_spans):
            continue
        prefix = text[max(0, start - 80):start]
        follows_setcounter = bool(re.search(
            r"\\setcounter\{enum[ivxl]+\}\{\d+\}\s*$", prefix))
        if _list_depth_at(text, start) > 1 and not follows_setcounter:
            # Вложенный \item — подпункт ответа, не новая задача.
            continue
        if follows_setcounter:
            continue
        marker = Marker(start, match.end(), "")
        events.append((start, "bare", marker))
        task_spans.append((start, match.end()))
    events.sort(key=lambda item: (item[0], item[1] != "item"))
    return events


def _ziv_looks_like_topic_title(body: str) -> bool:
    cleaned = clean(BLOCK_WRAPPER_RE.sub("", body or ""))
    cleaned = re.sub(r"(?i)^item\s+", "", cleaned).strip()
    if not cleaned or len(cleaned) > 160:
        return False
    if re.search(r"\.{4,}|…{2,}", cleaned):
        return False
    if "$" in cleaned or r"\(" in cleaned or r"\[" in cleaned or r"\begin" in cleaned:
        return False
    if re.search(r"(?i)см\.\s*рис", cleaned):
        return False
    if re.search(
            r"(?i)(?:^|[\s;])(?:[аa]\)|[бb6]\)|[вc]\)|[гd]\))",
            cleaned):
        return False
    if re.match(
            r"(?i)(?:решите|найдите|постройте|упростите|вычислите|"
            r"докажите|сравните|выполните|установите|две |два |"
            r"имеется|лыжник|сколько|дано:|при каких|между )",
            cleaned):
        return False
    return True


def _ziv_split_task_and_answer(text: str) -> tuple[str, str]:
    """Отделяет ответы, даже если они начались повторным типом работы."""
    heading = ANSWER_HEADING_RE.search(text)
    seen: set[str] = set()
    answer_start = heading.start() if heading else None
    for section in sections(text):
        code = _ziv_work_code(section.title)
        if not code:
            continue
        if code in seen:
            answer_start = (section.start if answer_start is None
                            else min(answer_start, section.start))
            break
        seen.add(code)
    if answer_start is None:
        raise ValueError("Не найден раздел ответов Зива")
    return text[:answer_start], text[answer_start:]


def _list_depth_at(text: str, pos: int) -> int:
    """Глубина itemize/enumerate в позиции ``pos``."""
    depth = 0
    for match in LIST_ENV_RE.finditer(text[:pos]):
        if match.group("action") == "begin":
            depth += 1
        else:
            depth = max(0, depth - 1)
    return depth


def _max_leaked_task_number(text: str, floor: int = 0) -> int:
    """Самый большой номер задачи, торчащий внутри уже начатого пункта."""
    best = floor
    healed = heal_ocr_task_number_labels(text or "")
    for match in LEAKED_TASK_NUM_RE.finditer(healed):
        number = int(match.group("num"))
        if floor < number <= 20:
            best = max(best, number)
    return best


def _ziv_trim_next_variant(body: str) -> str:
    """Не оставляет следующий вариант, тему или тип работ в теле задачи."""
    return split_leaked_structural_tail(body)[0]


def _ziv_walk(
        text: str, *, items_only: bool = True,
        include_inline: bool | None = None,
        known_topics=None) -> list[tuple[Marker, list[str], str, str]]:
    """Строит маркеры Зива с ключом работа/тема/вариант/номер."""
    emit_inline = (not items_only) if include_inline is None else include_inline
    emit_boundaries = not items_only
    work, work_title = "xx", "Раздел"
    topic_num, topic_title = 0, "Тема"
    variant = 0
    last_num = 0
    pending_stem = ""
    seen: set[tuple[int, str]] = set()
    result: list[tuple[Marker, list[str], str, str]] = []
    events = _ziv_state_events(text)
    for index, (pos, kind, payload) in enumerate(events):
        if kind == "group_stem":
            pending_stem = str(payload or "").strip()
            continue
        if kind == "section":
            variant_title = ZIV_SECTION_VARIANT_RE.match(
                re.sub(r"\s+", " ", payload.title).strip())
            if variant_title:
                variant = int(variant_title.group(1))
                last_num = 0
                pending_stem = ""
                if emit_boundaries:
                    result.append((
                        Marker(pos, pos, "__ziv_boundary__"), [], "", ""))
                continue
            code = _ziv_work_code(payload.title)
            if code:
                work, work_title = code, clean_heading(payload.title)
                topic_num, topic_title = 0, "Тема"
                variant = 0
                last_num = 0
                pending_stem = ""
            else:
                topic_num, topic_title = _ziv_topic_parts(payload.title)
                if topic_num == 0 and known_topics:
                    matched = _ziv_match_known_topic(
                        topic_title, work, known_topics)
                    if matched:
                        topic_num, topic_title = matched
                variant = 0
                last_num = 0
                pending_stem = ""
            if emit_boundaries:
                result.append((
                    Marker(pos, pos, "__ziv_boundary__"), [], "", ""))
            continue
        if kind == "variant":
            variant = payload
            last_num = 0
            pending_stem = ""
            if emit_boundaries:
                result.append((
                    Marker(pos, pos, "__ziv_boundary__"), [], "", ""))
            continue
        if kind == "pr_topic":
            topic_num = payload
            topic_title = f"Проверочная работа № {payload}"
            variant = 0
            last_num = 0
            pending_stem = ""
            if emit_boundaries:
                result.append((
                    Marker(pos, pos, "__ziv_boundary__"), [], "", ""))
            continue
        if kind in {"inline", "enumi", "stem", "bare"} and not emit_inline:
            continue
        if kind not in {"item", "inline", "enumi", "stem", "bare"}:
            continue
        marker: Marker = payload
        if kind in {"stem", "bare"}:
            last_num += 1
            marker = Marker(marker.start, marker.end, str(last_num))
        elif marker.external_id.isdigit():
            last_num = int(marker.external_id)
        next_pos = len(text)
        for later_pos, later_kind, _later in events[index + 1:]:
            if later_kind in ZIV_TASK_BOUNDARY_KINDS and (
                    later_kind != "inline" or emit_inline):
                next_pos = later_pos
                break
        body = _ziv_trim_next_variant(text[marker.end:next_pos])
        if pending_stem and pending_stem.lower() not in body.lower()[:len(pending_stem) + 8]:
            body = pending_stem + "\n" + body
        ocr_heading = _ziv_item_topic_heading(marker.external_id, body)
        known_heading = None
        title_heading = None
        if marker.external_id.isdigit() and _ziv_looks_like_topic_title(body):
            title = clean_heading(BLOCK_WRAPPER_RE.sub("", body))
            title = re.sub(r"(?i)^item\s+", "", title).strip()
            number = int(marker.external_id)
            if known_topics:
                matched = _ziv_match_known_topic(title, work, known_topics)
                if matched:
                    number, title = matched
                    known_heading = (number, title)
            title_heading = (number, title)
        heading = ocr_heading or known_heading or title_heading
        if heading is not None:
            next_variant = None
            next_real_section = False
            for _later_pos, later_kind, later in events[index + 1:]:
                if later_kind == "variant":
                    next_variant = later
                    break
                if later_kind == "section":
                    later_title = re.sub(r"\s+", " ", later.title).strip()
                    variant_title = ZIV_SECTION_VARIANT_RE.match(later_title)
                    if variant_title:
                        next_variant = int(variant_title.group(1))
                        break
                    if (_ziv_work_code(later.title)
                            or _ziv_topic_parts(later.title)[0]):
                        next_real_section = True
                        break
                    break
                if later_kind in ZIV_TASK_BOUNDARY_KINDS:
                    break
            # Известное название темы — заголовок даже перед «Вариант 4»:
            # в ответах Зива тема 1 часто сразу с последнего варианта.
            if (known_heading is not None
                    or next_variant == 1
                    or (ocr_heading is not None and next_real_section)):
                topic_num, topic_title = heading
                variant = 0
                last_num = 0
                continue
            if ocr_heading is not None:
                continue
        identity = (marker.start, kind)
        if identity in seen:
            continue
        seen.add(identity)
        effective_variant = _ziv_effective_variant(topic_num, variant)
        locator = _ziv_locator(
            work, topic_num, effective_variant, marker.external_id)
        path = [work_title, topic_title, f"Вариант {effective_variant}"]
        result.append((
            Marker(marker.start, marker.end, locator),
            path,
            f"{work}/{topic_num:02d}/v{effective_variant}",
            body,
        ))
    return result


ZIV_UNEVEN_VARIANT_WARNING = (
    "Нечётное число вариантов с одинаковым числом задач: "
    "возможно, задачи разных вариантов слиплись"
)
ZIV_LEAKED_HEADING_WARNING = (
    "С условия срезан прилипший заголовок варианта, темы или типа работ"
)
ZIV_LOOKS_LIKE_HEADING_WARNING = (
    "Похоже на заголовок темы, а не на задачу"
)
ZIV_SPLIT_FROM_WARNING = (
    "Выделено из слипшегося условия соседней задачи"
)


def _ziv_topic_variant(external_id: str) -> tuple[str, str] | None:
    """Разбирает ключ Зива ``sr/09/v1/3`` → (``sr/09``, ``v1``)."""
    parts = str(external_id or "").split("/")
    if len(parts) < 4:
        return None
    work, topic, variant = parts[0], parts[1], parts[2]
    if not variant.startswith("v") or not variant[1:].isdigit():
        return None
    return f"{work}/{topic}", variant


def _ziv_variant_counts(tasks: Sequence[TaskDraft]) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = {}
    for task in tasks:
        parsed = _ziv_topic_variant(task.external_id)
        if parsed is None:
            continue
        topic_key, variant = parsed
        groups.setdefault(topic_key, {})
        groups[topic_key][variant] = groups[topic_key].get(variant, 0) + 1
    return groups


def _ziv_apply_variant_parity(tasks: Sequence[TaskDraft]) -> list[dict]:
    """В Зиве пары 1–2, 3–4, 5–6, 7–8 одинаковы: число вариантов
    с одним и тем же количеством задач должно быть чётным."""
    uneven = []
    counts = _ziv_variant_counts(tasks)
    flagged: set[str] = set()
    for topic_key, by_variant in counts.items():
        if len(by_variant) < 2:
            continue
        freq = Counter(by_variant.values())
        if all(n % 2 == 0 for n in freq.values()):
            continue
        flagged.add(topic_key)
        uneven.append({
            "topic": topic_key,
            "variants": dict(sorted(by_variant.items())),
        })
    if not flagged:
        return []
    for task in tasks:
        parsed = _ziv_topic_variant(task.external_id)
        if parsed is None or parsed[0] not in flagged:
            continue
        if ZIV_UNEVEN_VARIANT_WARNING not in task.warnings:
            task.warnings.append(ZIV_UNEVEN_VARIANT_WARNING)
    return uneven


def _ziv_heading_like_title(value: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return bool(cleaned) and bool(re.match(r"(?i)вариант\s+\d+$", cleaned))


def _ziv_draft_work_title(source_path, work_code: str) -> str:
    if source_path:
        title = str(source_path[0]).strip()
        if _ziv_work_code(title):
            return title
    if work_code == "kr":
        return "Контрольные работы"
    if work_code == "pr":
        return "Проверочные работы"
    return "Самостоятельные работы"


def _ziv_draft_topic_title(
        source_path, collection_title: str = "",
        topic_original: str = "") -> str:
    candidates = []
    if source_path and len(source_path) > 1:
        candidates.append(source_path[1])
    candidates.extend([collection_title, topic_original])
    for title in candidates:
        cleaned = re.sub(r"\s+", " ", str(title or "")).strip()
        if cleaned and not _ziv_heading_like_title(cleaned):
            return cleaned
    return "Тема"


def wrap_ziv_draft_for_rewalk(
        external_id: str, source_path, body: str, *,
        collection_title: str = "", topic_original: str = "") -> str:
    """Оборачивает уже сохранённый черновик, чтобы снова прогнать _ziv_walk."""
    parts = str(external_id or "").split("/")
    work_code = parts[0] if parts else "sr"
    try:
        topic_num = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        topic_num = 0
    variant = 1
    if len(parts) > 2 and parts[2].startswith("v") and parts[2][1:].isdigit():
        variant = int(parts[2][1:])
    number = parts[3] if len(parts) > 3 else "1"
    work_title = _ziv_draft_work_title(source_path, work_code)
    topic_title = _ziv_draft_topic_title(
        source_path, collection_title, topic_original)
    heading = f"{topic_num}. {topic_title}" if topic_num else topic_title
    return (
        f"\\section*{{{work_title}}}\n"
        f"\\section*{{{heading}}}\n"
        f"Вариант {variant}\n"
        f"\\begin{{itemize}}\n"
        f"  \\item[{number}.] {body}\n"
        f"\\end{{itemize}}\n"
    )


def rewalk_ziv_merged_body(
        external_id: str, source_path, text_latex: str, subitems, *,
        collection_title: str = "", topic_original: str = "",
        known_topics=None) -> list[TaskDraft]:
    """Повторно режет слипшийся черновик Зива на отдельные задачи."""
    body = reconstruct_imported_body(text_latex, subitems)
    wrapped = wrap_ziv_draft_for_rewalk(
        external_id, source_path, body,
        collection_title=collection_title,
        topic_original=topic_original)
    walked = _ziv_walk(
        wrapped, items_only=True, include_inline=True,
        known_topics=known_topics)
    results = []
    seen: set[str] = set()
    for marker, path, key, task_body in walked:
        if marker.external_id in seen:
            continue
        seen.add(marker.external_id)
        task = task_from_block(marker, task_body, path)
        task.collection_key = key
        task.collection_title = (
            path[1] if len(path) > 1 else task.collection_title)
        if len(path) > 1:
            task.topic_original = path[1]
        task.source_number = marker.external_id.rsplit("/", 1)[-1]
        results.append(task)
    return results


def parse_ziv(text: str) -> tuple[list[TaskDraft], dict]:
    """Профиль Зива: ключ = тип работы / тема / вариант / локальный номер."""
    task_text, answer_text = _ziv_split_task_and_answer(text)
    walked = _ziv_walk(task_text, items_only=True, include_inline=True)
    raw_count = len(walked)
    markers = [item[0] for item in walked]
    unique, duplicates = unique_markers(markers)
    path_by_id = {}
    key_by_id = {}
    body_by_id = {}
    for marker, path, key, body in walked:
        if marker.external_id in body_by_id:
            continue
        path_by_id[marker.external_id] = path
        key_by_id[marker.external_id] = key
        body_by_id[marker.external_id] = body
    tasks = [
        task_from_block(
            marker, body_by_id.get(marker.external_id, ''),
            path_by_id.get(marker.external_id, []))
        for marker in unique
    ]
    for task in tasks:
        task.collection_key = key_by_id.get(task.external_id, task.collection_key)
        task.collection_title = (
            task.source_path[1] if len(task.source_path) > 1
            else task.collection_title)
        if len(task.source_path) > 1:
            task.topic_original = task.source_path[1]
        task.source_number = task.external_id.rsplit("/", 1)[-1]
        if task.external_id in duplicates:
            task.warnings.append("Неоднозначный локальный номер Зива")
            task.confidence = max(0.0, task.confidence - 0.35)
    uneven = _ziv_apply_variant_parity(tasks)
    allowed = {task.external_id for task in tasks}
    answer_markers = [
        marker for marker, _path, _key, _body in _ziv_walk(
            answer_text, items_only=False,
            known_topics=_ziv_known_topics(walked))
        if marker.external_id in allowed
        or marker.external_id == "__ziv_boundary__"
    ]
    diagnostics = {
        "task_marker_occurrences": raw_count,
        "unique_tasks": len(tasks),
        "duplicate_task_ids": sorted(duplicates),
        "ziv_uneven_variant_topics": uneven,
    }
    diagnostics.update(merge_solutions(
        tasks, answer_text,
        lambda _value: answer_markers,
        missing_ok=True,
    ))
    reattach_leaked_following_answers(tasks)
    reattach_leaked_following_answers(tasks)
    shift_skipped_leading_compute_answers(tasks)
    for task in tasks:
        _split_stuck_solutions(task)
        distribute_numbered_part_answers(task)
        redistribute_glued_subitem_answers(task)
        finalize_draft_images(task)
    return tasks, diagnostics


def bundle_from_text(
        profile: str, tasks_text: str, solutions_text: str = "", *,
        tasks_file: str = "tasks.tex", solutions_file: str = "",
        answers: dict | None = None, expected_ids: set | None = None,
        answers_file: str = "", pdf_task_contexts=None) -> ImportBundle:
    """Разбирает уже прочитанные TEX-файлы для CLI и веб-интерфейса."""
    if profile == "shestakov":
        if not solutions_text:
            raise ValueError("Для профиля shestakov обязателен файл решений")
        tasks, diagnostics = parse_shestakov(tasks_text, solutions_text)
    elif profile == "galitsky":
        tasks, diagnostics = parse_galitsky(tasks_text)
    elif profile == "merzlyak":
        from .merzlyak_parser import parse_merzlyak
        tasks, diagnostics = parse_merzlyak(tasks_text)
    elif profile == "shabunin":
        from .shabunin_parser import parse_shabunin
        tasks, diagnostics = parse_shabunin(tasks_text)
    elif profile == "feoktistov":
        from .feoktistov_parser import parse_feoktistov
        tasks, diagnostics = parse_feoktistov(tasks_text)
    elif profile == "ziv":
        tasks, diagnostics = parse_ziv(tasks_text)
    elif profile == "ostromogilsky":
        from .ostromogilsky_parser import parse_ostromogilsky
        tasks, diagnostics = parse_ostromogilsky(
            tasks_text, answers=answers, expected_ids=expected_ids,
            pdf_task_contexts=pdf_task_contexts)
    elif profile == "ostromogilsky_ege":
        from .ege_parser import parse_ege
        tasks, diagnostics = parse_ege(
            tasks_text, answers=answers, expected_ids=expected_ids,
            pdf_task_contexts=pdf_task_contexts)
    else:
        raise ValueError(f"Неизвестный профиль: {profile}")
    review_counts = Counter(
        "clean" if not task.warnings else "warning" for task in tasks
    )
    diagnostics["review_counts"] = dict(review_counts)
    diagnostics["tasks_with_subitems"] = sum(bool(task.subitems) for task in tasks)
    diagnostics["tasks_with_images"] = sum(bool(task.images) for task in tasks)
    diagnostics["tasks_with_author_answer"] = sum(
        bool(task.author_answer_latex)
        or any(item.author_answer_latex for item in task.subitems)
        for task in tasks
    )
    diagnostics["tasks_with_author_solution"] = sum(
        bool(task.author_solution_latex)
        or any(item.author_solution_latex for item in task.subitems)
        for task in tasks
    )
    return ImportBundle(
        schema_version=SCHEMA_VERSION,
        profile=profile,
        source={
            "tasks_file": tasks_file,
            "solutions_file": solutions_file,
            "answers_file": answers_file,
        },
        tasks=tasks,
        diagnostics=diagnostics,
    )


def bundle_for(profile: str, tasks_path: Path,
               solutions_path: Path | None,
               answers_pdf: Path | None = None,
               pdf_index_path: Path | None = None) -> ImportBundle:
    answers = None
    expected_ids = None
    answers_file = ""
    pdf_task_contexts = None
    if profile in {"ostromogilsky", "ostromogilsky_ege"}:
        if answers_pdf is None:
            raise ValueError(
                "Для профиля банка ФИПИ обязателен PDF с ключом "
                "(--answers-pdf)")
        from .ostromogilsky_parser import extract_pdf_answers
        answers, expected_ids = extract_pdf_answers(answers_pdf)
        if profile == "ostromogilsky_ege":
            import hashlib
            from .ege_parser import build_pdf_index
            pdf_hash = hashlib.sha256(answers_pdf.read_bytes()).hexdigest()
            parser_hash = hashlib.sha256(Path(__file__).with_name('ege_parser.py').read_bytes()).hexdigest()
            cache_key = [pdf_hash, parser_hash]
            cached = json.loads(pdf_index_path.read_text()) if pdf_index_path and pdf_index_path.exists() else {}
            if cached.get('cache_key') == cache_key:
                pdf_task_contexts = cached
            else:
                pdf_task_contexts = build_pdf_index(answers_pdf)
                pdf_task_contexts['cache_key'] = cache_key
                if pdf_index_path:
                    pdf_index_path.parent.mkdir(parents=True, exist_ok=True)
                    pdf_index_path.write_text(json.dumps(pdf_task_contexts, ensure_ascii=False, indent=2) + '\n')
            expected_ids = set(pdf_task_contexts['tasks'])
            answers = {key: value for key, value in answers.items() if key in expected_ids}
            from .ege_answers import extract_ege_answers
            answers, answer_diagnostics = extract_ege_answers(
                tasks_path.read_text(encoding='utf-8'), answers, pdf_task_contexts)
            from .ege_repairs import repair_answers
            answer_diagnostics['verified_pdf_transcriptions'] = repair_answers(
                answers, hashlib.sha256(tasks_path.read_bytes()).hexdigest(), pdf_hash)
        else:
            from .ostromogilsky_splits import extract_pdf_task_contexts
            pdf_task_contexts = extract_pdf_task_contexts(answers_pdf)
        answers_file = str(answers_pdf.resolve())
    bundle = bundle_from_text(
        profile,
        tasks_path.read_text(encoding="utf-8"),
        (solutions_path.read_text(encoding="utf-8")
         if solutions_path else ""),
        tasks_file=str(tasks_path.resolve()),
        solutions_file=(str(solutions_path.resolve())
                        if solutions_path else ""),
        answers=answers,
        expected_ids=expected_ids,
        answers_file=answers_file,
        pdf_task_contexts=pdf_task_contexts,
    )
    if profile == "ostromogilsky_ege":
        import hashlib
        parser_files = [Path(__file__), *(Path(__file__).parent / name for name in (
            'ege_parser.py', 'ege_answers.py', 'ege_figures.py', 'ege_repairs.py',
            'ege_metadata.py', 'ege_cleanup.py', 'data/ege_source_repairs.json',
            'data/ege_answer_repairs.json'))]
        parser_hash = hashlib.sha256(b''.join(p.read_bytes() for p in parser_files)).hexdigest()
        bundle.source.update({
            "tasks_sha256": hashlib.sha256(tasks_path.read_bytes()).hexdigest(),
            "pdf_sha256": hashlib.sha256(answers_pdf.read_bytes()).hexdigest(),
            "edition": "ostromogilsky-ege-2026-08-28",
            "parser_sha256": parser_hash,
        })
        bundle.diagnostics['answer_extraction'] = answer_diagnostics
        from .ege_repairs import repair_drafts, exclude_incomplete_tasks, remove_trailing_headings
        bundle.diagnostics['verified_condition_repairs'] = repair_drafts(
            bundle.tasks, bundle.source['tasks_sha256'])
        bundle.diagnostics['excluded_source_tasks'] = exclude_incomplete_tasks(
            bundle.tasks, bundle.source['tasks_sha256'])
        bundle.diagnostics['unique_tasks'] = len(bundle.tasks)
        bundle.diagnostics['answers_matched'] = sum(bool(t.author_answer_latex) or any(
            item.author_answer_latex for item in t.subitems) for t in bundle.tasks)
        bundle.diagnostics['removed_subsection_headings'] = remove_trailing_headings(
            bundle.tasks, bundle.source['tasks_sha256'])
        from .ege_cleanup import clean_ege_drafts
        bundle.diagnostics['text_cleanup'] = clean_ege_drafts(bundle.tasks)
        bundle.diagnostics['tasks_by_exam'] = dict(Counter(
            task.external_id.split('.')[0] for task in bundle.tasks))
        bundle.diagnostics['review_counts'] = dict(Counter(
            'warning' if t.warnings else 'clean' for t in bundle.tasks))
        bundle.diagnostics['tasks_with_images'] = sum(bool(t.images) for t in bundle.tasks)
        bundle.diagnostics['tasks_with_subitems'] = sum(bool(t.subitems) for t in bundle.tasks)
        bundle.diagnostics['tasks_with_author_answer'] = bundle.diagnostics['answers_matched']
    return bundle


def write_bundle(bundle: ImportBundle, output: Path) -> None:
    from .oge_metadata import apply_oge_metadata
    from .ege_metadata import apply_ege_metadata
    for task in bundle.tasks:
        apply_oge_metadata(task, bundle.profile)
        apply_ege_metadata(task, bundle.profile)
    output.mkdir(parents=True, exist_ok=True)
    payload = asdict(bundle)
    (output / "import.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "review.tsv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow([
            "external_id", "source_number", "collection", "topic_original",
            "text_latex", "subitems", "stars", "author_answer_latex",
            "author_solution_latex", "confidence", "warnings", "review_status",
        ])
        for task in bundle.tasks:
            writer.writerow([
                task.external_id,
                task.source_number,
                task.collection_title,
                task.topic_original,
                task.text_latex,
                json.dumps([asdict(item) for item in task.subitems], ensure_ascii=False),
                task.stars,
                task.author_answer_latex,
                task.author_solution_latex,
                f"{task.confidence:.2f}",
                "; ".join(task.warnings),
                task.review_status,
            ])
    lines = [
        f"# Отчёт разбора: {bundle.profile}",
        "",
        f"- Найдено задач: {len(bundle.tasks)}",
        f"- С подпунктами: {bundle.diagnostics['tasks_with_subitems']}",
        f"- С авторским ответом: {bundle.diagnostics['tasks_with_author_answer']}",
        f"- С авторским решением: {bundle.diagnostics['tasks_with_author_solution']}",
        f"- С предупреждениями: {bundle.diagnostics['review_counts'].get('warning', 0)}",
    ]
    if "missing_task_ids" in bundle.diagnostics:
        lines.append(
            "- Пропущено ожидаемых номеров: "
            f"{len(bundle.diagnostics['missing_task_ids'])}")
        if "matched_solutions" in bundle.diagnostics:
            lines.append(
                f"- Однозначно сопоставлено решений: "
                f"{bundle.diagnostics['matched_solutions']}")
        if "physical_order_affected_ids" in bundle.diagnostics:
            lines.append(
                f"- Затронуто нарушениями порядка колонок: "
                f"{len(bundle.diagnostics['physical_order_affected_ids'])}")
        if "answers_matched" in bundle.diagnostics:
            lines.extend([
                f"- Сопоставлено ответов: "
                f"{bundle.diagnostics['answers_matched']}",
                f"- Ответов без задачи: "
                f"{len(bundle.diagnostics.get('answers_without_task') or [])}",
            ])
    lines.extend([
        "", "## Диагностика", "", "```json",
        json.dumps(bundle.diagnostics, ensure_ascii=False, indent=2), "```",
    ])
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", required=True,
        choices=("galitsky", "merzlyak", "shabunin", "feoktistov", "ziv", "shestakov", "ostromogilsky",
                 "ostromogilsky_ege"))
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--solutions", type=Path)
    parser.add_argument(
        "--answers-pdf", type=Path,
        help="Интерактивный PDF с якорями ans:: (обязателен для ostromogilsky)")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pdf-index", type=Path,
                        help="Кэш проверенного индекса PDF для профиля ЕГЭ")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.profile in {"ostromogilsky", "ostromogilsky_ege"} and args.answers_pdf is None:
        raise SystemExit(
            "Для профиля ostromogilsky укажите --answers-pdf с ключом ответов.")
    bundle = bundle_for(
        args.profile, args.tasks, args.solutions,
        answers_pdf=args.answers_pdf, pdf_index_path=args.pdf_index)
    if args.profile == "ostromogilsky" and args.answers_pdf is not None:
        from .ostromogilsky_pdf_geometry import extract_pdf_geometry, attach_pdf_geometry
        from .ostromogilsky_parser import extract_pdf_answers
        geometry = extract_pdf_geometry(args.answers_pdf)
        answers, _ = extract_pdf_answers(args.answers_pdf)
        attach_pdf_geometry(bundle, geometry, answers, args.output / "images")
        from .ostromogilsky_pdf_inequalities import extract_pdf_systems, attach_pdf_systems
        systems = extract_pdf_systems(args.answers_pdf)
        attach_pdf_systems(bundle, systems, answers, args.output / "images")
        from .ostromogilsky_pdf_linear_graphs import extract_pdf_linear_graphs, attach_pdf_linear_graphs
        linear_graphs = extract_pdf_linear_graphs(args.answers_pdf)
        attach_pdf_linear_graphs(bundle, linear_graphs, answers, args.output / "images")
        from .ostromogilsky_pdf_repairs import extract_pdf_repairs, attach_pdf_repairs
        repairs = extract_pdf_repairs(args.answers_pdf)
        attach_pdf_repairs(bundle, repairs, answers, args.output / "images")
        from .ostromogilsky_shared_repairs import extract_shared_repairs, attach_shared_repairs
        shared_repairs = extract_shared_repairs(args.answers_pdf)
        attach_shared_repairs(bundle, shared_repairs, args.output / "images")
        from .ostromogilsky_graph_repairs import extract_graph_repairs, attach_graph_repairs
        graph_repairs = extract_graph_repairs(args.answers_pdf)
        attach_graph_repairs(bundle, graph_repairs, args.output / "images")
        from .ostromogilsky_inequality_figures import extract_inequality_figures, attach_inequality_figures
        inequality_figures = extract_inequality_figures(args.answers_pdf)
        attach_inequality_figures(bundle, inequality_figures, args.output / "images")
        from .ostromogilsky_final_repairs import apply_final_repairs
        apply_final_repairs(bundle, args.answers_pdf, args.output / "images")
        from .ostromogilsky_parser import (
            attach_grid_figures, extract_grid_figures)
        figures = extract_grid_figures(args.answers_pdf)
        attached = attach_grid_figures(
            bundle.tasks, figures, dest=args.output / "images")
        bundle.diagnostics["grid_figures"] = len(attached)
        bundle.diagnostics["tasks_with_images"] = sum(
            bool(task.images) for task in bundle.tasks)
        from .ostromogilsky_final_repairs import copy_referenced_images
        copy_referenced_images(bundle, args.tasks.parent, args.output / "images")
        bundle.diagnostics['tasks_with_author_answer'] = sum(
            bool(task.author_answer_latex) for task in bundle.tasks)
        bundle.diagnostics['review_counts'] = dict(Counter(
            'warning' if task.warnings else 'clean' for task in bundle.tasks))
    if args.profile == "ostromogilsky_ege":
        from .ege_figures import package_ege_images
        from .ege_parser import build_pdf_index
        index = json.loads(args.pdf_index.read_text()) if args.pdf_index else build_pdf_index(args.answers_pdf)
        bundle.diagnostics['image_packaging'] = package_ege_images(
            bundle, args.tasks.parent, args.answers_pdf, args.output / 'images', index)
    write_bundle(bundle, args.output)
    print(json.dumps({k: v for k, v in bundle.diagnostics.items()
                      if k not in {'raw_tex_spans', 'prepared_tex_spans', 'pdf_index', 'answer_extraction', 'image_packaging'}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

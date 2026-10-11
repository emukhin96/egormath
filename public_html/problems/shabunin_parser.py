"""Профиль задачника Шабунина, Прокофьева, Олейник, Соколовой.

«Математика. Алгебра. Начала математического анализа. Профильный уровень.
Задачник для 10–11 классов» (БИНОМ, 2009), OCR Mathpix.

Особенности книги:

- 23 главы с римскими номерами; задача — «IV.12», в OCR обычно
  ``\\item[IV.] 12.``, иногда строка «VIII.1. …» или метка без точки
  (``\\item[V.] 57\\\\``);
- внутри главы — параграфы и уровни сложности («Первый уровень», …),
  в конце главы — «Задачи повышенной сложности»; заголовки в OCR местами
  потеряны, поэтому путь подборки берётся из сверенной таблицы
  ``data/shabunin_structure.json`` по номеру задачи;
- общая формулировка для серии задач: «Решить уравнение (IV.3–IV.9).»
  стоит перед серией, а сами задачи — только формулы. Формулировка
  дописывается в условие каждой задачи серии, номера источника убираются;
- пункты задач и ответов — цифры ``1) 2) 3)``;
- ответы — после каждой главы («Ответы к главе IV»), плотный поток
  ``IV.1. …``; рисунки к ответам подписаны «Рис. N» с нумерацией внутри
  главы и упоминаются в ответах как «рис. N».

Приложение «Материал для подготовки к ЕГЭ» (варианты 2005–2008 гг.) в этот
профиль не входит.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Sequence

from .merzlyak_parser import (
    LEFTOVER_LABEL_RE, _flatten_lists, _heal_ocr_math, _heal_ocr_words,
    _tabular_to_array, normalize_degrees, wrap_answer_numbers)
from .textbook_parser import (
    Marker, TaskDraft, _open_paren_depth, blocks, clean, finalize_draft_images,
    inline_numeric_markers, merge_solutions, numeric_subitem_labels,
    task_from_block)


DATA_DIR = Path(__file__).with_name("data")
STRUCTURE_PATH = DATA_DIR / "shabunin_structure.json"
REPAIRS_PATH = DATA_DIR / "shabunin_repairs.json"

LEVEL_TITLES = {1: "Первый уровень", 2: "Второй уровень", 3: "Третий уровень"}
HARD_TITLE = "Задачи повышенной сложности"

# Римские цифры глав; OCR путает X/Х и I/І с кириллицей.
ROMAN = r"[IVXХІ]{1,6}"
_ROMAN_FIX = str.maketrans({"Х": "X", "І": "I"})

ANSWERS_HEADING_RE = re.compile(
    r"\\section\*?\{\s*ОТВЕТЫ\s+К\s+ГЛАВЕ\s+(?P<roman>" + ROMAN + r")\s*\}")
APPENDIX_RE = re.compile(r"\\section\*?\{\s*МАТЕРИАЛ ДЛЯ ПОДГОТОВКИ К ЕГЭ")
SECTION_RE = re.compile(r"\\section\*?\{")
# ``\item[IV.] 12.`` / ``\item[V.] 57\\`` → строка «IV.12. ».
ITEM_MARKER_RE = re.compile(
    r"\\item\[\s*(?P<roman>" + ROMAN + r")\s*\.?\s*\]\s*(?P<number>\d{1,3})"
    r"\s*\.?(?=\s|\\\\|$)")
# Номер задачи в начале строки после разворачивания списков. «V.9.1) …» —
# пункт сразу за номером.
TASK_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?P<roman>" + ROMAN + r")\s*\.\s*(?P<number>\d{1,3})"
    r"\s*\.?(?=[ \t]|\\\\|$|\d{1,2}\))")
# Номер посреди строки: «IV.246. … IV.247. …». Только с точкой после
# номера и пробелом — так ссылки «(IV.3-IV.9)» не считаются задачами.
INLINE_TASK_MARKER_RE = re.compile(
    r"(?<![\w.])(?P<roman>" + ROMAN + r")\.\s?(?P<number>\d{1,3})\.(?=\s)")
# «(VIII.72-\\ VIII.83)» — серия разорвана переносом строки.
RANGE_BREAK_RE = re.compile(
    r"(?<=\d)\s*([-–—])\s*\\\\\s*\n\s*(?=" + ROMAN + r"\s*\.\s*\d{1,3}\s*\))")
# «(IV.3-IV.9)» — серия задач с общей формулировкой.
RANGE_RE = re.compile(
    r"\s*\(\s*(?:\\mathbf\{)?\s*(?P<r1>" + ROMAN + r")\s*\.\s*(?P<a>\d{1,3})"
    r"\s*[-–—]\s*(?P<r2>" + ROMAN + r")\s*\.\s*(?P<b>\d{1,3})\s*\}?\s*\)"
    r"\s*[.:]?")
# Заголовки внутри потока задач: параграфы, уровни, повышенная сложность,
# подпункты оглавления «1. Градусная и радианная меры угла».
HEADING_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:§\s*\d+\.?[^\n]*|(?:Первый|Второй|Третий)\s+уровень"
    r"[ \t]*(?:\\\\)?|ЗАДАЧИ ПОВЫШЕННОЙ СЛОЖНОСТИ[^\n]*)[ \t]*$")
# Рисунок с подписью «Рис. N» в ответах главы.
FIGURE_RE = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.S)
CAPTION_RE = re.compile(r"\\caption\{\s*Рис\.?\s*(?P<num>\d{1,3})\s*\}")
GRAPHICS_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{(?P<path>[^{}\s\\]+)\}")
FIG_REF_RE = re.compile(r"(?<![\w\\])[Рр]ис\.\s*(?P<num>\d{1,3})(?!\d)")


def roman_to_int(value: str) -> int:
    numerals = {"I": 1, "V": 5, "X": 10, "L": 50}
    value = value.translate(_ROMAN_FIX)
    total = 0
    for index, char in enumerate(value):
        current = numerals[char]
        following = numerals[value[index + 1]] if index + 1 < len(value) else 0
        total += -current if current < following else current
    return total


def load_structure(path: Path = STRUCTURE_PATH) -> dict[str, dict]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    return {chapter["roman"]: chapter for chapter in spec["chapters"]}


def apply_source_repairs(text: str, path: Path = REPAIRS_PATH) -> tuple[str, list[str]]:
    """Сверенные с книгой правки OCR, привязанные к sha256 исходного TEX."""
    if not path.exists():
        return text, []
    spec = json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    applied = []
    for edition in spec.get("editions", []):
        if edition.get("source_sha256") != digest:
            continue
        for patch in edition.get("patches", []):
            count = text.count(patch["before"])
            if count != 1:
                raise ValueError(
                    f"Сверенный фрагмент {patch['id']} встречается {count} раз")
            text = text.replace(patch["before"], patch["after"], 1)
            applied.append(patch["id"])
    return text, applied


# --------------------------------------------------------------------------
# Структура книги
# --------------------------------------------------------------------------

def chapter_title(chapter: dict) -> str:
    return f"Глава {chapter['number']}. {chapter['title']}"


def topic_code(chapter: dict, number: int, text: str) -> str:
    """Тема рубрикатора по параграфу; смешанный раздел — по виду задачи."""
    code = chapter.get("topic", "")
    hard = chapter.get("hard_first")
    if not (hard and number >= hard):
        for item in chapter["paragraphs"]:
            if item["first"] <= number:
                code = item.get("topic") or code
    if isinstance(code, dict):
        kind = "inequality" if re.search(r"(?i)неравенств", text) else "equation"
        code = code[kind]
    return code


def source_path(chapter: dict, number: int) -> list[str]:
    """Глава → параграф → уровень по номеру задачи в главе."""
    path = [chapter_title(chapter)]
    hard = chapter.get("hard_first")
    if hard and number >= hard:
        return path + [HARD_TITLE]
    paragraph = None
    for item in chapter["paragraphs"]:
        if item["first"] <= number:
            paragraph = item
    paragraph_first = 1
    if paragraph:
        path.append(f"§ {paragraph['number']}. {paragraph['title']}")
        paragraph_first = paragraph["first"]
    level = None
    for item in chapter["levels"]:
        # Уровень действует только внутри своего параграфа: у V §3 уровней
        # нет, и «Второй уровень» V §2 туда переходить не должен.
        if paragraph_first <= item["first"] <= number:
            level = item["level"]
    if level:
        path.append(LEVEL_TITLES[level])
    return path


# --------------------------------------------------------------------------
# Подготовка текста
# --------------------------------------------------------------------------

def _normalize_roman(match: re.Match) -> str:
    return match.group(0).translate(_ROMAN_FIX)


def _unwrap_range_sections(text: str) -> str:
    """``\\section*{Вычислить (IX.110-IX.113).}`` — формулировка серии."""
    return re.sub(
        r"\\section\*?\{(?P<title>[^{}]*\(\s*" + ROMAN + r"\s*\.\s*\d[^{}]*)\}",
        lambda match: "\n" + match.group("title").strip() + "\n", text)


def _join_hyphenation(text: str) -> str:
    """«Указа- ние» — перенос OCR; «пяти- и шестизначные» — нет."""
    return re.sub(r"(?<=[а-яё])-\s+(?=[а-яё])(?!(?:и|или)\s)", "", text)


def _join_page_breaks(text: str) -> str:
    """Перенос страницы посреди фразы: «На крышке первой\\n\\nкоробки …»."""
    return re.sub(r"(?<=[а-яё,])[ \t]*\n(?:[ \t]*\n)+[ \t]*(?=[а-яё])", " ", text)


def _renumber_enumerate(text: str) -> str:
    """``\\item`` без метки внутри enumerate → ``\\item[k)]``.

    OCR кладёт пункты нескольких задач и ответов в один enumerate
    («XIV.110. \\begin{enumerate} \\item … XIV.111. \\item …», «IV.45. 1) …
    \\item …»). Отсчёт продолжает последнюю метку «k)» после ближайшего
    номера задачи, а номер задачи без меток начинает отсчёт заново.
    """
    out = []
    counters: list[int] = []
    pos = 0
    token_re = re.compile(
        r"\\begin\{enumerate\}|\\end\{enumerate\}|\\item(?!\[)(?![a-zA-Z])"
        r"|\\setcounter\{enumi+\}\{(?P<counter>\d+)\}")
    marker_re = re.compile(
        r"(?:(?m:^)[ \t]*|(?<![\w.]))" + ROMAN + r"\s?\.\s?\d{1,3}\.(?=\s|\d)")
    label_re = re.compile(r"(?:^|[\s;$])(\d{1,2})\)(?=[\s$])")
    math_re = re.compile(r"\$\$.*?\$\$|\$[^$]*\$", re.S)

    def labels_in(segment: str) -> list[int]:
        """Метки «k)» вне формул и скобок: «(-2 ; 2)», «[-1; 0)» — не метки."""
        plain = math_re.sub(" $ ", segment)
        return [int(found.group(1)) for found in label_re.finditer(plain)
                if found.group(1) != "0"
                and _open_paren_depth(plain[:found.start(1)]) == 0]
    for match in token_re.finditer(text):
        segment = text[pos:match.start()]
        out.append(segment)
        token = match.group(0)
        if counters:
            markers = list(marker_re.finditer(segment))
            if markers:
                segment = segment[markers[-1].end():]
                counters[-1] = 0
            labels = labels_in(segment)
            if labels:
                counters[-1] = max(labels)
        if match.group("counter"):
            # «\\setcounter{enumi}{1}» — OCR продолжает нумерацию после
            # разрыва списка рисунками или страницей.
            if counters:
                counters[-1] = int(match.group("counter"))
            token = ""
        elif token == r"\begin{enumerate}":
            # «IV.5. 1) … \\begin{enumerate} \\item …» — список продолжает
            # пункты, начатые в строке номера задачи.
            before = text[max(0, match.start() - 600):match.start()]
            markers = list(marker_re.finditer(before))
            labels = labels_in(before[markers[-1].end():]) if markers else []
            counters.append(max(labels, default=0))
        elif token == r"\end{enumerate}":
            if counters:
                counters.pop()
        elif re.match(r"\s*" + ROMAN + r"\s?\.\s?\d{1,3}\.", text[match.end():]):
            # «\\item XXIII.19.» — OCR сделал пунктом сам номер задачи.
            token = "\n"
        elif counters:
            counters[-1] += 1
            token = rf"\item[{counters[-1]})]"
        out.append(token)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


# «$\left.Q(x)=2x^2+4 ; \quad 4\right) \quad Q(x)=…$» — метка пункта «4)»
# стала правой скобкой формулы.
_LEFT_DOT_LABEL_RE = re.compile(
    r"\$\s*\\left\.(?P<body>[^$\n]*?)[;,]\s*(?:\\quad\s*)?(?P<label>\d{1,2})"
    r"\\right\)\s*(?:\\quad\s*)?")
# То же посреди формулы: «$a+2\pi k, \left.\pm b ; \quad 3\right) c$».
_INNER_LEFT_DOT_LABEL_RE = re.compile(
    r"(?<=[,;])\s*\\left\.(?P<body>[^$\n]*?)[;,]\s*(?:\\quad\s*)?"
    r"(?P<label>\d{1,2})\\right\)\s*(?:\\quad\s*)?")
# «радиусом $5 ; 2$ ) окружность» — метка «2)» разорвана долларом.
_DOLLAR_LABEL_RE = re.compile(r";\s*(?P<label>\d{1,2})\$\s*\)")


def _heal_item_labels(text: str) -> str:
    """Типовые OCR-поломки цифровых меток пунктов."""
    # «з)» — тройка, распознанная как буква.
    text = re.sub(r"(?m)(^[ \t]*|;\s*)з\)", r"\g<1>3)", text)
    # «2 )» — пробел внутри метки.
    text = re.sub(r"(?m)(^[ \t]*|;\s*)([1-9])[ \t]+\)(?=\s)", r"\1\2)", text)
    # «$2) \forall x…$» — метка ушла внутрь формулы в начале строки.
    text = re.sub(r"(?m)^([ \t]*)\$(\d{1,2})\)\s*", r"\1\2) $", text)
    text = _LEFT_DOT_LABEL_RE.sub(
        lambda m: "$" + m.group("body").rstrip() + "$; " + m.group("label") + ") $",
        text)
    text = _INNER_LEFT_DOT_LABEL_RE.sub(
        lambda m: " " + m.group("body").strip() + "$; " + m.group("label") + ") $",
        text)
    return _DOLLAR_LABEL_RE.sub(lambda m: "$; " + m.group("label") + ")", text)


def _join_split_brackets(text: str) -> str:
    """«$\\left[a\\right.$, $\\left.b\\right]$» — Mathpix режет промежуток по запятой."""
    text = re.sub(
        r"\\right\.\s*\$\s*,\s*\$\s*(?:\\displaystyle\s*)?\\left\.\s*", ", ", text)
    # Без «\\right.» слева «\\left.» нужен для пары с правой скобкой.
    return re.sub(
        r"\s*\$\s*,\s*\$\s*(?:\\displaystyle\s*)?(?=\\left\.)", ", ", text)


def prepare_shabunin_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = _join_split_brackets(text)
    text = _unwrap_range_sections(text)
    text = RANGE_BREAK_RE.sub(r"\1", text)
    # «xiii.45.» / «XXIII.14» отдельной строкой — номер задачи строчными
    # буквами или без точки.
    text = re.sub(r"(?m)^[ \t]*([ivx]{1,6}|" + ROMAN + r")\s?\.\s?(\d{1,3})\.?[ \t]*$",
                  lambda m: m.group(1).upper().translate(_ROMAN_FIX) + "."
                  + m.group(2) + ".", text)
    # «XIII.44. I) …» — первая метка пункта распознана как римская I.
    text = re.sub(r"(?<=\d\. )I\)(?=\s)", "1)", text)
    text = ITEM_MARKER_RE.sub(
        lambda m: "\n" + m.group("roman").translate(_ROMAN_FIX) + "."
        + m.group("number") + ". ", text)
    text = TASK_MARKER_RE.sub(
        lambda m: m.group(0).translate(_ROMAN_FIX), text)
    text = re.sub(r"\\hspace\{0pt\}\s*", "", text)
    # «в точке ( $1 ;-8$ )» — скобки координат вынесены из формулы.
    text = re.sub(r"(?<![\w\\])\(\s*\$([^$\n]+)\$\s*\)", r"$(\1)$", text)
    # Делимость «a ⋮ b»: в книге это отношение высотой с цифру. Сайт и
    # пакеты LaTeX знают макрос \divby; высокий \vdots выпирает из строки.
    text = re.sub(r"\$\s*⋮\s*\$", r" \\divby ", text)
    text = re.sub(r"(?:\\vdots(?![a-zA-Z])|⋮)\s*", r"\\divby ", text)
    text = _renumber_enumerate(text)
    text = _flatten_lists(text)
    text = _heal_item_labels(text)
    text = re.sub(r"\\\\\[0pt\]", r"\\\\", text)
    # Ячейки таблиц в OCR обёрнуты в «$…$»: внутри выносной array доллары
    # недопустимы, а ``_tabular_to_array`` снимает только ``\\(…\\)``.
    text = re.sub(
        r"\\begin\{tabular\}.*?\\end\{tabular\}",
        lambda m: re.sub(r"(?<!\$)\$([^$]+)\$", r"\\(\1\\)", m.group(0)),
        text, flags=re.S)
    text = _tabular_to_array(text)
    # Диакритика OCR на латинице и знаках («a ̈-1»).
    text = re.sub(r"(?<![А-Яа-яЁё])[\u0300-\u036f]", "", text)
    text = _join_hyphenation(text)
    text = re.sub(r"(?<![а-яё])с\s+м(?![а-яё])", "см", text)
    text = _heal_ocr_words(text)
    text = _join_page_breaks(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# --------------------------------------------------------------------------
# Задачи
# --------------------------------------------------------------------------

def chapter_zones(text: str) -> list[tuple[str, str, str]]:
    """(римский номер, текст задач, текст ответов) по главам."""
    zones = []
    start = 0
    for match in ANSWERS_HEADING_RE.finditer(text):
        roman = match.group("roman").translate(_ROMAN_FIX)
        following = SECTION_RE.search(text, match.end())
        end = following.start() if following else len(text)
        zones.append((roman, text[start:match.start()], text[match.end():end]))
        start = end
    return zones


def task_markers(text: str, roman: str) -> list[Marker]:
    """Номера задач главы, монотонно возрастающие.

    Номер в начале строки надёжен; номер посреди строки принимается, только
    если продолжает нумерацию (не дальше чем через две задачи).
    """
    candidates = []
    for match in TASK_MARKER_RE.finditer(text):
        candidates.append((match.start(), match.end(), match, True))
    line_starts = {start for start, *_ in candidates}
    for match in INLINE_TASK_MARKER_RE.finditer(text):
        if not any(start <= match.start() < end for start, end, *_ in candidates):
            candidates.append((match.start(), match.end(), match, False))
    candidates.sort(key=lambda item: item[0])
    result = []
    previous = 0
    for start, end, match, at_line_start in candidates:
        if match.group("roman").translate(_ROMAN_FIX) != roman:
            continue
        number = int(match.group("number"))
        if number <= previous:
            continue
        if not at_line_start and start not in line_starts and number > previous + 3:
            continue
        result.append(Marker(start, end, f"{roman}.{number}"))
        previous = number
    return result


def extract_range_stems(text: str, roman: str) -> tuple[str, dict[int, str], list[dict]]:
    """Вырезает формулировки серий и возвращает {номер задачи: формулировка}.

    Формулировка — строка, в которой стоит «(IV.3-IV.9)»; её место в
    потоке занимает пустая строка, чтобы она не прилипла к предыдущей задаче.
    """
    stems: dict[int, str] = {}
    found = []
    out = []
    pos = 0
    for match in RANGE_RE.finditer(text):
        if match.group("r1").translate(_ROMAN_FIX) != roman:
            continue
        line_start = text.rfind("\n", 0, match.start()) + 1
        if line_start < pos:
            continue
        line_end = text.find("\n", match.end())
        line_end = len(text) if line_end < 0 else line_end
        tail = text[match.end():line_end]
        if tail.strip() not in {"", r"\\"}:
            # Ссылка на серию внутри фразы, а не общая формулировка.
            continue
        stem = text[line_start:match.start()].strip()
        stem = re.sub(r"\s*(?:\\\\)\s*$", "", stem).strip()
        if not stem:
            continue
        first, last = int(match.group("a")), int(match.group("b"))
        stem = re.sub(r"[.:;\s]+$", "", stem) + ":"
        for number in range(first, last + 1):
            # Пересекающиеся серии («XV.41–XV.45», «XV.45–XV.47») — у номера
            # действует ближайшая предшествующая формулировка.
            stems[number] = stem
        found.append({"first": f"{roman}.{first}", "last": f"{roman}.{last}",
                      "stem": stem})
        out.append(text[pos:line_start])
        out.append("\n")
        pos = line_end
    out.append(text[pos:])
    return "".join(out), stems, found


def _heading_key(line: str) -> str:
    line = re.sub(r"\\section\*?\{|\}|\\\\", " ", line)
    line = re.sub(r"^\s*(?:\d{1,2}\s*[.)]\s*)?", "", line)
    line = line.replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"[\s.]+", " ", line).strip().lower()


def _strip_subsection_headings(body: str, titles: set[str]) -> str:
    """Строки-подзаголовки параграфа («3. Пересечение и объединение …»).

    OCR оформляет их то заголовком, то пунктом списка — тогда они
    прилипают к последнему подпункту предыдущей задачи.
    """
    if not titles:
        return body
    return "\n".join(
        line for line in body.split("\n") if _heading_key(line) not in titles)


def _clean_task_body(body: str, titles: set[str] = frozenset()) -> str:
    body = _strip_subsection_headings(body, titles)
    body = HEADING_LINE_RE.sub("", body)
    body = re.sub(r"\\section\*?\{[^{}]*\}", "", body)
    body = re.sub(r"(?m)^\s*\}\s*$", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


_OWN_INSTRUCTION_RE = re.compile(
    r"(?:Найти|Найдите|Решить|Решите|Вычислить|Вычислите|Доказать|Докажите|"
    r"Построить|Постройте|Определить|Указать|Выяснить|Исследовать|Упростить|"
    r"Сравнить|Показать|При\s+как)")


def _with_stem(body: str, stem: str) -> str:
    """Формулировка серии + условие задачи.

    Если задача начинается собственным заданием («Найти все решения…»,
    «При каком $a$…»), общая формулировка не нужна (канон QA § 4.5);
    утверждение («Число … делится на 16») её, наоборот, требует.
    """
    if not stem:
        return body
    if _OWN_INSTRUCTION_RE.match(body.lstrip()):
        return body
    return stem + "\n" + body if body else stem


# --------------------------------------------------------------------------
# Ответы
# --------------------------------------------------------------------------

def extract_answer_figures(text: str) -> tuple[str, dict[int, list[str]], list[str]]:
    """Подписанные рисунки «Рис. N» уходят в индекс, остальные остаются."""
    index: dict[int, list[str]] = {}
    unnamed: list[str] = []

    def replace(match: re.Match) -> str:
        block = match.group(0)
        paths = [m.group("path") for m in GRAPHICS_RE.finditer(block)]
        caption = CAPTION_RE.search(block)
        if caption and paths:
            index.setdefault(int(caption.group("num")), []).extend(paths)
            return "\n"
        unnamed.extend(paths)
        return block

    return FIGURE_RE.sub(replace, text), index, unnamed


def attach_answer_figures(text: str, index: dict[int, list[str]]) -> tuple[str, set[int]]:
    """«рис. 5» в ответе → ``\\includegraphics{файл}`` того же рисунка."""
    used: set[int] = set()

    def replace(match: re.Match) -> str:
        number = int(match.group("num"))
        paths = index.get(number)
        if not paths:
            return match.group(0)
        used.add(number)
        return " ".join(rf"\includegraphics{{{path}}}" for path in paths)

    return FIG_REF_RE.sub(replace, text), used


_DOLLAR_SPAN_RE = re.compile(r"(?<!\$)\$(?!\$)[^$]*\$")
_LABEL_IN_MATH_RE = re.compile(
    r";\s*(?:\\quad\s*)?(?P<label>[1-9]\d?)\)(?=[\s(\[]|\\[a-z{])")


def _bracket_depth(prefix: str) -> int:
    """Глубина скобок с учётом промежутков «(a; b]» и «[a; b)»."""
    depth = 0
    for char in prefix:
        if char in "([":
            depth += 1
        elif char in ")]" and depth:
            depth -= 1
    return depth


def _split_labels_in_math(text: str, roman: str = "") -> str:
    """Метка пункта или номер задачи внутри формулы ответа закрывает её.

    «$\\{1, a\\} ; 2) \\oslash, …$», «$(-3 ; 2] ; \\quad 2)(1 ; 3)$»,
    «$… \\mathbf{X} .177 .1)[8 ;+\\infty)$».
    """
    task_re = re.compile(
        r"(?:\\mathbf\{\s*)?(?<![A-Za-z])" + re.escape(roman)
        + r"\s*\}?\s*\.\s*(?P<number>\d{1,3})\s*\.\s*") if roman else None

    def fix_span(match: re.Match) -> str:
        inner = match.group(0)[1:-1]
        cuts = []
        lead = re.match(r"\s*(?P<label>[1-9]\d?)\)", inner)
        if lead:
            # «$1)[8 ;+\\infty)$» — метка в самом начале формулы.
            cuts.append((lead.start(), lead.end(), f"{lead.group('label')}) $"))
        for found in _LABEL_IN_MATH_RE.finditer(inner):
            if _bracket_depth(inner[:found.start()]) == 0:
                cuts.append((found.start(), found.end(),
                             f"$; {found.group('label')}) $"))
        if task_re:
            for found in task_re.finditer(inner):
                cuts.append((found.start(), found.end(),
                             f"$ {roman}.{found.group('number')}. $"))
        if not cuts:
            return match.group(0)
        cuts.sort()
        out = []
        pos = 0
        for start, end, replacement in cuts:
            if start < pos:
                continue
            out.append(inner[pos:start])
            out.append(replacement)
            pos = end
        out.append(inner[pos:])
        value = ("" if lead else "$") + "".join(out) + "$"
        # «X.177. $1)[8 ;…$» — метка сразу за вырезанным номером задачи.
        value = re.sub(r"(\d\. )\$\s*([1-9]\d?)\)\s*", r"\1\2) $", value)
        value = re.sub(r"\$\s*(?:\\quad\s*)*\$", "", value)
        return re.sub(r"\$\s*([.;,])\s*\$", r"\1 ", value)

    return _DOLLAR_SPAN_RE.sub(fix_span, text)


def _wrap_answer_specials(text: str) -> str:
    """Периодические дроби «1,069(4)» и «±1» вне формул — в ``$…$``."""
    out = []
    pos = 0
    for match in _DOLLAR_SPAN_RE.finditer(text):
        chunk = text[pos:match.start()]
        chunk = re.sub(r"(?<![\d$])(\d+,\d*)\s*\((\d+)\)", r"$\1(\2)$", chunk)
        chunk = re.sub(r"±\s*(\d+(?:,\d+)?)", r"$\\pm \1$", chunk)
        out.append(chunk)
        out.append(match.group(0))
        pos = match.end()
    chunk = text[pos:]
    chunk = re.sub(r"(?<![\d$])(\d+,\d*)\s*\((\d+)\)", r"$\1(\2)$", chunk)
    chunk = re.sub(r"±\s*(\d+(?:,\d+)?)", r"$\\pm \1$", chunk)
    out.append(chunk)
    return "".join(out)


def _unbold_task_numbers(text: str, roman: str) -> str:
    """«\\mathbf{X . 5 2 . ~ 1 ) ~}» внутри формулы → «X.52. 1)»."""
    def fix(match: re.Match) -> str:
        squeezed = re.sub(r"[\s~]+", "", match.group(1))
        found = re.fullmatch(
            r"(?P<roman>" + ROMAN + r")\.(?P<number>\d{1,3})\.?(?P<label>\d\))?",
            squeezed)
        if not found or found.group("roman").translate(_ROMAN_FIX) != roman:
            return match.group(0)
        label = found.group("label")
        return f" {roman}.{found.group('number')}. " + (label + " " if label else "")

    return re.sub(r"\\mathbf\{([^{}]*)\}", fix, text)


_INTERVAL = (r"[\[(]\s*[-+]?\s*(?:\d+(?:,\d+)?|\\infty|∞)\s*;\s*[-+]?\s*"
             r"(?:\d+(?:,\d+)?|\\infty|∞)\s*[\])]")
_INTERVAL_CHAIN_RE = re.compile(
    _INTERVAL + r"(?:\s*(?:U|∪|\\cup)\s*" + _INTERVAL + r")*")


_NUM = r"[-+]?\s*\d+(?:,\d+)?"
_TUPLE_RE = re.compile(r"\(\s*" + _NUM + r"(?:\s*;\s*" + _NUM + r"){2,}\s*\)")


def _wrap_bare_intervals(text: str) -> str:
    """«[-5; -3] U [3; 5]» вне формулы → ``$[-5; -3] \\cup [3; 5]$``."""
    def wrap(chunk: str) -> str:
        # Тройки и пары координат «(2;3;5)» — целиком одна формула.
        chunk = _TUPLE_RE.sub(lambda m: "$" + m.group(0) + "$", chunk)
        return _INTERVAL_CHAIN_RE.sub(
            lambda m: "$" + re.sub(r"\s*(?:U|∪)\s*", r" \\cup ", m.group(0)) + "$",
            chunk)

    out = []
    pos = 0
    for match in _DOLLAR_SPAN_RE.finditer(text):
        out.append(wrap(text[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(wrap(text[pos:]))
    return "".join(out)


def prepare_answers(text: str, roman: str = "") -> str:
    # «$E(f)=\\{0\\} ;$ 2) …» — разделитель пунктов ушёл внутрь формулы.
    text = re.sub(r"\s*([;,])\s*(?:\\quad\s*)*\$(?=\s+[1-9]\d?\)\s)", r"$\1", text)
    text = _wrap_bare_intervals(text)
    text = re.sub(r"(?<![A-Za-zА-Яа-яЁё])" + ROMAN + r"(?=\s*\.\s*\d)",
                  _normalize_roman, text)
    if roman:
        text = _unbold_task_numbers(text, roman)
        # «XII.24, 1)», «XXIII.14 1)» — у номера пропала или исказилась точка.
        text = re.sub(
            r"(?<![\w.])(" + re.escape(roman) + r")\.(\d{1,3}),?\s+(?=1\)\s)",
            r"\1.\2. ", text)
    text = re.sub(r"\\\\\[0pt\]", r"\\\\", text)
    text = _split_labels_in_math(text, roman)
    return _wrap_answer_specials(text)


def answer_markers(text: str, allowed: set[str]) -> list[Marker]:
    """Границы ответов главы: только возрастающие номера."""
    result = []
    previous = 0
    for marker in inline_numeric_markers(text, allowed):
        number = int(marker.external_id.split(".")[1])
        if number <= previous:
            continue
        result.append(marker)
        previous = number
    return result


# --------------------------------------------------------------------------
# Единицы измерения
# --------------------------------------------------------------------------

# Единица внутри формулы после числа: «$20 к м$», «$50 м / м и н$»,
# «$5 \\kappa м / u$» (OCR: u — «ч», латинская c — «с»), «$12 c м^{3}$».
_UNIT_WORDS = {
    "км": "км", "κм": "км", "см": "см", "cм": "см", "мм": "мм", "м": "м",
    "кг": "кг", "г": "г", "мин": "мин", "ч": "ч", "с": "с", "мл": "мл",
    "л": "л", "т": "т",
}
_PER_WORDS = {"ч": "ч", "u": "ч", "c": "с", "с": "с", "мин": "мин"}
_UNIT_RE = re.compile(
    r"(?:(?<=[\d}])|(?<=\\pi))\s*(?P<unit>(?:\\kappa|к)\s*м|[сc]\s*м|м\s*м|м\s*и\s*н|м\s*л|к\s*г"
    r"|м|г|ч|с|л|т)(?![а-яё])"
    r"(?P<per>\s*/\s*(?:м\s*и\s*н|ч|u|c|с)(?![а-яё\w]))?"
    r"(?P<power>\s*\^\s*\{?\s*[23]\s*\}?)?"
    r"(?=\s*(?:[,.;:)]|\\quad|\\text|$))")


def _unit_word(match: re.Match) -> str:
    unit = re.sub(r"\s+|\\kappa", lambda m: "к" if "kappa" in m.group(0) else "",
                  match.group("unit"))
    unit = _UNIT_WORDS.get(unit, unit)
    per = match.group("per")
    if per:
        unit += "/" + _PER_WORDS[re.sub(r"[\s/]+", "", per)]
    power = match.group("power")
    if power:
        unit += "$^{" + re.search(r"[23]", power).group(0) + "}$"
    return unit


def normalize_cyrillic_units(value: str) -> str:
    """Число — в формуле, единица — текстом (канон QA § 4.6)."""
    if not value or "$" not in value:
        return value

    def math_piece(piece: str) -> str:
        """«, y=4» → «, $y=4$»: пунктуация между формулами — текст."""
        lead = re.match(r"\s*(?:(?:[,.;:]|\\quad)\s*)*", piece).group(0)
        rest = piece[len(lead):].strip()
        lead = re.sub(r"\\quad", " ", lead).strip()
        return (lead + " " if lead else "") + ("$" + rest + "$" if rest else "")

    def fix_span(match: re.Match) -> str:
        inner = match.group(0)[1:-1]
        out = []
        pos = 0
        for found in _UNIT_RE.finditer(inner):
            out.append(math_piece(inner[pos:found.start()]))
            out.append(" " + _unit_word(found))
            pos = found.end()
        if not out:
            return match.group(0)
        tail = math_piece(inner[pos:])
        if tail:
            out.append(("" if tail[0] in ",.;:" else " ") + tail)
        return re.sub(r"\s+([,.;:])", r"\1", "".join(out)).strip()

    return _DOLLAR_SPAN_RE.sub(fix_span, value)


def _finish_value(value: str) -> str:
    # «$\\taskpic{2}$» — рисунок не формула (иначе после финальной обработки
    # рисунков остаётся висячий «$»).
    value = re.sub(r"\$\s*(\\taskpic\{[^{}]+\})\s*\$", r"\1", value or "")
    # «$… . \\quad$» — хвост разделителя OCR в конце формулы.
    value = re.sub(r"\s*\.?\s*(?:\\quad\s*)+\$(?=\s*[.;,]?\s*$)", "$", value)
    # «$-1$- наим.», «$1+2\\sqrt{3}-$ наиб.» — тире OCR перед пояснением.
    value = re.sub(r"\s*-\s*\$\s*(?=наи[мб])", "$ — ", value)
    value = re.sub(r"\$\s*-\s*(?=наи[мб])", "$ — ", value)
    # «1)\\ -8» — перенос строки сразу после метки пункта.
    value = re.sub(r"^\s*(?:\\\\\s*)+", "", value)
    value = _join_split_halves(value)
    value = _unwrap_math_prose(value)
    return _wrap_lone_braces(normalize_cyrillic_units(value))


# Проза внутри строчной формулы («$\ln ^{2} x>… \text { при } x>2$»): на
# сайте русский текст в формуле идёт чужим шрифтом и не переносится.
# Выносим \text{…} с кириллицей наружу, только вне скобок и окружений:
# «если» в кусочной функции, русские индексы и \operatorname остаются.
_TEXT_CMD_RE = re.compile(r"\\(?:text|mbox|textrm)\s*\{")
_PROSE_DEPTH_RE = re.compile(
    r"\\(?:left|begin)(?![a-zA-Z])|(?<!\\)\{|\\(?:right|end)(?![a-zA-Z])|(?<!\\)\}")


def _brace_end(text: str, opening: int) -> int:
    depth = 0
    for pos in range(opening, len(text)):
        char = text[pos]
        if char == "\\":
            continue
        if char == "{" and text[pos - 1] != "\\":
            depth += 1
        elif char == "}" and text[pos - 1] != "\\":
            depth -= 1
            if depth == 0:
                return pos
    return -1


def _split_math_prose(body: str) -> list[tuple[bool, str]] | None:
    """[(формула?, кусок)] или None, если прозы на верхнем уровне нет."""
    pieces = []
    depth = 0
    start = pos = 0
    found = False
    while pos < len(body):
        command = _TEXT_CMD_RE.match(body, pos)
        if command and depth == 0:
            end = _brace_end(body, command.end() - 1)
            content = body[command.end():end] if end > 0 else ""
            # Русские слова и знаки предложения («\text {. }») — проза.
            if end > 0 and (re.search(r"[А-Яа-яЁё]", content)
                            or re.fullmatch(r"[\s.,;:]+", content)):
                pieces.append((True, body[start:pos]))
                pieces.append((False, content))
                found = True
                start = pos = end + 1
                continue
        token = _PROSE_DEPTH_RE.match(body, pos)
        if token:
            opening = token.group(0) in ("{",) or token.group(0).startswith(("\\left", "\\begin"))
            depth += 1 if opening else -1
            pos = token.end()
            continue
        pos += 2 if body.startswith("\\", pos) else 1
    pieces.append((True, body[start:]))
    if not found or depth != 0 or not any(
            re.search(r"[А-Яа-яЁё]", piece) for is_math, piece in pieces if not is_math):
        return None
    return pieces


_FLAT_SET_PAIR_RE = re.compile(r"\\left\\\{((?:(?!\\left|\\right).)*?)\\right\\\}", re.S)


_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)


def _unwrap_math_prose(value: str) -> str:
    """Строчная формула с прозой — формулы и текст вперемешку; выключная
    («$$\ln … \text { при } x>2 .$$») — строка текста со строчными."""
    def fix_display(match: re.Match) -> str:
        body = match.group(1) or match.group(2)
        fixed = fix_body(body, display=True)
        return match.group(0) if fixed is None else fixed

    def fix(match: re.Match) -> str:
        fixed = fix_body(match.group(0)[1:-1])
        return match.group(0) if fixed is None else fixed

    def fix_body(body: str, display: bool = False) -> str | None:
        if not _TEXT_CMD_RE.search(body):
            return None
        # Скобки множества вокруг фразы («\left\{\text{Число} …\right\}»)
        # — обычные: после выноса фразы половины окажутся в разных формулах.
        plain = _FLAT_SET_PAIR_RE.sub(r"\\{\1\\}", body)
        pieces = _split_math_prose(plain)
        if pieces is None:
            return None
        display = display or body.lstrip().startswith("\\displaystyle")
        out = ""
        for is_math, piece in pieces:
            piece = " ".join(piece.split())
            if is_math:
                piece = re.sub(r"^\\displaystyle\s*", "", piece)
                # Знак предложения в конце формулы («…\frac{2}{y-3},», «2,9 .»)
                # — за формулу; точку «\right.» не трогаем.
                tail = re.search(r"(?<!\\right)\s*([,.;:])$", piece)
                if tail:
                    piece = piece[:tail.start()].rstrip()
                if not piece:
                    continue
                if display and "\\frac" in piece:
                    piece = "\\displaystyle " + piece
                glue = "" if not out or out.endswith((" ", "(")) or piece.startswith("\\}") else " "
                out += glue + "$" + piece + "$" + (tail.group(1) if tail else "")
            elif piece:
                glue = "" if not out or piece[0] in ".,;:)" or out.endswith("\\{$") else " "
                out += glue + piece
        return out.strip()

    value = _DISPLAY_MATH_RE.sub(fix_display, value or "")
    return _DOLLAR_SPAN_RE.sub(fix, value)


# Метка сайта для задач с параметром (как у ОГЭ-22, oge_metadata).
PARAMETER_TAG = "задача с параметром"
# Буква параметра — строчная латинская (регистр учитывается и под re.I).
_PARAM_LETTER = r"\$\s*(?:\\displaystyle\s*)?(?-i:[a-dk-mpqr]|\\lambda)\s*\$"
_PARAMETER_RE = re.compile(
    # «параметр(а, ы…)», но не «параметрически», «параметризация».
    r"параметр(?:а|ы|ов|ом|ами|ах|у|е)?\b"
    r"|(?:при|для)\s+(?:каких|всех|любых|каждого|каждом|каком)\s+"
    r"(?:(?:действительных|целых|натуральных)\s+)?(?:значени\w*\s+)?" + _PARAM_LETTER
    + r"|(?:найти|найдите|определить|указать)\s+(?:все\s+)?(?:\w+\s+)?значени\w*\s+" + _PARAM_LETTER
    + r"|в\s+зависимости\s+от\s+(?:значени\w*\s+)?" + _PARAM_LETTER,
    re.I)


# Не задача с параметром: доказательство («при любых $a$…», константа $C$
# в решении ДУ) и уравнения при заданных значениях («при указанных
# значениях параметра $a$: $a=-2$, $a=3$»).
_NOT_PARAMETER_RE = re.compile(r"^\s*(?:Доказать|Докажите|Показать)|при\s+указанных\s+значени", re.I)


def _tag_parameter_task(task: TaskDraft) -> None:
    text = " ".join([task.text_latex] + [item.text_latex for item in task.subitems])
    if (_PARAMETER_RE.search(text) and not _NOT_PARAMETER_RE.search(text)
            and PARAMETER_TAG not in task.tags):
        task.tags.append(PARAMETER_TAG)


# «$\left(a\right.$; $\displaystyle \left.b\right)$» — OCR разорвал пару
# на две формулы по «;». Формула с «\left.» в начале — всегда вторая
# половина такой пары, поэтому половины склеиваются в одну формулу.
_SPLIT_HALVES_RE = re.compile(
    r"\s*\\right\.\s*\$\s*([;,]?)\s*\$\s*(?:\\displaystyle\s*)?\\left\.\s*")


def _join_split_halves(value: str) -> str:
    return _SPLIT_HALVES_RE.sub(
        lambda m: f" {m.group(1)} " if m.group(1) else " ", value or "")


# «…x>0 ;\end{array}\right.$» — знак перечисления подпунктов остался
# внутри системы, куда strip_subitem_punct не заглядывает.
_SYSTEM_TAIL_PUNCT_RE = re.compile(
    r"\s*(?:[;,.]|\\text\s*\{\s*[;,.]\s*\})\s*"
    r"(?=\\end\{(?:array|aligned|cases)\}\s*\\right\.\s*\$\s*$)")


def _strip_system_tail_punct(value: str) -> str:
    """Как strip_subitem_punct: точка законченного предложения остаётся."""
    match = _SYSTEM_TAIL_PUNCT_RE.search(value or "")
    if not match:
        return value
    if "." in match.group(0) and value.lstrip()[:1].isupper():
        return value
    return value[:match.start()] + value[match.end():]


_QUAD_SEP_RE = re.compile(r"\s*([,;])\s*\\quad(?![a-zA-Z])\s*")
_DEPTH_TOKEN_RE = re.compile(
    r"\\(?:left|begin)(?![a-zA-Z])|\\\{|(?<!\\)\{"
    r"|\\(?:right|end)(?![a-zA-Z])|\\\}|(?<!\\)\}")


def _top_level_quad_split(body: str) -> list[tuple[str, str]]:
    """Части формулы между «, \\quad» вне скобок и окружений: [(знак, часть)]."""
    depth = 0
    parts = []
    start = 0
    sign = ""
    pos = 0
    while pos < len(body):
        token = _DEPTH_TOKEN_RE.match(body, pos)
        if token:
            text = token.group(0)
            opening = text in ("{", "\\{") or text.startswith(("\\left", "\\begin"))
            depth += 1 if opening else -1
            pos = token.end()
            continue
        if body.startswith("\\", pos):
            pos += 2
            continue
        sep = _QUAD_SEP_RE.match(body, pos) if depth == 0 else None
        if sep:
            parts.append((sign, body[start:pos]))
            sign = sep.group(1)
            start = pos = sep.end()
            continue
        pos += 1
    parts.append((sign, body[start:]))
    return parts


def _split_quad_list(value: str) -> str:
    """«$A, \\quad B$» в ответе — перечисление: «$A$, $B$» (канон § 5)."""
    def fix(match: re.Match) -> str:
        body = match.group(0)[1:-1]
        parts = _top_level_quad_split(body)
        if len(parts) < 2 or not all(part.strip() for _sign, part in parts):
            return match.group(0)
        display = body.lstrip().startswith("\\displaystyle")
        out = []
        for sign, part in parts:
            part = part.strip()
            if display and "\\frac" in part and not part.startswith("\\displaystyle"):
                part = "\\displaystyle " + part
            out.append((sign + " " if sign else "") + "$" + part + "$")
        return "".join(out)

    return _DOLLAR_SPAN_RE.sub(fix, value or "")


def _wrap_lone_braces(value: str) -> str:
    """«$A \\equiv \\{$Число 54 … на 3 \\}» — скобка множества вне формулы.

    OCR закрывает формулу сразу после «\\{», и закрывающая «\\}» остаётся
    в тексте сырой командой. Скобки вне формул оборачиваем в ``$…$``.
    """
    if not value or ("\\}" not in value and "\\{" not in value):
        return value
    def fix(chunk: str) -> str:
        return re.sub(r"\s*\\([{}])",
                      lambda m: ("" if m.group(1) == "}" else " ") + "$\\" + m.group(1) + "$",
                      chunk)
    out = []
    pos = 0
    for match in _ANY_MATH_RE.finditer(value):
        out.append(fix(value[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(fix(value[pos:]))
    return "".join(out)


_ANY_MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$]*\$|\\\[.*?\\\]", re.S)


def _join_answer_lines(value: str) -> str:
    """Перенос строки OCR «\\\\» посреди ответа вне формул — пробел."""
    out = []
    pos = 0
    for match in _ANY_MATH_RE.finditer(value or ""):
        out.append(re.sub(r"\s*\\\\\s*", " ", value[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(re.sub(r"\s*\\\\\s*", " ", (value or "")[pos:]))
    return "".join(out).strip()


def _normalize_task_units(task: TaskDraft) -> None:
    task.author_answer_latex = _join_answer_lines(task.author_answer_latex)
    for item in task.subitems:
        item.author_answer_latex = _join_answer_lines(item.author_answer_latex)
    for attr in ("text_latex", "author_answer_latex", "author_solution_latex"):
        setattr(task, attr, _finish_value(getattr(task, attr)))
    for item in task.subitems:
        # Подпункт-число («1) -1; 2) $\\frac{1}{2}$») — тоже формула.
        if re.fullmatch(r"-?\d+(?:,\d+)?", item.text_latex.strip()):
            item.text_latex = "$" + item.text_latex.strip() + "$"
        for attr in ("text_latex", "author_answer_latex", "author_solution_latex"):
            setattr(item, attr, _finish_value(getattr(item, attr)))
        item.text_latex = _strip_system_tail_punct(item.text_latex)


def _finish_fields(task: TaskDraft) -> None:
    """Градусы и голые числа ответов, как у Мерзляка, но без его единиц:
    правило «$H$» → «Н» (ньютоны) портит высоту конуса в главе XIV."""
    def text_field(value: str) -> str:
        return normalize_degrees(_heal_ocr_math(value))

    def answer_field(value: str) -> str:
        value = wrap_answer_numbers(_split_quad_list(text_field(value)))
        value = re.sub(r"(?<!\\right)\.\s*\$$", "$", value)
        return re.sub(r"(?<=\S)[ \t]+\$(?=[\s;,.)]|$)", "$", value)

    task.text_latex = text_field(task.text_latex)
    task.author_solution_latex = text_field(task.author_solution_latex)
    task.author_answer_latex = answer_field(task.author_answer_latex)
    for item in task.subitems:
        item.text_latex = text_field(item.text_latex)
        item.author_solution_latex = text_field(item.author_solution_latex)
        item.author_answer_latex = answer_field(item.author_answer_latex)
    answers = [task.author_answer_latex] + [
        item.author_answer_latex for item in task.subitems]
    if any(LEFTOVER_LABEL_RE.search(value or "") for value in answers):
        task.warnings.append(
            "В ответе остались метки других пунктов: OCR перемешал "
            "колонки ответов, сверить с книгой")
        task.confidence = max(0.0, task.confidence - 0.3)


# --------------------------------------------------------------------------
# Разбор целиком
# --------------------------------------------------------------------------

def parse_shabunin(text: str) -> tuple[list[TaskDraft], dict]:
    if not ANSWERS_HEADING_RE.search(text):
        raise ValueError("Не найдены разделы «Ответы к главе …» Шабунина")
    text, source_repairs = apply_source_repairs(text)
    appendix = APPENDIX_RE.search(text)
    if appendix:
        text = text[:appendix.start()]
    structure = load_structure()
    prepared = prepare_shabunin_text(text)
    tasks: list[TaskDraft] = []
    diagnostics: dict = {
        "source_repairs_applied": source_repairs,
        "tasks_by_chapter": {},
        "missing_task_ids": [],
        "range_stems": [],
        "tasks_with_range_stem": 0,
        "answer_figures": 0,
        "answer_figures_unreferenced": [],
        "answer_figures_without_caption": [],
        "chapters_without_structure": [],
        "matched_solutions": 0,
        "tasks_without_solution_ids": [],
    }
    with numeric_subitem_labels():
        for roman, task_text, answer_text in chapter_zones(prepared):
            chapter = structure.get(roman)
            if chapter is None:
                diagnostics["chapters_without_structure"].append(roman)
                continue
            task_text, stems, found = extract_range_stems(task_text, roman)
            diagnostics["range_stems"].extend(found)
            markers = task_markers(task_text, roman)
            titles = {_heading_key(title) for title in chapter.get("subsections", [])}
            chapter_tasks = []
            for marker, raw_body in blocks(task_text, markers):
                number = int(marker.external_id.split(".")[1])
                body = _with_stem(_clean_task_body(raw_body, titles),
                                  stems.get(number, ""))
                task = task_from_block(marker, body, source_path(chapter, number))
                # Подборка — глава целиком, параграфы и уровни — рубрики
                # внутри неё (как у Мерзляка). Тема источника — параграф.
                task.collection_title = task.source_path[0]
                task.topic_code = topic_code(chapter, number, " ".join(
                    [task.text_latex] + [item.text_latex for item in task.subitems]))
                task.topic_original = (task.source_path[1]
                                       if len(task.source_path) > 1
                                       else task.source_path[0])
                if number in stems:
                    diagnostics["tasks_with_range_stem"] += 1
                chapter_tasks.append(task)
            numbers = [int(m.external_id.split(".")[1]) for m in markers]
            present = set(numbers)
            diagnostics["missing_task_ids"].extend(
                f"{roman}.{n}" for n in range(1, max(numbers, default=0) + 1)
                if n not in present)
            diagnostics["tasks_by_chapter"][roman] = len(chapter_tasks)

            answer_text, figures, unnamed = extract_answer_figures(answer_text)
            answer_text, used = attach_answer_figures(answer_text, figures)
            diagnostics["answer_figures"] += len(figures)
            diagnostics["answer_figures_unreferenced"].extend(
                f"{roman}: рис. {n}" for n in sorted(set(figures) - used))
            diagnostics["answer_figures_without_caption"].extend(
                f"{roman}: {path}" for path in unnamed)
            answer_text = prepare_answers(answer_text, roman)
            allowed = {task.external_id for task in chapter_tasks}
            solution = merge_solutions(
                chapter_tasks, answer_text,
                lambda value, allowed=allowed: answer_markers(value, allowed),
                missing_ok=True)
            diagnostics["matched_solutions"] += solution["matched_solutions"]
            diagnostics["tasks_without_solution_ids"].extend(
                sorted(solution["tasks_without_solution_ids"],
                       key=lambda value: int(value.split(".")[1])))
            for task in chapter_tasks:
                _normalize_task_units(task)
                _finish_fields(task)
                finalize_draft_images(task)
                _tag_parameter_task(task)
            tasks.extend(chapter_tasks)
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["unique_tasks"] = len(tasks)
    diagnostics["duplicate_task_ids"] = []
    counts = Counter(" / ".join(task.source_path[:2]) for task in tasks)
    diagnostics["tasks_by_paragraph"] = dict(counts)
    return tasks, diagnostics

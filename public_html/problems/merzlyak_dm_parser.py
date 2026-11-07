"""Профиль дидактических материалов Мерзляка, базовый уровень.

А. Г. Мерзляк, В. Б. Полонский, Е. М. Рабинович, М. С. Якир.
«Математика 5, 6», «Алгебра 7–9», «Геометрия 7–9». Дидактические
материалы (серия «Алгоритм успеха», Вентана-Граф), OCR Mathpix.

Особенности книг (сверено по ДМ-6 с текстовым слоем):

- «Упражнения» — четыре однотипных варианта с одинаковой нумерацией:
  № 170 в вариантах 1–4 — аналоги (одна семья, решение Егора 07.11.2026).
  Внутри варианта — заголовки тем; темы и их первые номера одинаковы во
  всех вариантах и сверены в ``data/merzlyak_dm_structure.json``;
- «Контрольные работы» — два варианта, в каждом «Контрольная работа № n»
  с подзаголовком «Тема. …» и задачами 1…m;
- колонтитулы «Вариант k», «Упражнения», «Контрольные работы» на каждой
  странице — вариант начинается с того «Вариант k», за которым идёт
  задача 1;
- пункты задач нумеруются цифрами «1) 2) 3)» и в книге стоят колонками:
  OCR читает их по строкам («1) …; 3) …⏎2) …; 4) …») — пункты
  раскладываются по номерам;
- рисунки пронумерованы сквозь книгу («Рис. 12»), ссылка в условии —
  «(рис. 12)», «на рисунке 12»; номер рисунка в задаче не остаётся:
  ссылка заменяется рисунком (как у Волчкевича);
- раздела ответов нет: авторских ответов и решений у задач нет.

Локаторы — договор с правилами аналогов (``independentworks.analogs``,
правило ``merzlyak_dm``): упражнения ``ДМ.В{k}/{N}``, контрольные
``КР{n}.В{k}/{m}``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from .merzlyak_parser import (
    MATH_SPAN_RE, _heal_numeric_item_labels, _heal_ocr_words, _join_hyphenation,
    _tabular_to_array, _unwrap_footnotes)
from .potoskuev_parser import _finish_fields, lift_common_tail, monotonic_numbers
from .textbook_parser import (
    Marker, TaskDraft, blocks, finalize_draft_images, numeric_subitem_labels,
    remove_group_commands, task_from_block)
from .volchkevich_parser import canon_fields


PROFILE = "merzlyak_dm"
STRUCTURE_PATH = Path(__file__).with_name("data") / "merzlyak_dm_structure.json"

EXERCISES_TITLE = "Упражнения"
TESTS_TITLE = "Контрольные работы"

_SECTION = r"\\(?:sub)*section\*?\{"
# Строка, в которой только «Вариант 2» (заголовок или колонтитул);
# строка оглавления «Вариант 2 . . . 34» сюда не попадает.
VARIANT_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:" + _SECTION + r")?\s*(?:\\textbf\{)?\s*Вариант\s*(?P<k>[1-4])\s*\}?\s*\}?"
    r"[ \t]*(?:\\\\)?[ \t]*$")
WORK_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:" + _SECTION + r")?\s*Контрольная\s+работа\s*(?:№|N[o°º]?)\s*"
    r"(?P<n>\d{1,2})\s*\}?[ \t]*(?:\\\\)?[ \t]*$")
RUNNING_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:" + _SECTION + r")?\s*(?:Упражнения|Контрольные\s+работы)\s*\}?"
    r"[ \t]*(?:\\\\)?[ \t]*$\n?")
# Номер страницы отдельной строкой.
PAGE_NUMBER_RE = re.compile(r"(?m)^[ \t]*\d{1,3}[ \t]*(?:\\\\)?[ \t]*$\n?")
HEADING_RE = re.compile(r"(?m)^[ \t]*" + _SECTION + r"(?P<title>(?:[^{}]|\{[^{}]*\})*)\}[ \t]*$")
TASK_RE = re.compile(r"(?m)^[ \t]*(?P<number>\d{1,3})[ \t]?\.(?=\s)")
THEME_RE = re.compile(r"^\s*(?:" + _SECTION + r")?\s*Тема\s*\.\s*")
BOOK_RE = re.compile(
    r"(?P<subject>Математика|Алгебра|Геометрия)\s*[.:,]?\s*(?P<grade>\d{1,2})\s*(?:-?\s*й\s+)?класс",
    re.I)


# --------------------------------------------------------------------------
# Книга и подготовка текста
# --------------------------------------------------------------------------

def load_structure(path: Path = STRUCTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def detect_book(text: str, structure: dict | None = None) -> dict | None:
    """Книга по титулу: первое «Математика : 6 класс» до упражнений."""
    structure = structure or load_structure()
    head = text[:max(4000, text.find("Вариант 1") + 1)]
    match = BOOK_RE.search(head)
    if not match:
        return None
    subject = match.group("subject").capitalize()
    grade = int(match.group("grade"))
    for book in structure["books"]:
        if book["subject"] == subject and book["grade"] == grade:
            return book
    return {"key": f"{subject}-{grade}", "subject": subject, "grade": grade,
            "title": f"{subject}. {grade} класс. Дидактические материалы",
            "unknown": True}


_LIST_TOKEN_RE = re.compile(
    r"\\begin\{(?P<begin>enumerate|itemize)\}(?:\[[^\]]*\])?|\\end\{(?:enumerate|itemize)\}"
    r"|\\setcounter\{enum(?P<depth>i+)\}\{(?P<value>\d+)\}"
    r"|\\item(?:\[(?P<label>[^\[\]]*)\])?[ \t]*")
_EXPLICIT_NUMBER_RE = re.compile(r"(?m)^[ \t]*(?P<number>\d{1,3})\s?\.(?=\s)")


def flatten_lists(text: str) -> str:
    """Списки Mathpix → строки «N. …» (задачи) и «k) …» (пункты).

    Внешний ``enumerate`` — номера задач: счётчик OCR (``\\setcounter``)
    и явные номера «12.» в тексте между пунктами дают следующий номер.
    Вложенный список — пункты задачи «1) 2) 3)».
    """
    out = []
    pos = 0
    depth = 0
    counter = 0
    last = 0
    inner: list[int] = []

    def seen(chunk: str) -> None:
        nonlocal last
        for match in _EXPLICIT_NUMBER_RE.finditer(chunk):
            number = int(match.group("number"))
            # «1.» после «229.» — новый вариант или контрольная.
            if last < number <= last + 8 or number < min(last, 3):
                last = number

    for match in _LIST_TOKEN_RE.finditer(text):
        chunk = text[pos:match.start()]
        out.append(chunk)
        if depth <= 1:
            seen(chunk)
        pos = match.end()
        token = match.group(0)
        if match.group("begin"):
            depth += 1
            if depth > 1:
                inner.append(0)
            else:
                counter = 0
            out.append("\n")
        elif token.startswith("\\end"):
            if depth > 1 and inner:
                inner.pop()
            depth = max(0, depth - 1)
            out.append("\n")
        elif match.group("depth"):
            value = int(match.group("value"))
            if len(match.group("depth")) == 1:
                # Счётчик OCR надёжнее номеров предыдущего списка.
                counter = last = value
            elif inner:
                inner[-1] = value
        elif match.group("label") is not None:
            label = match.group("label").strip()
            out.append("\n" + label + " " if label else "\n")
            if depth <= 1:
                seen(label + " ")
        elif depth > 1 and inner:
            inner[-1] += 1
            out.append(f"\n{inner[-1]}) ")
        elif depth:
            number = max(counter, last) + 1
            counter = last = number
            out.append(f"\n{number}. ")
        else:
            out.append("\n")
    out.append(text[pos:])
    return "".join(out)


def prepare_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    begin = text.find("\\begin{document}")
    if begin >= 0:
        text = text[begin + len("\\begin{document}"):]
    text = text.replace("\\end{document}", "")
    text = re.sub(r"\\textbackslash\s+item", r"\\item", text)
    text = _unwrap_footnotes(text)
    text = flatten_lists(text)
    text = re.sub(r"\\\\\[0pt\]", r"\\\\", text)
    text = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{image-not-found\}", "", text)
    text = _heal_numeric_item_labels(text)
    text = _tabular_to_array(text)
    text = _join_hyphenation(text)
    text = _heal_ocr_words(text)
    return re.sub(r"\n{3,}", "\n\n", text)


# --------------------------------------------------------------------------
# Рисунки
# --------------------------------------------------------------------------

_GRAPHICS = r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{(?P<path>[^{}\s\\]+)\}"
GRAPHICS_RE = re.compile(_GRAPHICS)
FIGURE_ENV_RE = re.compile(r"\\begin\{figure\}(?:\[[^\]]*\])?.*?\\end\{figure\}", re.S)
CAPTION_RE = re.compile(r"\\caption\{(?P<text>[^{}]*)\}")
CAPTION_NUMBERS_RE = re.compile(r"Рис\.?\s*(?P<num>\d{1,3})")
# Подпись строкой сразу после картинки: «\includegraphics{…}\\⏎Рис. 5».
TRAILING_CAPTION_RE = re.compile(
    r"^[ \t]*(?:\\\\)?[ \t]*\n?[ \t]*(?P<caption>(?:Рис\.?\s*\d{1,3}[ \t]*)+)(?:\\\\)?[ \t]*(?=\n|$)")
# Подпись, оставшаяся в тексте без картинки рядом: «… хорду Рис. 1».
STRAY_CAPTION_RE = re.compile(r"(?<![(\w])Рис\.\s*(?P<num>\d{1,3})(?![\d.,]|\s*[)\w])")
FIGURE_TOKEN = "\\dmfig{{{}}}"
FIGURE_TOKEN_RE = re.compile(r"\\dmfig\{(?P<num>\d{1,3})\}")
# Ссылки в условии: «(рис. 12)», «(рис. 5, 6)», «на рисунке 10», «рисунок 49».
FIG_REF_RE = re.compile(
    r"(?P<paren>\(\s*)?(?P<word>рис(?:ун[а-яё]*|\.))\s*(?P<nums>\d{1,3}(?:\s*(?:,|и|–|-)\s*\d{1,3})*)"
    r"(?P<close>\s*\))?", re.I)


class Figures:
    def __init__(self):
        self.by_number: dict[str, list[str]] = {}
        self.stray_captions: list[str] = []
        self.merged: list[str] = []

    def add(self, number: str, path: str) -> None:
        paths = self.by_number.setdefault(number, [])
        if path not in paths:
            paths.append(path)


def extract_figures(text: str, figures: Figures) -> str:
    """Подписанные рисунки → ``\\dmfig{N}`` на их месте; без подписи — как есть."""
    def register(numbers: list[str], paths: list[str]) -> str:
        if not numbers or not paths:
            return "\n".join(f"\\includegraphics{{{path}}}" for path in paths)
        if len(paths) == len(numbers):
            pairs = list(zip(numbers, paths))
        else:
            # Mathpix склеил соседние рисунки в одну картинку (или наоборот).
            figures.merged.append(", ".join(numbers))
            pairs = [(number, path) for number in numbers for path in paths]
        for number, path in pairs:
            figures.add(number, path)
        return "\n" + "".join(FIGURE_TOKEN.format(n) for n in dict.fromkeys(numbers)) + "\n"

    def env(match: re.Match) -> str:
        block = match.group(0)
        paths = [m.group("path") for m in GRAPHICS_RE.finditer(block)]
        captions = " ".join(m.group("text") for m in CAPTION_RE.finditer(block))
        numbers = [m.group("num") for m in CAPTION_NUMBERS_RE.finditer(captions)]
        if not numbers:
            tail = TRAILING_CAPTION_RE.match(text, match.end())
            if tail:
                numbers = CAPTION_NUMBERS_RE.findall(tail.group("caption"))
                env.consumed.append((match.end(), tail.end()))
        return register(numbers, paths)
    env.consumed = []

    # Подпись после figure-окружения вырезается отдельно: сначала отметки.
    out = []
    pos = 0
    for match in FIGURE_ENV_RE.finditer(text):
        if match.start() < pos:
            continue
        out.append(text[pos:match.start()])
        out.append(env(match))
        pos = match.end()
        if env.consumed and env.consumed[-1][0] == match.end():
            pos = env.consumed[-1][1]
    out.append(text[pos:])
    text = "".join(out)

    out = []
    pos = 0
    for match in GRAPHICS_RE.finditer(text):
        tail = TRAILING_CAPTION_RE.match(text, match.end())
        if not tail:
            continue
        out.append(text[pos:match.start()])
        numbers = CAPTION_NUMBERS_RE.findall(tail.group("caption"))
        out.append(register(numbers, [match.group("path")]))
        pos = tail.end()
    out.append(text[pos:])
    text = "".join(out)

    # «134. Укажите … хорду Рис. 1»: подпись в тексте, картинка без подписи
    # рядом — ближайшая (сначала ниже, потом выше) в пределах страницы.
    def stray(text: str) -> str:
        result = text
        for match in reversed(list(STRAY_CAPTION_RE.finditer(text))):
            number = match.group("num")
            if number in figures.by_number:
                result = result[:match.start()] + result[match.end():]
                continue
            after = GRAPHICS_RE.search(result, match.end(), match.end() + 800)
            before = None
            for candidate in GRAPHICS_RE.finditer(result, max(0, match.start() - 800), match.start()):
                before = candidate
            pick = after or before
            if pick is None:
                figures.stray_captions.append(number)
                result = result[:match.start()] + result[match.end():]
                continue
            figures.add(number, pick.group("path"))
            token = FIGURE_TOKEN.format(number)
            if pick is after:
                result = (result[:match.start()] + result[match.end():pick.start()]
                          + token + result[pick.end():])
            else:
                result = (result[:pick.start()] + token + result[pick.end():match.start()]
                          + result[match.end():])
        return result

    text = stray(text)
    text = re.sub(r"\\(?:begin|end)\{center\}", "", text)
    return remove_group_commands(text, re.compile(r"\\captionsetup\s*\{"))


def _figure_numbers(nums: str) -> list[str]:
    """«5, 6», «5 и 6», «5–7» → номера рисунков."""
    result: list[str] = []
    for part in re.split(r"\s*(?:,|и)\s*", nums):
        span = re.match(r"(\d+)\s*[–-]\s*(\d+)$", part)
        if span and int(span.group(2)) - int(span.group(1)) < 6:
            result.extend(str(n) for n in range(int(span.group(1)), int(span.group(2)) + 1))
        elif part.strip().isdigit():
            result.append(part.strip())
    return result


def referenced_figures(body: str, figures: Figures) -> list[str]:
    found = []
    for match in FIG_REF_RE.finditer(_without_math(body)):
        for number in _figure_numbers(match.group("nums")):
            if number in figures.by_number and number not in found:
                found.append(number)
    return found


def _without_math(value: str) -> str:
    return MATH_SPAN_RE.sub(lambda m: " " * len(m.group(0)), value)


def replace_figure_refs(body: str, figures: Figures) -> tuple[str, list[str]]:
    """Ссылка на рисунок книги → сам рисунок; вернуть ненайденные номера."""
    missing: list[str] = []

    def fix(match: re.Match) -> str:
        numbers = _figure_numbers(match.group("nums"))
        if not numbers:
            return match.group(0)
        pics = []
        for number in numbers:
            paths = figures.by_number.get(number)
            if not paths:
                missing.append(number)
                return match.group(0)
            pics.extend(rf"\taskpic{{{path}}}" for path in paths)
        joined = " ".join(dict.fromkeys(pics))
        if match.group("paren") and match.group("close"):
            return joined
        word = match.group("word")
        lead = match.group("paren") or ""
        close = match.group("close") or ""
        return f"{lead}{word} {joined}{close}"

    parts, pos = [], 0
    for span in MATH_SPAN_RE.finditer(body):
        parts.append(FIG_REF_RE.sub(fix, body[pos:span.start()]))
        parts.append(span.group(0))
        pos = span.end()
    parts.append(FIG_REF_RE.sub(fix, body[pos:]))
    text = "".join(parts)
    # «(\taskpic{a})» → без скобок; «изображены \taskpic{a}» — как есть.
    return re.sub(r"[ \t]+(?=\\taskpic)", " ", text), missing


# Разряды «4 325», «20 104 050»: книга отделяет тысячи пробелом, OCR даёт
# обычный или неразрывный пробел. Иначе канон обернёт части порознь:
# «$4$ $325$».
_THOUSANDS_RE = re.compile(
    r"(?<![\d.,{}\\])(?P<num>\d{1,3}(?:[ \u00a0\u2009\u202f]\d{3})+)(?![\d]|[.,]\d)")
_MATH_NUMBER_RE = re.compile(
    r"^(?P<open>\\\(|\$)\s*(?P<num>\d{1,3}(?:\s*(?:\\,|\\ |~)?\s*\d{3})+)\s*(?P<close>\\\)|\$)$")


def group_thousands(value: str) -> str:
    """«4 325» → «$4\\,325$» в тексте и в формуле из одного числа."""
    def prose(chunk: str) -> str:
        return _THOUSANDS_RE.sub(
            lambda m: "$" + re.sub(r"\s+", r"\\,", m.group("num")) + "$", chunk)

    def math(span: str) -> str:
        match = _MATH_NUMBER_RE.match(span)
        if not match:
            return span
        digits = re.sub(r"\\,|\\ |~|\s", "", match.group("num"))
        groups = []
        while digits:
            groups.insert(0, digits[-3:])
            digits = digits[:-3]
        return match.group("open") + r"\,".join(groups) + match.group("close")

    out, pos = [], 0
    for span in MATH_SPAN_RE.finditer(value):
        out.append(prose(value[pos:span.start()]))
        out.append(math(span.group(0)))
        pos = span.end()
    out.append(prose(value[pos:]))
    return "".join(out)


# --------------------------------------------------------------------------
# Пункты «1) 2) 3)» колонками
# --------------------------------------------------------------------------

_ITEM_LABEL_RE = re.compile(
    r"(?:(?<=^)|(?<=\n)|(?<=[;:.?!])|(?<=\\\))|(?<=\\\\))[ \t]*(?P<label>\d{1,2})\)(?=[ \t~]|$)",
    re.M)
_ABBREV_RE = re.compile(r"(?:\b(?:рис|см|стр|п|с|№)\.)\s*$", re.I)


def reorder_column_items(body: str) -> tuple[str, bool]:
    """«1) …; 3) …⏎2) …; 4) …» → пункты по порядку номеров.

    Метка пункта — «k)» в начале строки или после знака препинания, вне
    формул и не после «рис.». Берётся последовательность 1, 2, …, m (m ≥ 2)
    по первым вхождениям после пункта 1; остальное — текст пунктов.
    """
    plain = _without_math(body)
    plain = re.sub(r"\\begin\{array\}.*?\\end\{array\}", lambda m: " " * len(m.group(0)), plain, flags=re.S)
    tokens = [m for m in _ITEM_LABEL_RE.finditer(plain)
              if not _ABBREV_RE.search(plain[max(0, m.start() - 6):m.start()])]
    ones = [m for m in tokens if m.group("label") == "1"]
    if not ones:
        return body, False
    start = ones[0]
    chosen = {1: start}
    expected = 2
    while True:
        nxt = next((m for m in tokens if m.start() > start.start()
                    and int(m.group("label")) == expected
                    and m not in chosen.values()), None)
        if nxt is None:
            break
        chosen[expected] = nxt
        expected += 1
    if len(chosen) < 2:
        return body, False
    ordered = sorted(chosen.items(), key=lambda pair: pair[1].start())
    if [label for label, _m in ordered] == sorted(chosen):
        return body, False
    stem = body[:start.start()].rstrip()
    chunks = {}
    for index, (label, match) in enumerate(ordered):
        end = ordered[index + 1][1].start() if index + 1 < len(ordered) else len(body)
        chunk = body[match.end():end].strip()
        chunk = re.sub(r"(?:\s*\\\\)+$", "", chunk).strip()
        chunks[label] = chunk
    last = max(chunks)
    lines = [stem] if stem else []
    for label in sorted(chunks):
        text = chunks[label]
        if label != last:
            text = re.sub(r"[;.,]\s*$", "", text) + ";"
        lines.append(f"{label}) {text}")
    return "\n".join(lines), True


# --------------------------------------------------------------------------
# Разбор зон
# --------------------------------------------------------------------------

def _line_events(text: str) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    variants = [(m.start(), m.end(), int(m.group("k"))) for m in VARIANT_LINE_RE.finditer(text)]
    works = [(m.start(), m.end(), int(m.group("n"))) for m in WORK_LINE_RE.finditer(text)]
    return variants, works


def _task_candidates(text: str, start: int = 0, end: int | None = None) -> list[tuple[int, int, int]]:
    end = len(text) if end is None else end
    return [(m.start(), m.end(), int(m.group("number")))
            for m in TASK_RE.finditer(text, start, end)]


def exercise_variants(text: str, start: int, end: int, variants: list,
                      expected: int) -> list[tuple[int, int, int]]:
    """(вариант, начало, конец) упражнений: «Вариант k», за которым задача 1."""
    candidates = _task_candidates(text, start, end)
    zones = []
    want = 1
    for v_start, v_end, k in variants:
        if not start <= v_start < end or k != want:
            continue
        following = next((n for b, _e, n in candidates if b > v_end), None)
        if following is not None and following <= 2:
            zones.append([k, v_end])
            want += 1
        if want > expected:
            break
    if not zones:
        # Заголовков вариантов OCR не сохранил: варианты — по сбросу
        # нумерации, но только если их несколько (иначе это не ДМ).
        previous = 0
        for begin, _e, number in candidates:
            if number == 1 and (not zones or previous >= 5):
                zones.append([len(zones) + 1, begin])
            previous = number if number > previous or number == 1 else previous
        if len(zones) < 2:
            zones = []
    result = []
    for index, (k, begin) in enumerate(zones):
        stop = zones[index + 1][1] if index + 1 < len(zones) else end
        result.append((k, begin, stop))
    return result


def _clean_running(zone: str) -> str:
    zone = VARIANT_LINE_RE.sub("", zone)
    zone = RUNNING_LINE_RE.sub("", zone)
    return PAGE_NUMBER_RE.sub("", zone)


def _similar(a: str, b: str) -> float:
    def norm(value: str) -> str:
        return re.sub(r"[^а-яё]", "", value.lower().replace("ё", "е"))
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def split_trailing_headings(body: str) -> tuple[str, list[str]]:
    """Заголовки в конце блока — тема следующей задачи; внутри — текст."""
    headings = []
    while True:
        match = None
        for match in HEADING_RE.finditer(body):
            pass
        if match is None or body[match.end():].strip():
            break
        headings.insert(0, match.group("title").strip())
        body = body[:match.start()].rstrip()
    body = HEADING_RE.sub(lambda m: m.group("title").strip(), body)
    return body, headings


def _topic_for(number: int, topics: list[dict]) -> dict | None:
    current = None
    for topic in topics:
        if topic["first"] <= number:
            current = topic
    return current


def build_task(marker: Marker, body: str, path: list[str], figures: Figures,
               used_figures: set[str], diagnostics: dict) -> TaskDraft:
    own = referenced_figures(body, figures)
    # Рисунок, на который ссылается задача, стоит в ней; на прежнем месте
    # (у соседней задачи) его нет. Без ссылки — остаётся по месту.
    positional: list[str] = []

    def place(match: re.Match) -> str:
        number = match.group("num")
        if number not in used_figures:
            # Без ссылки — рисунок той задачи, у которой стоит; в конец
            # условия, а не посреди фразы, куда его поставил OCR.
            diagnostics["figures_positional"].append(f"{marker.external_id}: рис. {number}")
            positional.extend(figures.by_number[number])
        return ""
    body = FIGURE_TOKEN_RE.sub(place, body)
    body, missing = replace_figure_refs(body, figures)
    body = group_thousands(body)
    body, reordered = reorder_column_items(body)
    if reordered:
        diagnostics["column_items"].append(marker.external_id)
    task = task_from_block(marker, body, path)
    if positional:
        task.text_latex = (task.text_latex.rstrip() + "\n"
                           + "\n".join(rf"\taskpic{{{p}}}" for p in positional))
    # «Несбалансированные окружения» — шум от array в пунктах-колонках.
    task.warnings = [w for w in task.warnings if "Несбалансированные" not in w]
    if missing:
        task.warnings.append("Не найден рисунок по подписи: " + ", ".join(missing))
        diagnostics["figures_missing_by_task"][marker.external_id] = missing
    return task


def _finish(task: TaskDraft, grade: int) -> None:
    lift_common_tail(task)
    _finish_fields(task)
    canon_fields(task)
    finalize_draft_images(task)
    task.grade_band_codes = [f"GRADE_{grade}"] if grade else []


def parse_exercises(text: str, zones: list, book: dict, figures: Figures,
                    used: set[str], diagnostics: dict) -> list[TaskDraft]:
    spec = book.get("exercises") or {}
    topics = spec.get("topics") or []
    expected = spec.get("tasks")
    tasks: list[TaskDraft] = []
    by_number_topic: dict[int, str] = {}
    for k, start, end in zones:
        zone = _clean_running(text[start:end])
        candidates = _task_candidates(zone)
        chain = monotonic_numbers(candidates, 0, 6, expected)
        markers = [Marker(b, e, f"ДМ.В{k}/{n}") for b, e, n in chain]
        numbers = [n for _b, _e, n in chain]
        diagnostics["tasks_by_variant"][f"В{k}"] = len(markers)
        top = expected or (max(numbers) if numbers else 0)
        diagnostics["missing_task_ids"].extend(
            f"ДМ.В{k}/{n}" for n in range(1, top + 1) if n not in set(numbers))
        # Заголовок перед первой задачей варианта.
        _preamble, lead = split_trailing_headings(zone[:markers[0].start] if markers else zone)
        heading = " ".join(lead)
        found_titles = []
        for index, (marker, raw) in enumerate(blocks(zone, markers)):
            number = numbers[index]
            topic = _topic_for(number, topics)
            if topic:
                title, code = topic["title"], topic.get("topic", "")
                if number == topic["first"]:
                    found_titles.append((topic["title"], heading))
            else:
                title = heading or by_number_topic.get(number, "") or "Без темы"
                code = ""
            by_number_topic.setdefault(number, title)
            body, next_heading = split_trailing_headings(raw)
            path = [EXERCISES_TITLE, title, f"Вариант {k}"]
            task = build_task(marker, body, path, figures, used, diagnostics)
            task.source_number = str(number)
            task.collection_title = f"Вариант {k}"
            task.topic_original = title
            task.topic_code = code
            _finish(task, book.get("grade", 0))
            tasks.append(task)
            if next_heading:
                heading = " ".join(next_heading)
        for title, seen in found_titles:
            if not seen or _similar(title, seen) < 0.6:
                diagnostics["topic_headings_mismatch"].append(
                    f"В{k}: «{title}» — в тексте «{seen or '—'}»")
    return tasks


def work_zones(text: str, start: int, end: int,
               works: list) -> list[tuple[int, int, int, int]]:
    """(вариант, номер работы, начало, конец): вариант растёт при сбросе номера."""
    found = [(s, e, n) for s, e, n in works if start <= s < end]
    zones = []
    variant = 1
    previous = 0
    for index, (s, e, n) in enumerate(found):
        if n <= previous:
            variant += 1
        previous = n
        stop = found[index + 1][0] if index + 1 < len(found) else end
        zones.append((variant, n, e, stop))
    return zones


def parse_tests(text: str, zones: list, book: dict, figures: Figures,
                used: set[str], diagnostics: dict) -> list[TaskDraft]:
    spec = book.get("tests") or {}
    works = {work["number"]: work for work in spec.get("works") or []}
    tasks: list[TaskDraft] = []
    for k, n, start, end in zones:
        zone = _clean_running(text[start:end])
        candidates = _task_candidates(zone)
        work = works.get(n, {})
        chain = monotonic_numbers(candidates, 0, 3, work.get("tasks"))
        key = f"КР{n}.В{k}"
        # «Тема. …» — до первой задачи, иногда в две строки.
        head = zone[:chain[0][0]] if chain else zone
        theme = THEME_RE.sub("", HEADING_RE.sub(lambda m: m.group("title"), head))
        theme = re.sub(r"\s*\\\\\s*|\s+", " ", theme).strip().rstrip(".")
        title = work.get("title") or theme
        if work.get("title") and theme and _similar(work["title"], theme[:len(work["title"]) + 5]) < 0.6:
            diagnostics["topic_headings_mismatch"].append(f"{key}: «{work['title']}» — в тексте «{theme}»")
        diagnostics["tests_by_work"][key] = len(chain)
        if work.get("tasks") and len(chain) != work["tasks"]:
            diagnostics["tests_task_count_mismatch"].append(
                f"{key}: {len(chain)} из {work['tasks']}")
        work_title = f"Контрольная работа № {n}" + (f". {title}" if title else "")
        markers = [Marker(b, e, f"{key}/{m}") for b, e, m in chain]
        for marker, raw in blocks(zone, markers):
            body, _next = split_trailing_headings(raw)
            path = [TESTS_TITLE, work_title, f"Вариант {k}"]
            task = build_task(marker, body, path, figures, used, diagnostics)
            task.source_number = marker.external_id.rsplit("/", 1)[1]
            task.collection_title = f"Вариант {k}"
            task.topic_original = title
            # Итоговая работа смешанная: темы по номеру задачи.
            task.topic_code = ((work.get("topics") or {}).get(task.source_number)
                               or work.get("topic", ""))
            _finish(task, book.get("grade", 0))
            tasks.append(task)
    expected_variants = spec.get("variants")
    if expected_variants:
        found = sorted({k for k, *_rest in zones})
        if found != list(range(1, expected_variants + 1)):
            diagnostics["tests_variants_mismatch"] = found
    return tasks


def parse_merzlyak_dm(text: str, book: dict | None = None) -> tuple[list[TaskDraft], dict]:
    """Разбор TEX Mathpix; ``book`` — описание книги вместо поиска по титулу."""
    text = prepare_text(text)
    book = book or detect_book(text)
    diagnostics: dict = {
        "book": book["title"] if book else "",
        "book_unknown": bool(not book or book.get("unknown")),
        "tasks_by_variant": {},
        "tests_by_work": {},
        "missing_task_ids": [],
        "topic_headings_mismatch": [],
        "tests_task_count_mismatch": [],
        "column_items": [],
        "figures_positional": [],
        "figures_missing_by_task": {},
    }
    book = book or {"title": "", "grade": 0}
    figures = Figures()
    text = extract_figures(text, figures)
    variants, works = _line_events(text)
    first_work = next((s for s, _e, n in works if n == 1), None)
    exercises_end = first_work if first_work is not None else len(text)
    # Начало контрольных — «Вариант 1» прямо перед «Контрольная работа № 1».
    if first_work is not None:
        before = [s for s, _e, k in variants if k == 1 and 0 <= first_work - s < 300]
        if before:
            exercises_end = before[-1]
    expected_variants = (book.get("exercises") or {}).get("variants", 4)
    zones = exercise_variants(text, 0, exercises_end, variants, expected_variants)
    if not zones:
        raise ValueError(
            "Не найдены «Упражнения» ДМ Мерзляка: нет строки «Вариант 1» "
            "с задачей 1 после неё")
    diagnostics["exercise_variants"] = [k for k, *_rest in zones]
    if len(zones) != expected_variants:
        diagnostics["exercise_variants_mismatch"] = f"{len(zones)} из {expected_variants}"
    # Все ссылки на рисунки — заранее: рисунок уходит к задаче со ссылкой.
    used = set(referenced_figures(text, figures))
    with numeric_subitem_labels():
        tasks = parse_exercises(text, zones, book, figures, used, diagnostics)
        if first_work is not None:
            tasks += parse_tests(
                text, work_zones(text, exercises_end, len(text), works),
                book, figures, used, diagnostics)
    diagnostics["figures_numbered"] = len(figures.by_number)
    diagnostics["figures_merged"] = figures.merged
    diagnostics["figure_captions_without_picture"] = figures.stray_captions
    diagnostics["figures_unreferenced"] = sorted(
        set(figures.by_number) - used, key=int)
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["unique_tasks"] = len({t.external_id for t in tasks})
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_section"] = dict(Counter(t.source_path[0] for t in tasks))
    return tasks, diagnostics

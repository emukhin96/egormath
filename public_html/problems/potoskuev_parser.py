"""Профиль задачника Потоскуева и Звавича по геометрии, 10 класс.

Е. В. Потоскуев, Л. И. Звавич. «Геометрия. 10 класс. Углублённый уровень.
Задачник» (Дрофа), OCR Mathpix.

Особенности книги:

- семь глав, задачи нумеруются «глава.номер» с тремя цифрами: ``1.001``,
  ``7.230``; внутри главы — «Задачи к § N. …» и «Задачи к главе N»,
  путь подборки берётся из сверенной таблицы ``data/potoskuev_structure.json``
  по номеру задачи;
- после номера стоят значки ☺ (задача, необходимая для решения в классе и
  дома) и ⌛ (трудная задача); OCR превращает ☺ в «:-)», «⊙», «-», «()»,
  а ⌛ обычно теряет. В условие значки не попадают;
- сноска «Творческая задача» у номера («6.074 \\({ }^{1}\\).») — метка
  задачи, а не текст;
- три графические работы («Сделайте чертежи по условиям задач …») с
  пунктами ``1.`` … ``16.``: одна задача с подпунктами, ключ ``ГР1`` …;
- рисунки подписаны «Рис. N» со сквозной нумерацией и упоминаются в
  условиях как «(рис. N)», «рис. 56, а», «на рисунках 4–18»; привязка — по
  подписи, а не по положению float-окружения в OCR;
- «ОТВЕТЫ И УКАЗАНИЯ» в конце книги — плотный поток ``1.004. …`` по главам.

Дополнения Д1 (методы построения сечений) и Д2 (планиметрия) в профиль пока
не входят.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Sequence

from .merzlyak_parser import (
    LEFTOVER_LABEL_RE, MATH_SPAN_RE, _flatten_lists, _heal_ocr_math,
    _heal_ocr_words, _renumber_enumerate, _split_markers_in_math,
    normalize_degrees, normalize_units, wrap_answer_numbers)
from .textbook_parser import (
    Marker, SubitemDraft, TaskDraft, apply_imported_math, blocks, clean,
    finalize_draft_images, inline_numeric_markers, merge_solutions,
    normalize_task_images, split_answer_solution, strip_subitem_punct,
    task_from_block)


DATA_DIR = Path(__file__).with_name("data")
STRUCTURE_PATH = DATA_DIR / "potoskuev_structure.json"
REPAIRS_PATH = DATA_DIR / "potoskuev_repairs.json"

CREATIVE_TAG = "Творческая задача"
KEY_TAG = "Основная задача"
HARD_TAG = "Трудная задача"

TASKS_START_RE = re.compile(r"\\section\*?\{\s*Задачи к § 3-4")
APPENDIX_RE = re.compile(r"\\section\*?\{\s*МЕТОДЫ ПОСТРОЕНИЯ СЕЧЕНИЙ")
ANSWERS_RE = re.compile(r"\\section\*?\{\s*ОТВЕТЫ И УКАЗАНИЯ\s*\}")
ANSWERS_APPENDIX_RE = re.compile(r"\\section\*?\{\s*Д2\.")
TOC_RE = re.compile(r"\\section\*?\{\s*ОГЛАВЛЕНИЕ\s*\}")
SECTION_RE = re.compile(r"\\section\*?\{[^{}]*\}")
GRAPHIC_WORK_RE = re.compile(
    r"(?m)^(?:\\section\*?\{)?\s*Графическая работа № (?P<number>\d)[^\n]*$")

# Номер задачи: «1.001.», OCR — «1.001 .», «1 .001.».
TASK_MARKER_RE = re.compile(
    r"(?<![\d.,])(?P<chapter>[1-7])\s?\.\s?(?P<number>\d{3})\s?\.(?=\s|$)")
# Знак сноски «¹»: «6.074 \({ }^{1}\).», «сферы \({ }^{1}(x-4)^{2}…\)».
FOOTNOTE_MARK_RE = re.compile(r"\s*\\\(\{\s*\}\^\{1\}\\\)|\{\s*\}\^\{1\}\s*")
FOOTNOTE_TEXT_RE = re.compile(r"\\footnotetext\{\s*\\\(\{\s*\}\^\{1\}\\\).*?\n\}", re.S)
# Разобранный в книге пример: «Решение.» в начале строки или после условия.
EXAMPLE_SOLUTION_RE = re.compile(
    r"(?:(?<=\n)|(?<=[.?!]\s)|(?<=\\\\\s))[ \t]*Решение(?:[.:]|\s+пунктов)")
# «Ответ:» разобранного примера — до конца строки: дальше может идти
# второй способ решения со своим «Ответ:».
EXAMPLE_ANSWER_RE = re.compile(r"(?m)\bОтвет\s*:\s*(?P<answer>[^\n]+)")
# Значки ☺ и ⌛ после номера в OCR: «:-)», «:)», «⊙», «©», «-», «()».
TASK_SIGN_RE = re.compile(
    r"^(?P<lead>[ \t]*(?:\(Устно\.\)\s*)?)"
    r"(?:\(\s*-?\s*\)|:-?\)?|-\)?|[⊙◯©]\s*\.?|О(?=\s)|\((?=\s))[ \t]+")

FIGURE_RE = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.S)
CAPTION_RE = re.compile(
    r"\\caption\{\s*Рис\.?\s*(?P<num>\d{1,3})(?:\s*[-–—]\s*(?P<last>\d{1,3}))?\s*\}")
GRAPHICS_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{(?P<path>[^{}\s\\]+)\}")
# «(рис. 1)», «рис. 56, а», «на рисунке 3», «на рисунках 4-18», «рис. 42-44».
FIG_REF_RE = re.compile(
    r"(?P<word>[Рр]ис(?:ун(?:ок|ке|ка|ки|ках|кам|ком))?\.?)\s*"
    r"(?P<first>\d{1,3})(?:\s*[-–—]\s*(?P<last>\d{1,3}))?(?!\d|\.\d)")


def load_structure(path: Path = STRUCTURE_PATH) -> dict[int, dict]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    return {chapter["number"]: chapter for chapter in spec["chapters"]}


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
            if "start" in patch:
                # Длинный испорченный фрагмент (раздел ответов Д2) заменяется
                # целиком: от уникального начала до уникального конца.
                for key in ("start", "end"):
                    count = text.count(patch[key])
                    if count != 1:
                        raise ValueError(
                            f"Граница {key} правки {patch['id']} встречается {count} раз")
                start = text.index(patch["start"])
                end = text.index(patch["end"])
                if end <= start:
                    raise ValueError(f"Границы правки {patch['id']} перепутаны")
                text = text[:start] + patch["after"] + text[end:]
            else:
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


def section_for(chapter: dict, number: int) -> dict:
    current = None
    for section in chapter["sections"]:
        if "first" in section and section["first"] <= number:
            current = section
    return current or chapter["sections"][0]


def topic_code(section: dict, text: str) -> str:
    if section.get("topic_sections") and re.search(r"(?i)(?<![а-яё])сечени", text):
        return section["topic_sections"]
    return section.get("topic", "")


# --------------------------------------------------------------------------
# Подготовка текста
# --------------------------------------------------------------------------

def _join_hyphenation(text: str) -> str:
    """«Выбе-\\n\\nрите» — перенос OCR; «пяти- и шестизначные» — нет."""
    text = re.sub(r"(?<=[а-яё])-[ \t]*\n(?:[ \t]*\n)*[ \t]*(?=[а-яё])", "", text)
    return re.sub(r"(?<=[а-яё])-\s+(?=[а-яё])(?!(?:и|или)\s)", "", text)


_LATIN_LABELS = {"a": "а", "B": "в", "e": "е"}


def _heal_label_letters(text: str) -> str:
    """Латинские «a)», «B)», «e)» в метках пунктов → кириллица."""
    return re.sub(
        r"(?m)(^[ \t]*|[;:.]\s*|\\\\\s*|[1-9]\)\s*)([aBe])\)(?=\s)",
        lambda m: m.group(1) + _LATIN_LABELS[m.group(2)] + ")", text)


_CYR_TO_LAT = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M",
    "О": "O", "Р": "P", "Т": "T", "Х": "X"})


def _heal_cyrillic_math(text: str) -> str:
    """«\\(А В\\)» — заглавные кириллические буквы точек внутри формулы."""
    def fix(match: re.Match) -> str:
        inner = match.group(0)
        if re.search(r"[а-яё]|\\text", inner):
            return inner
        return inner.translate(_CYR_TO_LAT)
    return re.sub(r"\\\(.*?\\\)", fix, text, flags=re.S)


def _heal_word_lookalikes(text: str) -> str:
    """«cepeдина» — латинские двойники в начале русского слова вне формул."""
    lookalike = str.maketrans({
        "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у"})

    def fix_chunk(chunk: str) -> str:
        return re.sub(r"(?<![A-Za-z\\{])[acepoxy]+(?=[а-яё])",
                      lambda m: m.group(0).translate(lookalike), chunk)
    out = []
    pos = 0
    for match in MATH_SPAN_RE.finditer(text):
        out.append(fix_chunk(text[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(fix_chunk(text[pos:]))
    return "".join(out)


# Невидимый разделитель: «6⁠)» внутри координат не считается меткой «б)».
_LABEL_GUARD = "\u2060"
_MATH_LABEL_RE = re.compile(r"(?P<label>[a-dа-и6])\)")


def _heal_math_labels(text: str) -> str:
    """Метки пунктов внутри формул OCR.

    «\\(\\vec{b}(1 ;-4 ; 6)\\)» — координата, а не «б)»: общий разбор
    видит «; 6)» и режет пункт. Внутри открытой скобки метка защищается.
    «\\(H(0 ; 0 ; 2) ; 6) P(2 ;-1 ; 2)\\)» — настоящая метка б) на верхнем
    уровне формулы закрывает её. «\\vec{k} ;\\) г \\() \\vec{a}…» — скобка
    метки ушла в следующую формулу.
    """
    text = re.sub(r"(?<=\s)(?P<label>[а-и])\s*\\\(\)\s*", r"\g<label>) \\(", text)

    def fix(match: re.Match) -> str:
        raw = match.group(0)
        if not raw.startswith("\\("):
            return raw
        inner = raw[2:-2]
        out = []
        pos = 0
        for found in _MATH_LABEL_RE.finditer(inner):
            before = inner[:found.start()]
            plain = re.sub(r"\\[a-zA-Z]+|\\.", " ", before)
            depth = plain.count("(") - plain.count(")")
            if depth > 0:
                out.append(inner[pos:found.end() - 1] + _LABEL_GUARD + ")")
                pos = found.end()
                continue
            label = found.group("label")
            if label == "6" and re.search(r";\s*$", before) and depth == 0:
                out.append(re.sub(r"\s*;\s*$", "", inner[pos:found.start()]))
                out.append("\\); б) \\(")
                pos = found.end()
        if not out:
            return raw
        out.append(inner[pos:])
        return re.sub(r"\\\(\s*\\\)", "", "\\(" + "".join(out) + "\\)")

    text = MATH_SPAN_RE.sub(fix, text)
    return _guard_plain_coordinates(text)


def _guard_plain_coordinates(text: str) -> str:
    """«(8; 1; 6).» вне формулы — тоже координата, а не метка «б)»."""
    out = []
    pos = 0
    depth = 0
    for match in re.finditer(r"\\\(.*?\\\)|\\\[.*?\\\]|\$\$.*?\$\$|\$[^$]*\$|\n|[()]|(?<=;)\s*[a-d6]\)", text, re.S):
        token = match.group(0)
        out.append(text[pos:match.start()])
        pos = match.end()
        if token == "\n":
            depth = 0
        elif token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
        elif token.rstrip().endswith(")") and len(token.strip()) == 2 and depth > 0:
            token = token[:-1] + _LABEL_GUARD + ")"
            depth -= 1
        out.append(token)
    out.append(text[pos:])
    return "".join(out)


def prepare_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    # Сноски внизу страницы («Творческая задача», общее условие серии,
    # определение) переносятся в задачи по сверенной таблице структуры.
    text = FOOTNOTE_TEXT_RE.sub("\n", text)
    text = FOOTNOTE_MARK_RE.sub("", text)
    text = _renumber_enumerate(text)
    text = _flatten_lists(text)
    text = re.sub(r"\\\\\[0pt\]", r"\\\\", text)
    # Перенос строки внутри формулы: книга повторяет знак в начале новой
    # строки — «\(x=\) \(=y\)», «\(6 \vec{a}-3 \vec{b}+\) \(+2 \vec{c}\)».
    text = re.sub(
        r"([=+\-<>]|\\cdot|\\times|\\leqslant|\\geqslant)\s*\\\)\s*(?:\\\\\s*)?"
        r"\\\(\s*\1", r"\1 ", text)
    # «\(\overrightarrow{P E} .6\).012.» — номер задачи разорван концом формулы.
    text = re.sub(r"\s*\.\s*([1-7])\\\)\s*\.\s*(\d{3})\s*\.", r"\\) \1.\2.", text)
    # «\(\left.\frac{x}{2}+…=1 ; 2\right) \ldots\)» — метка «2)» стала скобкой.
    text = re.sub(r"\\left\.(?P<body>[^\n]*?)[;,]\s*(?P<label>[1-9])\\right\)",
                  r"\g<body>\); \g<label>) \(", text)
    text = _heal_label_letters(text)
    text = _heal_cyrillic_math(text)
    text = _heal_math_labels(text)
    text = tabular_to_array(text)
    text = re.sub(r"(?<![А-Яа-яЁё])[\u0300-\u036f]", "", text)
    text = _join_hyphenation(text)
    text = _heal_ocr_words(text)
    text = _heal_word_lookalikes(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


_CYRILLIC_RUN_RE = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё.,:;!?«»\- ]*")


def _table_cell(cell: str) -> str:
    """Ячейка таблицы для ``array``: формулы как есть, слова — ``\\text``.

    OCR пишет ячейку то формулой целиком, то вперемешку
    («\\(L N\\) и \\(E G\\)», «TN и EG», «0°»).
    """
    cell = cell.strip()
    if not cell:
        return ""
    multicolumn = re.match(
        r"^\\multicolumn\{(\d+)\}\{[^{}]*\}\{(?P<body>.*)\}$", cell, re.S)
    if multicolumn:
        span = int(multicolumn.group(1))
        return _table_cell(multicolumn.group("body")) + " &" * (span - 1)
    parts = []
    pos = 0
    for match in MATH_SPAN_RE.finditer(cell):
        parts.append(_table_text(cell[pos:match.start()]))
        inner = match.group(0)
        inner = inner[2:-2] if inner.startswith(("\\(", "\\[")) else inner.strip("$")
        parts.append(inner.strip())
        pos = match.end()
    parts.append(_table_text(cell[pos:]))
    return " ".join(part for part in parts if part).replace("°", "^{\\circ}")


def _table_text(chunk: str) -> str:
    chunk = chunk.strip()
    if not chunk:
        return ""
    out = []
    pos = 0
    for match in _CYRILLIC_RUN_RE.finditer(chunk):
        out.append(chunk[pos:match.start()].strip())
        word = match.group(0).strip()
        if word:
            out.append(r"\text{" + word + "}")
        pos = match.end()
    out.append(chunk[pos:].strip())
    return " ".join(part for part in out if part)


def tabular_to_array(text: str) -> str:
    """``tabular`` OCR → выносная ``array``: её понимают и KaTeX, и LaTeX."""
    pattern = re.compile(
        r"(?:\\begin\{center\}\s*)?\\begin\{tabular\}(?:\[[^\]]*\])?\{(?P<spec>[^{}]*)\}"
        r"(?P<body>.*?)\\end\{tabular\}(?:\s*\\end\{center\})?", re.S)

    def convert(match: re.Match) -> str:
        body = match.group("body").replace("\\hline", " \\hline ")
        rows = []
        for row in re.split(r"\\\\", body):
            hline = ""
            while re.match(r"\s*\\hline", row):
                hline += r"\hline "
                row = re.sub(r"^\s*\\hline", "", row, count=1)
            cells = [_table_cell(cell) for cell in row.split("&")]
            if not any(cells) and not hline:
                continue
            rows.append(hline + " & ".join(cells))
        joined = " \\\\\n".join(row for row in rows if row.strip())
        joined = re.sub(r"\\hline\s*$", "", joined).rstrip()
        return ("\n" + r"\[\begin{array}{" + match.group("spec") + "}\n"
                + joined + "\n\\hline\\end{array}\\]" + "\n")

    return pattern.sub(convert, text)


# --------------------------------------------------------------------------
# Рисунки
# --------------------------------------------------------------------------

def extract_figures(text: str) -> tuple[str, dict[int, list[str]]]:
    """Подписанные «Рис. N» рисунки уходят в индекс, остальные остаются."""
    index: dict[int, list[str]] = {}

    def replace(match: re.Match) -> str:
        block = match.group(0)
        paths = [m.group("path") for m in GRAPHICS_RE.finditer(block)]
        captions = list(CAPTION_RE.finditer(block))
        if captions and paths:
            first = int(captions[0].group("num"))
            last = int(captions[0].group("last") or first)
            # «Рис. 4–18» — полосы из нескольких рисунков одной задачи.
            for number in range(first, last + 1):
                index.setdefault(number, []).extend(paths)
            return "\n"
        return "\n" + "\n".join(rf"\includegraphics{{{path}}}" for path in paths) + "\n"

    return FIGURE_RE.sub(replace, text), index


def attach_figure_refs(task: TaskDraft, index: dict[int, list[str]],
                       used: set[int], skip: Sequence[int] = ()) -> list[int]:
    """«(рис. 5)» → «(рис. 5 \\taskpic{файл})»; вернуть ненайденные номера."""
    missing: list[int] = []
    placed: set[str] = set()

    def rewrite(value: str) -> str:
        def replace(match: re.Match) -> str:
            first = int(match.group("first"))
            last = int(match.group("last") or first)
            if last < first or last - first > 30:
                return match.group(0)
            tokens = []
            for number in range(first, last + 1):
                if number in skip:
                    # Опечатка книги в номере рисунка (сверено со сканом).
                    continue
                paths = index.get(number)
                if not paths:
                    missing.append(number)
                    continue
                used.add(number)
                for path in paths:
                    if path not in placed:
                        placed.add(path)
                        tokens.append(rf"\taskpic{{{path}}}")
            if not tokens:
                return match.group(0)
            return match.group(0) + " " + " ".join(tokens)

        return FIG_REF_RE.sub(replace, value or "")

    for attr in ("text_latex", "author_solution_latex", "author_answer_latex"):
        setattr(task, attr, rewrite(getattr(task, attr)))
    for item in task.subitems:
        for attr in ("text_latex", "author_solution_latex", "author_answer_latex"):
            setattr(item, attr, rewrite(getattr(item, attr)))
    return missing


# --------------------------------------------------------------------------
# Задачи
# --------------------------------------------------------------------------

def task_markers(text: str, chapter: int) -> list[Marker]:
    """Номера задач главы, монотонно возрастающие."""
    result = []
    previous = 0
    for match in TASK_MARKER_RE.finditer(text):
        if int(match.group("chapter")) != chapter:
            continue
        number = int(match.group("number"))
        if number <= previous or number > previous + 5:
            continue
        result.append(Marker(match.start(), match.end(), f"{chapter}.{number:03d}"))
        previous = number
    return result


def split_example_solution(body: str) -> tuple[str, str]:
    """Условие и решение разобранного в книге примера («Решение. …»)."""
    match = EXAMPLE_SOLUTION_RE.search(body)
    if not match:
        return body, ""
    return body[:match.start()].rstrip(), body[match.start():].strip()


_PART_LABEL_RE = re.compile(r"(?:(?<=^)|(?<=[\s.:;!?]))(?P<n>[1-9])\)(?=\s|\\\\)")


def _top_level_positions(text: str) -> list[tuple[int, int, int]]:
    """Метки «1)», «2)» … вне формул и скобок: (начало, конец, номер)."""
    spans = [(m.start(), m.end()) for m in MATH_SPAN_RE.finditer(text)]
    found = []
    for match in _PART_LABEL_RE.finditer(text):
        if any(a <= match.start() < b for a, b in spans):
            continue
        prefix = text[:match.start()]
        plain = MATH_SPAN_RE.sub(" ", prefix)
        if plain.count("(") > plain.count(")"):
            continue
        found.append((match.start(), match.end(), int(match.group("n"))))
    return found


def split_numbered_parts(text: str, allowed: Sequence[str] = ()) -> tuple[str, list[tuple[str, str]]]:
    """«Вступление. 1) Постройте: а) …; б) … 2) Найдите: а) …» → части.

    Части идут подряд с «1)»; внутри каждой остаются её буквенные пункты.
    Общий разбор такие задачи не делит: вступление перед «1)» он считает
    признаком шагов решения.
    """
    labels = _top_level_positions(text)
    chain = []
    if allowed:
        # Ответ: части без ответа (доказательство) пропущены — «2) … 3) …».
        wanted = [int(label) for label in allowed]
        for start, end, number in labels:
            if number in wanted and (not chain or number > chain[-1][2]):
                chain.append((start, end, number))
        if not chain:
            return text, []
    else:
        expected = 1
        for start, end, number in labels:
            if number == expected:
                chain.append((start, end, number))
                expected += 1
        if len(chain) < 2:
            return text, []
    stem = text[:chain[0][0]].strip()
    parts = []
    for index, (start, end, number) in enumerate(chain):
        stop = chain[index + 1][0] if index + 1 < len(chain) else len(text)
        parts.append((str(number), text[end:stop].strip()))
    return stem, parts


def _format_part(text: str) -> str:
    """Буквенные пункты части — с новой строки, без служебных «;»."""
    text = re.sub(r"\s*\\\\\s*$", "", text.strip())
    text = re.sub(r"\s*\\\\\s*\n\s*", "\n", text)
    text = re.sub(r"(?:(?<=[:;.?])|(?<=\\\)))\s*(?=[а-и]\)\s)", "\n", text)
    text = re.sub(r";\n", "\n", text)
    return strip_subitem_punct(text)


def set_example_solution(task: TaskDraft, solution: str) -> None:
    """Решение примера — в авторское решение, первый «Ответ:» — в ответ."""
    task.author_solution_latex = clean(solution)
    match = EXAMPLE_ANSWER_RE.search(solution)
    if match:
        answer = re.sub(r"\s*\\\\\s*$", "", match.group("answer")).strip()
        task.author_answer_latex = re.sub(r"\.$", "", answer).strip()


def _heal_late_labels(body: str) -> str:
    """«…; з) …; и) …» — метки после «з)» общий разбор не знает."""
    if not re.search(r"(?:^|[;\s])з\)", body):
        return body
    return re.sub(r";\s*(?=[иклмн]\)\s)", ";\n", body)


def _clean_task_body(body: str) -> str:
    body = TASK_SIGN_RE.sub(r"\g<lead>", body, count=1)
    body = _heal_late_labels(body)
    body = SECTION_RE.sub("", body)
    body = re.sub(r"(?m)^\s*\}\s*$", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def chapter_zones(task_text: str) -> list[tuple[int, str]]:
    """Текст задач по главам: граница — первый номер «N.001.»."""
    starts = []
    for chapter in range(1, 8):
        match = re.search(rf"(?<![\d.]){chapter}\s?\.\s?001\s?\.", task_text)
        if match:
            starts.append((chapter, match.start()))
    zones = []
    for index, (chapter, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(task_text)
        zones.append((chapter, task_text[start:end]))
    return zones


def split_graphic_works(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Вырезает графические работы: (номер, текст после заголовка)."""
    works = []
    out = []
    pos = 0
    for match in GRAPHIC_WORK_RE.finditer(text):
        out.append(text[pos:match.start()])
        end = SECTION_RE.search(text, match.end())
        stop = end.start() if end else len(text)
        works.append((int(match.group("number")), text[match.end():stop]))
        pos = stop
    out.append(text[pos:])
    return "".join(out), works


def graphic_work_task(number: int, body: str, chapter: dict, section: dict) -> TaskDraft:
    body = re.sub(r"(?m)^\s*Тема:?\s*«[^»]*»\s*(?:\\\\)?\s*$", "", body)
    stem_match = re.search(r"Сделайте чертежи[^\n]*", body)
    stem = stem_match.group(0).strip() if stem_match else ""
    stem = re.sub(r"\s*\\\\\s*$", "", stem)
    items = []
    for match in re.finditer(
            r"(?m)^\s*(?P<label>\d{1,2})\.\s+(?P<text>.*?)(?=^\s*\d{1,2}\.\s|\Z)",
            body[stem_match.end() if stem_match else 0:], re.S):
        value = clean(match.group("text"))
        value = re.sub(r"\s*\\\\\s*$", "", value).strip()
        items.append(SubitemDraft(label=match.group("label"), text_latex=value))
    path = [chapter_title(chapter), section["title"]]
    task = TaskDraft(
        external_id=f"ГР{number}",
        source_number=f"Графическая работа № {number}",
        source_path=path,
        collection_key="/".join(path),
        collection_title=path[0],
        topic_original=section["title"],
        text_latex=stem,
        subitems=items,
    )
    task.topic_code = section.get("topic", "")
    return task


# --------------------------------------------------------------------------
# Ответы
# --------------------------------------------------------------------------

def _expand_ids(spec: dict) -> list[str]:
    if "tasks" in spec:
        return list(spec["tasks"])
    chapter, first = spec["first"].split(".")
    last = int(spec["last"].split(".")[1])
    return [f"{chapter}.{n:03d}" for n in range(int(first), last + 1)]


def apply_footnotes(tasks: list[TaskDraft], spec: dict) -> list[str]:
    """Сноски книги: метка «Творческая задача», общее условие серии."""
    by_id = {task.external_id: task for task in tasks}
    applied = []
    for external_id in spec.get("creative", []):
        if external_id in by_id:
            by_id[external_id].tags.append(CREATIVE_TAG)
            applied.append(external_id)
    for note in spec.get("footnotes", []):
        for external_id in _expand_ids(note):
            task = by_id.get(external_id)
            if task is None:
                continue
            if note["position"] == "prepend":
                task.text_latex = note["text"] + " " + task.text_latex
            else:
                task.text_latex = task.text_latex.rstrip() + "\n" + note["text"]
            applied.append(external_id)
    return applied


def raw_answer_blocks(text: str, allowed: set[str]) -> dict[str, str]:
    return {marker.external_id: body
            for marker, body in blocks(text, answer_markers(text, allowed))}


def keep_hint_whole(task: TaskDraft, raw: str) -> None:
    """«Указание. Рассмотрите случаи: а) …; б) …» у задачи без пунктов.

    Пункты внутри указания — часть указания, а не ответы подпунктов.
    """
    if not re.match(r"\s*Указание\.", raw or ""):
        return
    if task.subitems:
        # «Указание. а) …; б) …» — указания к пунктам, а не их ответы.
        for item in task.subitems:
            if item.author_answer_latex and not item.author_solution_latex:
                item.author_solution_latex = item.author_answer_latex
                item.author_answer_latex = ""
        if re.fullmatch(r"\s*Указание\.?\s*", task.author_solution_latex or ""):
            task.author_solution_latex = ""
        return
    task.author_answer_latex = ""
    task.author_solution_latex = clean(raw)


_PART_WARNINGS = (
    "Не совпали подпункты условия и решения",
    "Авторский материал не удалось распределить по подпунктам",
)


def distribute_part_answers(task: TaskDraft, raw: str) -> bool:
    """Ответ «1) а) 6; б) 15; 2) а) 1; б) 29» → ответы частей 1) и 2)."""
    if not task.subitems or not all(item.label.isdigit() for item in task.subitems):
        return False
    labels = [item.label for item in task.subitems]
    lead, parts = split_numbered_parts(clean(raw), labels)
    if not parts:
        return False
    by_label = {item.label: item for item in task.subitems}
    for label, part in parts:
        answer, solution = split_answer_solution(
            re.sub(r"^(?:\s*\\\\)+|\s*\\\\\s*", " ", part).strip())
        item = by_label[label]
        item.author_answer_latex = strip_subitem_punct(
            re.sub(r"(?:(?<=;)|(?<=\\\)))\s*(?=[б-и]\)\s)", " ", answer.strip()))
        item.author_solution_latex = strip_subitem_punct(solution.strip())
    lead_answer, lead_solution = split_answer_solution(lead)
    task.author_answer_latex = lead_answer.strip()
    task.author_solution_latex = lead_solution.strip()
    task.warnings = [w for w in task.warnings if not w.startswith(_PART_WARNINGS)]
    return True


_TAIL_SENTENCE_RE = re.compile(r"(?<=[.?!])\s+(?=(?:[А-ЯЁ]|\(Каждый)[^\n]{8,}$)", re.S)


def lift_common_tail(task: TaskDraft) -> bool:
    """Общая фраза после последнего пункта «…в) AC. Найдите длину каждого…».

    Пункты-фрагменты (со строчной буквы) не содержат законченных
    предложений, поэтому предложение с прописной в конце последнего пункта —
    общее требование ко всей задаче: оно переносится в условие, иначе при
    выборе части пунктов данные задачи пропадут.
    """
    if len(task.subitems) < 2:
        return False
    last = task.subitems[-1]
    def fragment(value: str) -> bool:
        plain = MATH_SPAN_RE.sub("x", value or "").lstrip()
        return plain[:1].islower()
    if not all(fragment(item.text_latex) for item in task.subitems[:-1]):
        return False
    plain = MATH_SPAN_RE.sub(lambda m: "x" * len(m.group(0)), last.text_latex)
    match = _TAIL_SENTENCE_RE.search(plain)
    if not match:
        return False
    tail = last.text_latex[match.end():].strip()
    head = last.text_latex[:match.start()].strip()
    if not head:
        return False
    last.text_latex = strip_subitem_punct(head)
    if not re.search(r"[.?!]\)?$", tail):
        tail += "."
    task.text_latex = task.text_latex.rstrip() + "\n" + tail
    return True


def apply_marks(tasks: list[TaskDraft], spec: dict) -> None:
    marks = spec.get("marks", {})
    smiley = set(marks.get("smiley", []))
    hourglass = set(marks.get("hourglass", []))
    for task in tasks:
        if task.external_id in smiley:
            task.tags.append(KEY_TAG)
        if task.external_id in hourglass:
            task.tags.append(HARD_TAG)


def answer_markers(text: str, allowed: set[str]) -> list[Marker]:
    result = []
    previous = (0, 0)
    for marker in inline_numeric_markers(text, allowed):
        chapter, number = marker.external_id.split(".")
        key = (int(chapter), int(number))
        if key <= previous:
            continue
        result.append(marker)
        previous = key
    return result


def prepare_answers(text: str, allowed: set[str]) -> str:
    text = re.sub(r"\\section\*?\{\s*Глава\s+\d\.[^{}]*\}", "\n", text)
    # «…\(u \overrightarrow{A E} .7 .044 .(8 ; 8 ; 8)\)» — номер следующего
    # ответа внутри формулы закрывает её.
    return _split_markers_in_math(text, allowed)


# --------------------------------------------------------------------------
# Поля
# --------------------------------------------------------------------------

def _finish_fields(task: TaskDraft) -> None:
    def text_field(value: str) -> str:
        value = (value or "").replace(_LABEL_GUARD, "")
        return normalize_degrees(normalize_units(_heal_ocr_math(value)))

    def answer_field(value: str) -> str:
        value = wrap_answer_numbers(text_field(value))
        value = re.sub(r"(?<!\\right)\.\s*\$$", "$", value)
        return re.sub(r"(?<=\S)[ \t]+\$(?=[\s;,.)]|$)", "$", value)

    task.text_latex = text_field(task.text_latex)
    task.author_solution_latex = text_field(task.author_solution_latex)
    task.author_answer_latex = answer_field(task.author_answer_latex)
    for item in task.subitems:
        # «\\(…, \\vec{k} ;\\)» — служебный знак перечисления внутри формулы.
        item.text_latex = re.sub(r"\s*[;,]\s*\\\)\s*$", r"\\)", text_field(item.text_latex))
        item.author_solution_latex = text_field(item.author_solution_latex)
        item.author_answer_latex = answer_field(item.author_answer_latex)
    answers = [task.author_answer_latex] + [
        item.author_answer_latex for item in task.subitems]
    if any(LEFTOVER_LABEL_RE.search(value or "") for value in answers):
        task.warnings.append(
            "В ответе остались метки других пунктов: сверить с книгой")
        task.confidence = max(0.0, task.confidence - 0.3)


# --------------------------------------------------------------------------
# Дополнения: сквозная нумерация 1–256
# --------------------------------------------------------------------------

_LIST_TOKEN_RE = re.compile(
    r"\\begin\{(?P<begin>enumerate|itemize)\}|\\end\{(?:enumerate|itemize)\}"
    r"|\\setcounter\{enum(?P<depth>i+)\}\{(?P<value>\d+)\}"
    r"|\\item(?:\[(?P<label>[^\[\]]*)\])?[ \t]*")


def renumber_appendix_lists(text: str) -> str:
    """Списки Д1/Д2 → строки «N. …»: номера задач живут в счётчиках OCR.

    Mathpix разрывает нумерацию книги на десятки ``enumerate`` с
    ``\\setcounter{enumi}{N}``: следующий ``\\item`` — задача N+1.
    """
    stack: list[list] = []
    out = []
    pos = 0
    for match in _LIST_TOKEN_RE.finditer(text):
        out.append(text[pos:match.start()])
        pos = match.end()
        token = match.group(0)
        enums = [level for level in stack if level[0] == "enumerate"]
        if match.group("begin"):
            stack.append([match.group("begin"), 0])
            out.append("\n")
        elif token.startswith("\\end"):
            if stack:
                stack.pop()
            out.append("\n")
        elif match.group("depth"):
            depth = len(match.group("depth"))
            if len(enums) >= depth:
                enums[depth - 1][1] = int(match.group("value"))
        elif match.group("label") is not None:
            out.append("\n" + match.group("label").strip() + " ")
        elif stack and stack[-1][0] == "enumerate":
            stack[-1][1] += 1
            number = stack[-1][1]
            out.append(f"\n{number}. " if len(enums) == 1 else f"\n{number}) ")
        else:
            out.append("\n")
    out.append(text[pos:])
    return "".join(out)


APPENDIX_TASK_RE = re.compile(
    r"(?m)^[ \t]*(?:ЗАДАЧА\s+)?(?P<number>\d{1,3})\s?\.(?=\s)")


def appendix_markers(text: str, key: str, first: int, last: int) -> list[Marker]:
    result = []
    previous = first - 1
    for match in APPENDIX_TASK_RE.finditer(text):
        number = int(match.group("number"))
        if not previous < number <= min(last, previous + 6):
            continue
        result.append(Marker(match.start(), match.end(), f"{key}.{number}"))
        previous = number
    return result


_APPENDIX_ANSWER_RE = re.compile(r"(?<![\d.,\w])(?P<number>\d{2,3})\s?\.(?=\s|$)")


def appendix_answer_markers(text: str, key: str, allowed: set[int]) -> list[Marker]:
    result = []
    previous = 0
    for match in _APPENDIX_ANSWER_RE.finditer(text):
        number = int(match.group("number"))
        if number not in allowed or number <= previous or number > previous + 12 and previous:
            continue
        result.append(Marker(match.start(), match.end(), f"{key}.{number}"))
        previous = number
    return result


def split_appendix_markers_in_math(text: str, allowed: set[int]) -> str:
    """«\\(\\sqrt{…} .186 .15 \\mathrm{~cm} .187 .7,2\\)» — номера внутри формулы."""
    inner_re = re.compile(r"\s*\.\s?(?P<number>\d{2,3})\s?\.\s?")

    def fix(match: re.Match) -> str:
        raw = match.group(0)
        if not raw.startswith("\\("):
            return raw
        inner = raw[2:-2]
        out = []
        pos = 0
        for found in inner_re.finditer(inner):
            if int(found.group("number")) not in allowed:
                continue
            out.append(inner[pos:found.start()])
            out.append(f"\\). {found.group('number')}. \\(")
            pos = found.end()
        if not out:
            return raw
        out.append(inner[pos:])
        return re.sub(r"\\\(\s*\\\)", "", "\\(" + "".join(out) + "\\)")

    return MATH_SPAN_RE.sub(fix, text)


def appendix_section_path(spec: dict, text: str, position: int) -> tuple[list[str], str]:
    """Путь «Д2 → 2.3 → Треугольник» и тема по заголовкам перед задачей."""
    path = [spec["title"]]
    topic = ""
    section = None
    subsection = None
    for match in re.finditer(r"\\section\*?\{(?P<title>[^{}]*)\}", text[:position]):
        title = clean(match.group("title")).strip()
        for item in spec["sections"]:
            if title.startswith(item["heading"]):
                section = item
                subsection = None
        if section and title in section.get("subsections", {}):
            subsection = title
    if section:
        path.append(section["title"])
        topic = section.get("topic", "")
        if subsection:
            path.append(subsection)
            topic = section["subsections"][subsection]
    return path, topic


def parse_appendix(spec: dict, zone: str, answers: str, figures: dict[int, list[str]],
                   diagnostics: dict) -> list[TaskDraft]:
    zone = prepare_text(renumber_appendix_lists(zone))
    markers = appendix_markers(zone, spec["key"], spec["first"], spec["last"])
    tasks = []
    for marker, raw_body in blocks(zone, markers):
        path, topic = appendix_section_path(spec, zone, marker.start)
        body, example_solution = split_example_solution(_clean_task_body(raw_body))
        body, images = normalize_task_images(body)
        task = task_from_block(marker, body, path)
        task.images = images
        task.source_number = marker.external_id.split(".")[1]
        task.collection_title = path[0]
        task.topic_original = path[-1]
        task.topic_code = topic
        if example_solution:
            set_example_solution(task, example_solution)
            diagnostics["worked_examples"].append(task.external_id)
        if task.images:
            diagnostics["figures_positional"].append(task.external_id)
            task.warnings.append("Рисунок без подписи привязан по положению: проверить")
        tasks.append(task)
    numbers = [int(m.external_id.split(".")[1]) for m in markers]
    present = set(numbers)
    diagnostics["missing_task_ids"].extend(
        f"{spec['key']}.{n}" for n in range(spec["first"], spec["last"] + 1)
        if n not in present)
    diagnostics["tasks_by_chapter"][spec["key"]] = len(tasks)

    if not spec.get("answers"):
        return tasks
    allowed = set(numbers)
    answers = split_appendix_markers_in_math(
        prepare_text(renumber_appendix_lists(answers)), allowed)
    examples = {task.external_id: (task.author_answer_latex, task.author_solution_latex)
                for task in tasks if task.author_solution_latex}
    factory = lambda value: appendix_answer_markers(value, spec["key"], allowed)
    solution = merge_solutions(tasks, answers, factory, missing_ok=True)
    diagnostics["appendix_matched_solutions"] = solution["matched_solutions"]
    raw_blocks = {m.external_id: body for m, body in blocks(answers, factory(answers))}
    for task in tasks:
        keep_hint_whole(task, raw_blocks.get(task.external_id, ""))
        if task.external_id in examples:
            answer, inline = examples[task.external_id]
            extra = task.author_solution_latex
            task.author_solution_latex = inline + ("\n\n" + extra if extra and extra != inline else "")
            task.author_answer_latex = task.author_answer_latex or answer
    return tasks


# --------------------------------------------------------------------------
# Разбор целиком
# --------------------------------------------------------------------------

def parse_potoskuev(text: str) -> tuple[list[TaskDraft], dict]:
    if not ANSWERS_RE.search(text) or not TASKS_START_RE.search(text):
        raise ValueError("Не найдены задачи и «Ответы и указания» Потоскуева")
    text, source_repairs = apply_source_repairs(text)
    structure = load_structure()
    start = TASKS_START_RE.search(text).start()
    appendix = APPENDIX_RE.search(text)
    answers = ANSWERS_RE.search(text)
    toc = TOC_RE.search(text, answers.end())
    task_text = text[start:appendix.start() if appendix else answers.start()]
    answer_text = text[answers.end():toc.start() if toc else len(text)]
    appendix_answers = ANSWERS_APPENDIX_RE.search(answer_text)
    appendix_answer_text = ""
    if appendix_answers:
        appendix_answer_text = answer_text[appendix_answers.end():]
        answer_text = answer_text[:appendix_answers.start()]
    spec_all = json.loads(STRUCTURE_PATH.read_text(encoding="utf-8"))
    appendix_zones = []
    for spec in spec_all.get("appendices", []):
        a = text.find(spec["start"])
        b = text.find(spec["end"], a)
        if a >= 0 and b > a:
            zone, zone_figures = extract_figures(text[a:b])
            appendix_zones.append((spec, zone, zone_figures))

    task_text, figures = extract_figures(task_text)
    task_text = prepare_text(task_text)
    answer_text = prepare_text(answer_text)

    diagnostics: dict = {
        "source_repairs_applied": source_repairs,
        "tasks_by_chapter": {},
        "missing_task_ids": [],
        "figures_numbered": len(figures),
        "figures_missing_by_task": {},
        "figures_unreferenced": [],
        "figures_positional": [],
        "graphic_works": [],
        "worked_examples": [],
        "numbered_parts": [],
        "numbered_part_answers": [],
        "lifted_tails": [],
    }
    tasks: list[TaskDraft] = []
    used: set[int] = set()
    task_text, works = split_graphic_works(task_text)
    works_by_chapter: dict[int, dict[int, tuple[int, TaskDraft]]] = {}
    for work_number, work_body in works:
        for chapter in structure.values():
            section = next((s for s in chapter["sections"]
                            if s.get("work") == work_number), None)
            if section is None:
                continue
            work = graphic_work_task(work_number, work_body, chapter, section)
            works_by_chapter.setdefault(chapter["number"], {})[work_number] = (
                section["after"], work)
            diagnostics["graphic_works"].append(
                f"ГР{work_number}: {len(work.subitems)} пунктов")
    for number, zone in chapter_zones(task_text):
        chapter = structure[number]
        work_tasks = works_by_chapter.get(number, {})
        markers = task_markers(zone, number)
        chapter_tasks = []
        for work_number, (after, work) in sorted(work_tasks.items()):
            if after == 0:
                chapter_tasks.append(work)
        for marker, raw_body in blocks(zone, markers):
            local = int(marker.external_id.split(".")[1])
            section = section_for(chapter, local)
            path = [chapter_title(chapter), section["title"]]
            body, example_solution = split_example_solution(_clean_task_body(raw_body))
            body, part_images = normalize_task_images(body)
            stem, parts = split_numbered_parts(body)
            if parts:
                task = task_from_block(marker, stem, path)
                task.subitems = [
                    SubitemDraft(label, apply_imported_math(_format_part(part)))
                    for label, part in parts]
                diagnostics["numbered_parts"].append(task.external_id)
            else:
                task = task_from_block(marker, body, path)
            task.images = part_images
            if example_solution:
                set_example_solution(task, example_solution)
                diagnostics["worked_examples"].append(task.external_id)
            task.collection_title = path[0]
            task.topic_original = section["title"]
            task.topic_code = topic_code(section, " ".join(
                [task.text_latex] + [item.text_latex for item in task.subitems]))
            if task.images:
                diagnostics["figures_positional"].append(task.external_id)
                task.warnings.append(
                    "Рисунок без подписи привязан по положению: проверить")
            chapter_tasks.append(task)
            for work_number, (after, work) in sorted(work_tasks.items()):
                if after and after == local:
                    chapter_tasks.append(work)
        numbers = [int(m.external_id.split(".")[1]) for m in markers]
        present = set(numbers)
        for work_number, (after, work) in sorted(work_tasks.items()):
            if after and after not in present:
                # Якорь работы потерян OCR: работа остаётся в своей главе.
                work.warnings.append(
                    "Графическая работа поставлена в конец главы: "
                    "проверить место по книге")
                chapter_tasks.append(work)
        diagnostics["missing_task_ids"].extend(
            f"{number}.{n:03d}" for n in range(1, max(numbers, default=0) + 1)
            if n not in present)
        diagnostics["tasks_by_chapter"][number] = len(markers)
        tasks.extend(chapter_tasks)

    diagnostics["footnotes_applied"] = apply_footnotes(tasks, spec_all)
    allowed = {task.external_id for task in tasks if "." in task.external_id}
    answer_text = prepare_answers(answer_text, allowed)
    numbered = [task for task in tasks if task.external_id in allowed]
    examples = {task.external_id: (task.author_answer_latex, task.author_solution_latex)
                for task in numbered if task.author_solution_latex}
    solution = merge_solutions(
        numbered, answer_text,
        lambda value: answer_markers(value, allowed), missing_ok=True)
    diagnostics.update(solution)
    raw_blocks = raw_answer_blocks(answer_text, allowed)
    for task in numbered:
        keep_hint_whole(task, raw_blocks.get(task.external_id, ""))
        if distribute_part_answers(task, raw_blocks.get(task.external_id, "")):
            diagnostics["numbered_part_answers"].append(task.external_id)
        if task.external_id in examples:
            answer, inline = examples[task.external_id]
            extra = task.author_solution_latex
            task.author_solution_latex = inline + ("\n\n" + extra if extra and extra != inline else "")
            task.author_answer_latex = task.author_answer_latex or answer
    for spec, zone, zone_figures in appendix_zones:
        appendix_tasks = parse_appendix(
            spec, zone, appendix_answer_text, zone_figures, diagnostics)
        for task in appendix_tasks:
            missing = attach_figure_refs(
                task, zone_figures, used,
                spec_all.get("figure_ref_skip", {}).get(task.external_id, ()))
            if missing:
                diagnostics["figures_missing_by_task"][task.external_id] = sorted(set(missing))
                task.warnings.append(
                    "Не найден рисунок по подписи: "
                    + ", ".join(str(n) for n in sorted(set(missing))))
        figures_extra = set(zone_figures)
        diagnostics.setdefault("appendix_figures", {})[spec["key"]] = len(figures_extra)
        appendix_task_list = appendix_tasks
        tasks.extend(appendix_task_list)
    for task in tasks:
        if task.external_id.startswith("Д"):
            continue
        missing = attach_figure_refs(task, figures, used)
        if missing:
            diagnostics["figures_missing_by_task"][task.external_id] = sorted(set(missing))
            task.warnings.append(
                "Не найден рисунок по подписи: "
                + ", ".join(str(n) for n in sorted(set(missing))))
    all_figures = set(figures)
    for _spec, _zone, zone_figures in appendix_zones:
        all_figures |= set(zone_figures)
    diagnostics["figures_unreferenced"] = sorted(all_figures - used)
    apply_marks(tasks, spec_all)
    for task in tasks:
        if lift_common_tail(task):
            diagnostics["lifted_tails"].append(task.external_id)
        _finish_fields(task)
        finalize_draft_images(task)
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["unique_tasks"] = len(tasks)
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_section"] = dict(Counter(" / ".join(t.source_path) for t in tasks))
    return tasks, diagnostics

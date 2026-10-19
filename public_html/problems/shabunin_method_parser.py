"""Профиль методического пособия Шабунина и др. для 10 класса.

М. И. Шабунин, А. А. Прокофьев, Т. А. Олейник, Т. В. Соколова.
«Математика. Алгебра. Начала математического анализа. Профильный
уровень. Методическое пособие для 10 класса» (БИНОМ, 2008), OCR Mathpix
по скану (текстового слоя нет; номер страницы PDF — в имени рисунка
Mathpix: ``…-073_327_…`` — с. 73).

Особенности книги:

- десять глав (у VII и VIII OCR потерял строку «Глава N» — граница по
  названию главы), в главе — параграфы «§ N.» с теорией и разобранными
  примерами «Пример N.» (нумерация с 1 в каждом параграфе): условие, «△»
  — начало решения, «□» (``\\square``) — конец. Ключ примера — «I.1.П3»
  (глава, параграф, пример);
- в конце главы — «Дидактические материалы»: самостоятельные (СР),
  контрольные (КР) и домашние контрольные (ДКР) работы по 2–6
  вариантов, варианты со звёздочкой («Вариант 5*») — повышенной
  сложности. Ключ задачи — «КРII.1.В5/3» (работа, вариант, номер);
  у работы без вариантов — «СРIX.2/1»;
- «Ответы» после каждой работы: «Вариант N. 1. … 2. …»; у ДКР ещё
  «Разбор варианта № 1» — авторское решение задач первого варианта;
- задачи под одним номером во всех вариантах работы — аналоги
  (``independentworks.analogs.WORK_ALL_VARIANTS``): семьи создаются при
  загрузке в каталог.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .merzlyak_parser import (
    LEFTOVER_LABEL_RE, MATH_SPAN_RE, _heal_ocr_math, _heal_ocr_words,
    normalize_degrees, normalize_units, wrap_answer_numbers)
from .potoskuev_parser import (
    monotonic_numbers, renumber_appendix_lists, tabular_to_array)
from .textbook_parser import (
    Marker, TaskDraft, blocks, clean, cyrillic_item_label,
    finalize_draft_images, split_subitems, strip_imported_answer_punct,
    task_from_block)
from .vysotsky_parser import lift_stem_pictures, math_text_braces


DATA_DIR = Path(__file__).with_name("data")
STRUCTURE_PATH = DATA_DIR / "shabunin_method_structure.json"
REPAIRS_PATH = DATA_DIR / "shabunin_method_repairs.json"

PROFILE_MARK = "ДИДАКТИЧЕСКИЕ МАТЕРИАЛЫ"
SECTION_RE = re.compile(r"\\section\*?\{(?P<title>(?:[^{}]|\{[^{}]*\})*)\}")
PARAGRAPH_RE = re.compile(r"\\section\*?\{\s*§\s*(?P<number>\d)\s*\.\s*(?P<title>[^{}]*)\}")
DIDACTIC_RE = re.compile(r"\\section\*?\{\s*ДИДАКТИЧЕСКИЕ МАТЕРИАЛЫ")
EXAMPLE_RE = re.compile(
    r"(?:(?<=\n)|(?<=\\section\*\{)|(?<=[.!?:]\s)|(?<=\\square\\\)\s)|(?<=\\square\\\)))"
    r"[ \t]*(?:\\item\[\][ \t]*)?Пример[ \t]+(?P<number>\d{1,2})[ \t]*\.")
SOLUTION_START_RE = re.compile(r"△|\\\(\s*\\(?:triangle|Delta)\s*\\\)|\\(?:triangle|Delta)\b\s*")
# Конец решения — «□», в главах V и IX — «▲»: OCR читает его буквой «A»/«А»
# в конце строки после точки.
SOLUTION_END_RE = re.compile(
    r"\\\(\s*\\square\s*\\\)|\\square\b|□|▲"
    r"|(?<=[.)\]])[ \t]*[AА](?=[ \t]*(?:\\\\)?[ \t]*(?:\n|$))")

ROMAN = r"[IVXІХ]{1,4}"
WORK_RE = re.compile(
    r"(?P<kind>Домашняя\s+контрольная|Контрольная|Самостоятельная)\s+работа\s+"
    r"(?P<roman>" + ROMAN + r")\s*\.\s*(?P<number>\d)")
# «Вариант 1», «\section*{Вариант 5*}»; OCR — «Bapuatum 3», «Bapuaнт 6*».
VARIANT_RE = re.compile(
    r"(?m)(?:\\section\*\{\s*|^[ \t]*|(?<=\\\\)\s*|(?<=[.)]\s))"
    r"(?:Вариант|Bap[uи]a\w*|Вapиант|Bариант)\s*(?P<number>\d)\s*(?P<star>\*?)"
    r"\s*(?:\}|\.|\\\\|$|(?=\s))")
ANSWERS_RE = re.compile(
    r"(?m)(?:\\section\*\{\s*Ответы\s*\}|^[ \t]*Ответы\s*\.?\s*(?:\\\\(?:\[0pt\])?)?[ \t]*$)")
REVIEW_RE = re.compile(r"\\section\*\{\s*Разбор\s+варианта\s*№?\s*1\s*\}")

KIND_CODES = {"Самостоятельная": "СР", "Контрольная": "КР", "Домашняя контрольная": "ДКР"}
KIND_TITLES = {"СР": "Самостоятельная работа", "КР": "Контрольная работа",
               "ДКР": "Домашняя контрольная работа"}
_ROMAN_FIX = str.maketrans({"Х": "X", "І": "I"})


def load_structure(path: Path = STRUCTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_repairs(text: str, path: Path = REPAIRS_PATH) -> tuple[str, dict, list[str]]:
    """Сверенные с книгой правки, привязанные к sha256 исходного TEX.

    ``patches`` — точечные замены текста OCR (фрагмент встречается ровно
    один раз); ``tasks`` — переписанные по скану поля задачи
    (``text``, ``answer``, ``solution``, ``stars``) по её ключу.
    """
    if not path.exists():
        return text, {}, []
    spec = json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    applied: list[str] = []
    overrides: dict = {}
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
        for key, fields in edition.get("tasks", {}).items():
            overrides[key] = fields
            applied.append("task:" + key)
        # Предупреждения разбора у этих задач сверены со сканом.
        for key in edition.get("reviewed", []):
            overrides.setdefault(key, {})["clear_warnings"] = True
    return text, overrides, applied


def _find_chapters(text: str, structure: dict) -> list[tuple[dict, int, int]]:
    end = text.find(structure["end"])
    if end < 0:
        raise ValueError("Не найдено «Примерное поурочное планирование» пособия Шабунина")
    starts = []
    pos = 0
    for chapter in structure["chapters"]:
        index = text.find(chapter["start"], pos)
        if index < 0:
            raise ValueError(f"Не найдена глава {chapter['roman']} пособия Шабунина")
        starts.append((chapter, index))
        pos = index + 1
    zones = []
    for i, (chapter, start) in enumerate(starts):
        stop = starts[i + 1][1] if i + 1 < len(starts) else end
        zones.append((chapter, start, stop))
    return zones


def chapter_title(chapter: dict) -> str:
    return f"Глава {chapter['roman']}. {chapter['title']}"


def _title_case(value: str) -> str:
    """«ВЫСКАЗЫВАНИЯ И ОПЕРАЦИИ НАД НИМИ» → «Высказывания и операции над ними»."""
    value = re.sub(r"\s+", " ", value.replace("\\\\", " ")).strip().rstrip(".")
    if value.isupper():
        value = value[:1] + value[1:].lower()
    value = value.replace("CXEMA", "Схема").replace("Cxema", "Схема")
    return value


def topic_code(code, text: str) -> str:
    if isinstance(code, dict):
        kind = "inequality" if re.search(r"(?i)неравенств", text) else "equation"
        return code[kind]
    return code or ""


# --------------------------------------------------------------------------
# Общие преобразования
# --------------------------------------------------------------------------

def prepare_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    # «Otbet.», «Oтвет» — латинские двойники в слове «Ответ».
    text = re.sub(r"\b[OО][тt][вb][еe][тt]\b", "Ответ", text)
    text = re.sub(r"\\\\\[0pt\]", r"\\\\", text)
    text = re.sub(r"\\hspace\{0pt\}\s*", "", text)
    text = _heal_ocr_words(text)
    text = tabular_to_array(text)
    text = re.sub(r"\\(?:begin|end)\{(?:table|center)\}(?:\[[^\]]*\])?", "", text)
    text = re.sub(r"\\captionsetup\{[^{}]*\}", "", text)
    text = re.sub(r"\\caption\{\s*Таблица\s*\d+\s*\}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


_FIGURE_RE = re.compile(
    r"\\begin\{figure\}(?:\[[^\]]*\])?(?P<body>.*?)\\end\{figure\}", re.S)
_GRAPHIC_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^{}]+\}")


def flatten_figures(text: str) -> str:
    """``figure`` → рисунок и подпись «Рис. N» строкой под ним."""
    def repl(match: re.Match) -> str:
        body = match.group("body")
        pictures = _GRAPHIC_RE.findall(body)
        caption = re.search(r"\\caption\{([^{}]*)\}", body)
        lines = list(pictures)
        if caption and caption.group(1).strip():
            lines.append(caption.group(1).strip())
        return "\n" + "\\\\\n".join(lines) + "\n"
    return _FIGURE_RE.sub(repl, text)


def _clean_body(body: str) -> str:
    body = re.sub(r"\\footnotetext\{.*?\n\}", "\n", body, flags=re.S)
    body = SECTION_RE.sub(lambda m: "\n" + m.group("title") + "\n", body)
    body = re.sub(r"(?m)^\s*\}\s*$", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


# --------------------------------------------------------------------------
# Разобранные примеры
# --------------------------------------------------------------------------

def paragraph_zones(text: str) -> list[tuple[int, str, int, int]]:
    found = [(int(m.group("number")), _title_case(m.group("title")), m.start(), m.end())
             for m in PARAGRAPH_RE.finditer(text)]
    zones = []
    for i, (number, title, start, end) in enumerate(found):
        stop = found[i + 1][2] if i + 1 < len(found) else len(text)
        zones.append((number, title, end, stop))
    return zones


def example_markers(text: str, key: str) -> list[Marker]:
    candidates = [(m.start(), m.end(), int(m.group("number")))
                  for m in EXAMPLE_RE.finditer(text)]
    chain = monotonic_numbers(candidates, 0, 1)
    return [Marker(b, e, f"{key}.П{n}") for b, e, n in chain]


_ANSWER_LINE_RE = re.compile(r"(?:^|(?<=\n)|(?<=\\\\)|(?<=[.)]\s))\s*Ответ\s*[.:]\s*")


def split_example(body: str) -> tuple[str, str, str, list[str]]:
    """(условие, решение, ответ, предупреждения) примера.

    Решение — от «△» до последнего «□» перед следующим примером; текст
    после «□» — теория параграфа.
    """
    warnings = []
    start = SOLUTION_START_RE.search(body)
    if not start:
        warnings.append("Не найден знак начала решения △")
        return body.strip(), "", "", warnings
    ends = list(SOLUTION_END_RE.finditer(body, start.end()))
    if not ends:
        warnings.append("Не найден знак конца решения □")
        solution = body[start.end():]
    else:
        # Несколько «□»: пример из пунктов а) … □ б) … □. Конец — последний
        # знак, после которого до следующего примера нет нового «△».
        solution = body[start.end():ends[-1].start()]
    text = body[:start.start()]
    solution = solution.strip()
    # Промежуточные «□ … △» внутри решения многопунктного примера.
    solution = SOLUTION_END_RE.sub("", solution)
    solution = SOLUTION_START_RE.sub("", solution)
    answer = ""
    matches = list(_ANSWER_LINE_RE.finditer(solution))
    if matches:
        answer = solution[matches[-1].end():].strip()
        answer = re.sub(r"\\\\\s*$", "", answer).strip()
    return text.strip(), solution, answer, warnings


_FIGURE_SLOT = "\u27e6Рис.{}\u27e7"
_FIGURE_SLOT_RE = re.compile("\u27e6Рис\\.(\\d+)\u27e7")
_GLUED_SLOT_RE = re.compile(
    "(?P<pre>[А-Яа-яЁё,])(?P<hy>-?)[ \\t]*(?:\\\\\\\\)?\\s*"
    "(?P<slot>\u27e6Рис\\.\\d+\u27e7(?:\\s*\u27e6Рис\\.\\d+\u27e7)*)\\s*(?P<post>[а-яё\\\\])")


def parse_examples(zone: str, chapter: dict, diagnostics: dict) -> list[TaskDraft]:
    """Примеры параграфов главы. Рисунки «Рис. N» OCR ставит где придётся
    (часто у соседнего примера): рисунок встаёт после строки условия или
    разбора с первой ссылкой «рис. N»; без ссылок — на своё место."""
    tasks = []
    figures: dict[int, list[str]] = {}

    def take(match: re.Match) -> str:
        number = int(match.group("number"))
        figures.setdefault(number, []).extend(_GRAPHIC_RE.findall(match.group("body")))
        return _FIGURE_SLOT.format(number)
    zone = flatten_figures(_CAPTIONED_FIGURE_RE.sub(take, zone))
    for number, title, start, stop in paragraph_zones(zone):
        key = f"{chapter['roman']}.{number}"
        # Пример в заголовке: «\section*{Пример 5. Решить …}».
        body_text = re.sub(r"(?m)^\\section\*\{(Пример[ \t]+\d[^\n]*)\}[ \t]*$", r"\1",
                           zone[start:stop])
        markers = example_markers(body_text, key)
        diagnostics["examples_by_paragraph"][key] = len(markers)
        path = [chapter_title(chapter), f"§{number}. {title}"]
        code = chapter["paragraphs"].get(str(number), chapter["topic"])
        for marker, raw in blocks(body_text, markers):
            start_mark = SOLUTION_START_RE.search(raw)
            if start_mark and not SOLUTION_END_RE.search(raw, start_mark.end()):
                # Знак «□» потерян: разбор — до ближайшего заголовка теории.
                for heading in SECTION_RE.finditer(raw, start_mark.end()):
                    if not heading.group("title").lstrip().startswith("Пример"):
                        raw = raw[:heading.start()]
                        break
            raw = prepare_text(renumber_appendix_lists(raw))
            text, solution, answer, warnings = split_example(_clean_body(raw))
            task = task_from_block(marker, text, path)
            task.source_number = marker.external_id
            task.collection_title = path[-1]
            task.topic_original = title
            task.topic_code = topic_code(code, text)
            task.author_solution_latex = clean(solution)
            task.author_answer_latex = clean(answer)
            task.warnings += warnings
            if warnings:
                task.confidence = max(0.0, task.confidence - 0.3)
            task.tags.append("пример с решением")
            tasks.append(task)
    used: set[int] = set()
    for task in tasks:
        task.text_latex = insert_solution_figures(task.text_latex, figures, used)
        for item in task.subitems:
            item.text_latex = insert_solution_figures(item.text_latex, figures, used)
    for task in tasks:
        task.author_solution_latex = insert_solution_figures(
            task.author_solution_latex, figures, used)

    theory_refs = {int(n) for n in re.findall(r"рис\.\s*(\d+)", zone)}

    def slot(match: re.Match) -> str:
        number = int(match.group(1))
        if number in used or number not in figures:
            return ""
        if number in theory_refs:
            # Ссылка есть только в теории параграфа — рисунок не к примеру.
            used.add(number)
            diagnostics["theory_figures"].append(f"{chapter['roman']}: рис. {number}")
            return ""
        used.add(number)
        diagnostics["figures_without_reference"].append(f"{chapter['roman']}: рис. {number}")
        return "\n" + "\\\\\n".join(figures[number] + [f"Рис. {number}"]) + "\n"
    def glue(value: str) -> str:
        """Рисунок стоял посреди фразы («пара-⏎рисунок⏎метра»): фраза
        склеивается, рисунок (если остаётся здесь) — после её строки."""
        def fix(match: re.Match) -> str:
            joiner = "" if match.group("hy") else " "
            return match.group("pre") + joiner + match.group("slot") + match.group("post")
        return _GLUED_SLOT_RE.sub(fix, value)

    def place(value: str) -> str:
        # Слот посреди строки — в конец строки, затем подстановка.
        value = glue(value)
        lines = []
        for line in value.split("\n"):
            slots = _FIGURE_SLOT_RE.findall(line)
            if slots and _FIGURE_SLOT_RE.sub("", line).strip():
                line = _FIGURE_SLOT_RE.sub("", line).rstrip() + "\n" + "".join(
                    _FIGURE_SLOT.format(n) for n in slots)
            lines.append(line)
        return _FIGURE_SLOT_RE.sub(slot, "\n".join(lines))
    for task in tasks:
        task.text_latex = place(task.text_latex)
        task.author_solution_latex = place(task.author_solution_latex)
        for item in task.subitems:
            item.text_latex = place(item.text_latex)
        task.text_latex = re.sub(r"\n{3,}", "\n\n", task.text_latex).strip()
        task.author_solution_latex = re.sub(r"\n{3,}", "\n\n", task.author_solution_latex).strip()
    for task in tasks:
        task.text_latex = _FIGURE_SLOT_RE.sub(slot, task.text_latex)
        task.author_solution_latex = _FIGURE_SLOT_RE.sub(slot, task.author_solution_latex)
        for item in task.subitems:
            item.text_latex = _FIGURE_SLOT_RE.sub(slot, item.text_latex)
    return tasks


# --------------------------------------------------------------------------
# Дидактические материалы
# --------------------------------------------------------------------------

def work_zones(zone: str) -> list[dict]:
    found = []
    for match in WORK_RE.finditer(zone):
        roman = match.group("roman").translate(_ROMAN_FIX)
        kind = KIND_CODES[re.sub(r"\s+", " ", match.group("kind"))]
        key = f"{kind}{roman}.{match.group('number')}"
        if found and found[-1]["key"] == key:
            continue
        # Тема контрольной: «… по теме «Множества. …» (2 урока)}».
        head = zone[match.end():match.end() + 300]
        theme = re.search(r"по\s+теме\s+«(?P<theme>[^»]+)»", head)
        found.append({"key": key, "kind": kind, "roman": roman,
                      "number": match.group("number"), "start": match.start(),
                      "body": match.end(), "theme": theme.group("theme") if theme else ""})
    for i, work in enumerate(found):
        work["stop"] = found[i + 1]["start"] if i + 1 < len(found) else len(zone)
        # Заголовок следующей работы стоит в «\section*{…»: отрезаем начало.
        tail = zone[work["body"]:work["stop"]]
        cut = tail.rfind("\\section*{")
        if cut >= 0 and not tail[cut + len("\\section*{"):].strip():
            work["stop"] = work["body"] + cut
    return found


def variant_zones(text: str) -> list[tuple[int, bool, int, int]]:
    found = [(int(m.group("number")), bool(m.group("star")), m.start(), m.end())
             for m in VARIANT_RE.finditer(text)]
    zones = []
    for i, (number, star, start, end) in enumerate(found):
        stop = found[i + 1][2] if i + 1 < len(found) else len(text)
        zones.append((number, star, end, stop))
    return zones


_ITEM_RE = re.compile(r"(?m)^[ \t]*(?P<number>[1-9]|1[0-9])[ \t]?\.(?=\s)")


def item_markers(text: str, key: str, limit: int | None = None) -> list[Marker]:
    candidates = [(m.start(), m.end(), int(m.group("number")))
                  for m in _ITEM_RE.finditer(text)]
    chain = monotonic_numbers(candidates, 0, 1, limit)
    return [Marker(b, e, f"{key}/{n}") for b, e, n in chain]


def _variant_key(work: dict, number: int | None) -> str:
    return work["key"] + (f".В{number}" if number else "")


def _work_title(work: dict) -> str:
    title = f"{KIND_TITLES[work['kind']]} {work['roman']}.{work['number']}"
    return title


_INSTRUCTION_LINE_RE = re.compile(r"(?m)^(?P<line>[А-ЯЁ][^\n$\\]{5,120}:)[ \t]*(?:\\\\)?[ \t]*$")


def split_trailing_instruction(raw: str) -> tuple[str, str]:
    """Формулировка следующей серии, которую OCR приклеил к концу пункта
    (после неё — только рисунки этого пункта)."""
    for match in reversed(list(_INSTRUCTION_LINE_RE.finditer(raw))):
        if match.start() == 0:
            break
        rest = _GRAPHIC_RE.sub("", raw[match.end():])
        if re.sub(r"\\\\|\s", "", rest):
            break
        head = re.sub(r"(?:\\\\|\s)+$", "", raw[:match.start()])
        return head + "\n" + raw[match.end():].strip(), match.group("line").strip()
    return raw, ""


def is_bare_item(raw: str) -> bool:
    """Задача — только формулы (и метки пунктов), без своей формулировки."""
    prose = MATH_SPAN_RE.sub(" ", raw)
    prose = re.sub(r"\\\[.*?\\\]", " ", prose, flags=re.S)
    prose = re.sub(r"\\[a-zA-Z]+|(?<![А-Яа-яЁё])[а-еa-e]\)", " ", prose)
    return len(re.findall(r"[А-Яа-яЁё]{3,}", prose)) == 0


_CAPTIONED_FIGURE_RE = re.compile(
    r"\\begin\{figure\}(?:\[[^\]]*\])?(?P<body>(?:(?!\\end\{figure\}).)*?"
    r"\\caption\{\s*Рис\.\s*(?P<number>\d+)\s*\}.*?)\\end\{figure\}", re.S)
_FIGURE_REF_RE = re.compile(
    r"(?P<open>\(\s*)?(?:[Сс]м\.\s*)?рис\.\s*(?P<numbers>\d+(?:\s*(?:,|и)\s*\d+)*)"
    r"(?(open)\s*\))")


def extract_answer_figures(materials: str) -> tuple[str, dict[int, list[str]]]:
    """Рисунки ответов «Рис. N» (нумерация сквозная по главе) вынимаются
    из текста работ: OCR ставит их посреди условий соседних задач."""
    figures: dict[int, list[str]] = {}

    def take(match: re.Match) -> str:
        figures.setdefault(int(match.group("number")), []).extend(
            _GRAPHIC_RE.findall(match.group("body")))
        return "\n"
    return _CAPTIONED_FIGURE_RE.sub(take, materials), figures


def insert_answer_figures(value: str, figures: dict[int, list[str]], used: set[int]) -> str:
    """«См. рис. 1, 2», «(рис. 42)» → сами рисунки."""
    def repl(match: re.Match) -> str:
        numbers = [int(n) for n in re.findall(r"\d+", match.group("numbers"))]
        if not all(n in figures for n in numbers):
            return match.group(0)
        used.update(numbers)
        pictures = [p for n in numbers for p in figures[n]]
        return "\n" + "\\\\\n".join(pictures) + "\n"
    value = _FIGURE_REF_RE.sub(repl, value or "")
    value = re.sub(r"(" + _GRAPHIC_RE.pattern + r")\n\s*[.,;]\s*", r"\1\n", value)
    # «… (рис. 42).» → «…⏎рисунок»: точка и пробелы вокруг рисунка лишние.
    value = re.sub(r"(" + _GRAPHIC_RE.pattern + r")\n\s*[.,;]?\s*$", r"\1", value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    return value.strip()


def insert_solution_figures(value: str, figures: dict[int, list[str]], used: set[int]) -> str:
    """В разборе ссылка «(рис. 19)» остаётся текстом, рисунок с подписью
    встаёт после абзаца с первой ссылкой."""
    if not value:
        return value
    lines = value.split("\n")
    for index, line in enumerate(lines):
        extra = []
        for match in re.finditer(r"рис\.\s*(\d+)(?:\s*[-–]\s*(\d+))?", line):
            first = int(match.group(1))
            last = int(match.group(2) or first)
            for n in range(first, last + 1):
                if n in figures and n not in used:
                    used.add(n)
                    extra += figures[n] + [f"Рис. {n}"]
        if extra:
            lines[index] = line.rstrip() + ("" if line.rstrip().endswith("\\\\") else "\\\\") + "\n" + "\\\\\n".join(extra)
    return "\n".join(lines)


_LIST_TOKEN_RE = re.compile(
    r"\\begin\{(?P<begin>enumerate|itemize)\}|\\end\{(?:enumerate|itemize)\}"
    r"|\\setcounter\{enum(?P<depth>i+)\}\{(?P<value>\d+)\}"
    r"|\\item(?:\[(?P<label>[^\[\]]*)\])?[ \t]*")
# Явный номер в строке условия: только в начале строки («\\⏎2. …»),
# иначе «кратных 7.» сдвинул бы счётчик.
_LINE_NUMBER_RE = re.compile(r"(?:^|\n|\\\\)\s*(?P<number>\d{1,2})\s?\.(?=\s)")


def renumber_items(text: str, *, answers: bool = False) -> str:
    """Списки работы → строки «N. …».

    Mathpix ведёт счётчик ``\\item`` сам по себе: номер пункта без метки —
    следующий за наибольшим из счётчика и явных номеров, встреченных после
    предыдущего пункта. В ответах метка «Вариант N.» посреди списка
    сбрасывает счётчик («\\item 17/4.\\\\ Вариант 2. \\item …»). Во
    вложенных списках — свой счётчик «1)», «2)».
    """
    explicit = _ANSWER_NUMBER_RE if answers else _LINE_NUMBER_RE
    out, pos = [], 0
    stack: list[list] = []
    counter = 0

    def seen(chunk: str) -> None:
        nonlocal counter
        resets = list(VARIANT_RE.finditer(chunk)) if answers else []
        if resets:
            counter = 0
            chunk = chunk[resets[-1].end():]
        for match in explicit.finditer(chunk):
            number = int(match.group("number"))
            if counter < number <= counter + 2:
                counter = number

    for match in _LIST_TOKEN_RE.finditer(text):
        chunk = text[pos:match.start()]
        out.append(chunk)
        if len(stack) <= 1:
            seen(chunk)
        pos = match.end()
        if match.group("begin"):
            stack.append([match.group("begin"), 0])
            out.append("\n")
        elif match.group(0).startswith("\\end"):
            if stack:
                stack.pop()
            out.append("\n")
        elif match.group("depth"):
            if len(match.group("depth")) == 1:
                counter = int(match.group("value"))
            elif stack:
                stack[-1][1] = int(match.group("value"))
        elif match.group("label") is not None:
            label = match.group("label").strip()
            out.append("\n" + label + " " if label else "\n")
            if len(stack) <= 1:
                seen(label + " ")
        elif len(stack) >= 2:
            stack[-1][1] += 1
            out.append(f"\n{stack[-1][1]}) ")
        else:
            counter += 1
            out.append(f"\n{counter}. ")
    out.append(text[pos:])
    return "".join(out)


def work_topic(work: dict, number: int, chapter: dict, text: str) -> str:
    """Тема задачи работы — по таблице ``works`` структуры, иначе — главы."""
    code = work.get("topics")
    if isinstance(code, list):
        code = code[number - 1] if number <= len(code) else None
    return topic_code(code or chapter["topic"], text)


def parse_work(zone: str, work: dict, chapter: dict, diagnostics: dict) -> list[TaskDraft]:
    body = flatten_figures(zone[work["body"]:work["stop"]])
    # Остаток заголовка работы: «… (2 урока)}», « \\ по теме …}».
    body = re.sub(r"^[^\n]*\}\s*\n", "\n", body, count=1)
    review = REVIEW_RE.search(body)
    review_text = body[review.end():] if review else ""
    if review:
        body = body[:review.start()]
    answers = ANSWERS_RE.search(body)
    answer_text = body[answers.end():] if answers else ""
    if answers:
        body = body[:answers.start()]
    title = _work_title(work)
    path = [chapter_title(chapter), "Дидактические материалы", title]
    variants = variant_zones(body)
    report = diagnostics["works"].setdefault(work["key"], {})
    report["variants"] = [f"{n}{'*' if s else ''}" for n, s, _a, _b in variants]
    tasks: list[TaskDraft] = []
    if not variants:
        variants = [(0, False, 0, len(body))]
    stems = {}
    for number, star, start, stop in variants:
        key = _variant_key(work, number)
        raw_chunk = re.sub(r"\\item\[(\d{1,2})\]", r"\\item[\1.]", body[start:stop])
        chunk = _clean_body(prepare_text(renumber_items(raw_chunk)))
        markers = item_markers(chunk, key)
        if not markers:
            diagnostics["variants_without_tasks"].append(key)
            continue
        lead = chunk[:markers[0].start].strip()
        lead = re.sub(r"^\s*(?:\\\\|\.)\s*", "", lead).strip()
        # Общее условие варианта до «1.» (СР II.1: «Даны множества …») —
        # всем задачам; формулировка с двоеточием («Построить графики
        # следующих функций:») — только задачам-формулам без своего текста.
        context, instruction = ("", lead) if lead.endswith(":") else (lead, "")
        if lead:
            stems[key] = lead
        label = f"Вариант {number}{'*' if star else ''}"
        for marker, raw in blocks(chunk, markers):
            n = marker.external_id.rsplit("/", 1)[1]
            # «\item[1] 1. …», «\item[1.] ⏎ \item[1.] …» — номер повторён.
            raw = re.sub(r"^\s*(?:" + n + r"\s*\.?\s+)+", " ", raw)
            raw, trailing = split_trailing_instruction(raw)
            text = raw
            if instruction and is_bare_item(raw):
                text = instruction + "\n" + raw
            if context:
                text = context + "\n\n" + text
            if trailing:
                instruction = trailing
            task = task_from_block(marker, text, path + ([label] if number else []))
            task.source_number = marker.external_id
            task.collection_title = label if number else path[-1]
            task.topic_original = work["theme"] or chapter["title"]
            task.topic_code = work_topic(work, int(n), chapter, text)
            if star:
                task.stars = max(task.stars, 1)
            tasks.append(task)
    report["tasks"] = len(tasks)
    report["stems"] = sorted(stems)
    attach_answers(tasks, work, answer_text, report)
    if review_text:
        attach_review(tasks, work, review_text, report)
    return tasks


_ANSWER_NUMBER_RE = re.compile(
    r"(?<![\w,.\\\-−])(?<!,\s)(?<!рис\.\s)(?P<number>[1-9]|1[0-9])\s?\.(?=\s|$|\\\\)")


def answer_blocks(text: str) -> dict[int, str]:
    """«Вариант N. 1. … 2. …» → {N: «1. … 2. …»}; списки — с номерами."""
    text = prepare_text(renumber_items(text, answers=True))
    found = [(int(m.group("number")), m.start(), m.end()) for m in VARIANT_RE.finditer(text)]
    result = {}
    for i, (number, start, end) in enumerate(found):
        stop = found[i + 1][1] if i + 1 < len(found) else len(text)
        result.setdefault(number, text[end:stop])
    if not found and text.strip():
        result[0] = text
    return result


def _split_numbered(chunk: str, numbers: set[int]) -> dict[int, str]:
    candidates = [(m.start(), m.end(), int(m.group("number")))
                  for m in _ANSWER_NUMBER_RE.finditer(chunk)
                  if int(m.group("number")) in numbers]
    chain = monotonic_numbers(candidates, 0, 2, max(numbers) if numbers else None)
    result = {}
    for i, (begin, end, number) in enumerate(chain):
        stop = chain[i + 1][0] if i + 1 < len(chain) else len(chunk)
        value = chunk[end:stop]
        value = SECTION_RE.sub("", value)
        value = re.sub(r"(?:\\\\|\s)+$", "", value).strip()
        value = re.sub(r"^\s*(?:\\\\)\s*", "", value)
        result[number] = value
    return result


def attach_answers(tasks: list[TaskDraft], work: dict, text: str, report: dict) -> None:
    if not text.strip():
        report["answers"] = "нет"
        return
    by_variant: dict[str, dict[int, TaskDraft]] = {}
    for task in tasks:
        key, number = task.external_id.rsplit("/", 1)
        by_variant.setdefault(key, {})[int(number)] = task
    blocks_ = answer_blocks(text)
    report["answer_variants"] = sorted(blocks_)
    missing = []
    for key, group in by_variant.items():
        match = re.search(r"\.В(\d)$", key)
        variant = int(match.group(1)) if match else 0
        chunk = blocks_.get(variant)
        if chunk is None:
            missing.append(key)
            continue
        found = _split_numbered(chunk, set(group))
        for number, task in group.items():
            value = found.get(number, "")
            if not value:
                missing.append(task.external_id)
                continue
            task.author_answer_latex = clean(value)
    report["answers_missing"] = missing


def attach_review(tasks: list[TaskDraft], work: dict, text: str, report: dict) -> None:
    """«Разбор варианта № 1» — решения задач первого варианта."""
    group = {int(t.external_id.rsplit("/", 1)[1]): t for t in tasks
             if t.external_id.startswith(_variant_key(work, 1) + "/")}
    text = prepare_text(renumber_items(flatten_figures(text)))
    text = _clean_body(text)
    markers = item_markers(text, _variant_key(work, 1), max(group) if group else None)
    found = []
    for marker, raw in blocks(text, markers):
        number = int(marker.external_id.rsplit("/", 1)[1])
        task = group.get(number)
        if task is None:
            continue
        task.author_solution_latex = clean(raw)
        found.append(number)
    report["review"] = found


# --------------------------------------------------------------------------
# Поля
# --------------------------------------------------------------------------

_PLAIN_MATH_RE = re.compile(r"^[\d\s\-−+±∓;,.:/()\[\]=<>|^_{}\\a-zA-Zπ∞]+$")
_UNICODE_MATH = {"±": "\\pm ", "∓": "\\mp ", "−": "-", "π": "\\pi ", "∞": "\\infty "}
_ANSWER_LABEL_SPLIT_RE = re.compile(r"((?:^|(?<=[;.]\s)|(?<=\s))[а-е]\)\s*)")


def wrap_plain_answer(value: str) -> str:
    """Ответ без формул «(±1; -3)», «а) [-4;-2]; б) 17/4» — каждую
    математическую часть целиком в формулу: ``wrap_answer_numbers``
    обернул бы только отдельные числа («(±$1$; -3)»)."""
    if not value or MATH_SPAN_RE.search(value) or "\\taskpic" in value:
        return value
    value = re.sub(r"(?:^|(?<=\s))a\)", "а)", value)
    parts = _ANSWER_LABEL_SPLIT_RE.split(value)
    out = []
    for part in parts:
        if not part or _ANSWER_LABEL_SPLIT_RE.fullmatch(part):
            out.append(part)
            continue
        body = part.rstrip()
        tail = ""
        while body and body[-1] in ";.":
            tail = body[-1] + tail
            body = body[:-1].rstrip()
        if re.fullmatch(r"-?\d+(?:,\d+)?", body):
            # Одиночное число — общий вид «$4$» (wrap_answer_numbers).
            out.append(part)
        elif body and re.search(r"\d", body) and _PLAIN_MATH_RE.match(body) \
                and not re.search(r"[a-zA-Z]{4,}", body):
            for char, command in _UNICODE_MATH.items():
                body = body.replace(char, command)
            out.append("\\(" + body.strip() + "\\)" + tail + part[len(part.rstrip()):])
        else:
            out.append(part)
    return "".join(out)


def _finish_fields(task: TaskDraft) -> None:
    def text_field(value: str) -> str:
        value = re.sub(r"(?<!\\)%", r"\\%", value or "")
        value = math_text_braces(value)
        return normalize_degrees(normalize_units(_heal_ocr_math(value)))

    def answer_field(value: str) -> str:
        value = strip_imported_answer_punct(re.sub(r"(?:\s|\\\\)+$", "", value or ""))
        value = wrap_answer_numbers(wrap_plain_answer(text_field(value)))
        value = re.sub(r"(?<!\\right)\.\s*\$$", "$", value)
        return re.sub(r"(?<=\S)[ \t]+\$(?=[\s;,.)]|$)", "$", value)

    task.text_latex = text_field(task.text_latex)
    task.author_solution_latex = text_field(task.author_solution_latex)
    task.author_answer_latex = answer_field(task.author_answer_latex)
    for item in task.subitems:
        item.label = cyrillic_item_label(item.label)
        item.text_latex = text_field(item.text_latex)
        item.author_solution_latex = text_field(item.author_solution_latex)
        item.author_answer_latex = answer_field(item.author_answer_latex)
    answers = [task.author_answer_latex] + [i.author_answer_latex for i in task.subitems]
    if any(LEFTOVER_LABEL_RE.search(value or "") for value in answers):
        task.warnings.append("В ответе остались метки других пунктов: сверить с книгой")
        task.confidence = max(0.0, task.confidence - 0.3)


_FIELDS = {"text": "text_latex", "answer": "author_answer_latex",
           "solution": "author_solution_latex"}


def apply_task_repair(task: TaskDraft, fields: dict) -> None:
    """Сверенная со сканом правка готовых полей задачи.

    ``text`` / ``answer`` / ``solution`` — поле целиком (у ``text`` пункты
    «а) … б) …» делятся заново), ``stars``, ``patches`` — точечные замены
    ``{field, before, after}``: фрагмент обязан встречаться ровно один раз;
    ``field`` — ``text``/``answer``/``solution`` или ``subitem:б``.
    """
    # Правки пишут рисунки именами файлов: \taskpic{N} задачи — обратно
    # в \includegraphics, после правки нумерация собирается заново.
    def expand(value: str) -> str:
        return re.sub(r"\\taskpic\{(\d+)\}", lambda m: (
            "\\includegraphics{" + task.images[int(m.group(1)) - 1] + "}"
            if 0 < int(m.group(1)) <= len(task.images) else m.group(0)), value or "")
    for attr in _FIELDS.values():
        setattr(task, attr, expand(getattr(task, attr)))
    for item in task.subitems:
        for attr in _FIELDS.values():
            setattr(item, attr, expand(getattr(item, attr)))
    if "text" in fields:
        # Текст без меток пунктов — только общее условие, пункты остаются.
        text, subitems = split_subitems(fields["text"])
        task.text_latex = text
        if subitems:
            task.subitems = subitems
    for key in ("answer", "solution"):
        if key in fields:
            setattr(task, _FIELDS[key], fields[key])
    if "stars" in fields:
        task.stars = fields["stars"]
    for patch in fields.get("patches", []):
        name = patch["field"]
        if name.startswith("subitem:"):
            label = name.split(":", 1)[1]
            items = [i for i in task.subitems if i.label.rstrip(")") == label]
            if len(items) != 1:
                raise ValueError(f"{task.external_id}: нет пункта {label}")
            target, attr = items[0], "text_latex"
        else:
            target, attr = task, _FIELDS[name]
        value = getattr(target, attr)
        count = value.count(patch["before"])
        if count != 1:
            raise ValueError(
                f"{task.external_id}: фрагмент правки {name} встречается {count} раз")
        setattr(target, attr, value.replace(patch["before"], patch["after"], 1))
    if fields.get("clear_warnings"):
        task.warnings = []
        task.confidence = 1.0
    task.images = []
    finalize_draft_images(task)


def parse_shabunin_method(text: str, *, structure: dict | None = None) -> tuple[list[TaskDraft], dict]:
    if PROFILE_MARK not in text or "ПОУРОЧНОЕ ПЛАНИРОВАНИЕ" not in text:
        raise ValueError("Не найдены дидактические материалы пособия Шабунина")
    text, overrides, applied = load_repairs(text)
    structure = structure or load_structure()
    diagnostics: dict = {
        "source_repairs_applied": applied,
        "examples_by_paragraph": {},
        "works": {},
        "variants_without_tasks": [],
        "unused_answer_figures": {},
        "figures_without_reference": [],
        "theory_figures": [],
    }
    tasks: list[TaskDraft] = []
    for chapter, start, stop in _find_chapters(text, structure):
        zone = text[start:stop]
        didactic = DIDACTIC_RE.search(zone)
        if not didactic:
            raise ValueError(f"Глава {chapter['roman']}: нет дидактических материалов")
        tasks += parse_examples(zone[:didactic.start()], chapter, diagnostics)
        materials, figures = extract_answer_figures(zone[didactic.start():])
        used: set[int] = set()
        for work in work_zones(materials):
            work["topics"] = structure.get("works", {}).get(work["key"])
            for task in parse_work(materials, work, chapter, diagnostics):
                task.author_answer_latex = insert_answer_figures(
                    task.author_answer_latex, figures, used)
                for item in task.subitems:
                    item.author_answer_latex = insert_answer_figures(
                        item.author_answer_latex, figures, used)
                task.author_solution_latex = insert_solution_figures(
                    task.author_solution_latex, figures, used)
                tasks.append(task)
        unused = sorted(set(figures) - used)
        if unused:
            diagnostics["unused_answer_figures"][chapter["roman"]] = unused
    used = set()
    for task in tasks:
        if lift_stem_pictures(task):
            diagnostics.setdefault("stem_pictures", []).append(task.external_id)
        task.grade_band_codes = list(structure.get("grade_bands", []))
        _finish_fields(task)
        finalize_draft_images(task)
        if task.external_id in overrides:
            apply_task_repair(task, overrides[task.external_id])
            used.add(task.external_id)
    diagnostics["unused_overrides"] = sorted(set(overrides) - used)
    diagnostics["unique_tasks"] = len({t.external_id for t in tasks})
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["examples"] = sum(1 for t in tasks if ".П" in t.external_id)
    diagnostics["work_tasks"] = len(tasks) - diagnostics["examples"]
    return tasks, diagnostics

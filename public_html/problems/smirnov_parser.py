"""Профиль пособия В. А. Смирнова «Стереометрия» (подготовка к ЕГЭ).

В. А. Смирнов. «Геометрия. Стереометрия: пособие для подготовки к ЕГЭ»
(М.: МЦНМО, 2009), OCR Mathpix по скану без текстового слоя (страница
PDF = номер страницы в имени картинки Mathpix, страница книги — на 1 меньше).

Особенности книги:

- 9 разделов ``\\section*{N. …}``; в начале раздела — «Общие сведения»
  (теория с рисунками), затем «Задачи»: в разделе 1 — один список, в
  разделах 2–9 — «Уровень А», «Уровень В», «Уровень С» (буквы то
  кириллицей, то латиницей), нумерация в каждом уровне своя с 1;
- у каждой задачи ровно один рисунок (``\\includegraphics`` после условия);
- Mathpix резал списки на страницах: ``enumerate`` с ``\\setcounter`` и
  ``itemize`` с явными ``\\item[4.]`` чередуются — номер берётся по
  счётчику или из метки;
- «Ответы» в конце книги Mathpix превратил во вложенные списки, где
  глубина вложенности заменяет потерянные номера; достоверные ответы
  переписаны со скана в ``data/smirnov_answers.json`` (по sha256 TEX и
  PDF), а TEX используется только для сверки там, где номера читаемы.

Внешний ключ задачи — «S3/C17» (раздел / уровень латиницей / номер),
в разделе 1 — «S1/17»; подборки — раздел → уровень.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .koryanov_parser import MATH_RE, _prose, cyrillic_words, degrees, point_names, tidy
from .textbook_parser import Marker, TaskDraft, clean, finalize_draft_images, task_from_block
from .volchkevich_parser import canon_field


DATA_DIR = Path(__file__).with_name("data")
STRUCTURE_PATH = DATA_DIR / "smirnov_structure.json"
REPAIRS_PATH = DATA_DIR / "smirnov_repairs.json"
ANSWERS_PATH = DATA_DIR / "smirnov_answers.json"

SIGNATURE_RE = re.compile(r"Стереометрия|СТЕРЕОМЕТРИЯ")
LEVEL_LATIN = str.maketrans("АВС", "ABC")


def load_structure(path: Path = STRUCTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_repairs(text: str, path: Path = REPAIRS_PATH) -> tuple[str, dict, list[str]]:
    """Сверенные с PDF правки, привязанные к sha256 исходного TEX.

    ``patches`` — замены текста OCR до разбора (``before`` встречается ровно
    один раз); ``fixes`` — точечные правки готового поля карточки
    (``old`` → ``new``), применяются последними; ``answer_masks`` — маска
    задачи вместо построенной по ответу; ``editor_answers`` — редакторский
    ответ, решение и маска при доказанной ошибке книги (поля автора не
    меняются). У каждой правки — ``page`` (PDF).
    """
    spec: dict = {"fixes": [], "answer_masks": {}, "editor_answers": {}}
    if not path.exists():
        return text, spec, []
    data = json.loads(path.read_text(encoding="utf-8"))
    digest = source_digest(text)
    applied: list[str] = []
    for edition in data.get("editions", []):
        if edition.get("source_sha256") != digest:
            continue
        for patch in edition.get("patches", []):
            count = text.count(patch["before"])
            if count != 1:
                raise ValueError(f"Сверенный фрагмент {patch['id']} встречается {count} раз")
            text = text.replace(patch["before"], patch["after"], 1)
            applied.append(patch["id"])
        spec["fixes"].extend(edition.get("fixes", []))
        spec["answer_masks"].update(edition.get("answer_masks", {}))
        spec["editor_answers"].update(edition.get("editor_answers", {}))
    return text, spec, applied


def load_answers(digest: str, path: Path = ANSWERS_PATH) -> dict:
    """Ответы, переписанные со скана: {раздел: {уровень: {номер: LaTeX}}}.

    Привязаны к sha256 TEX: таблица сверена с нумерацией именно этого OCR.
    """
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source_sha256") != digest:
        return {}
    return data.get("sections", {})


# --------------------------------------------------------------------------
# Задачи
# --------------------------------------------------------------------------

SECTION_RE = re.compile(r"\\section\*\{\s*(?P<num>\d)\.\s+(?P<title>[^{}]*?)\s*\}")
TASKS_RE = re.compile(r"\\section\*\{\s*Задачи\s*\}")
LEVEL_RE = re.compile(r"\\section\*\{\s*Уровень\s+(?P<level>[АВСABC])\s*\}")
OTHER_SECTION_RE = re.compile(r"\\section\*\{[^{}]*\}")
ITEM_TOKEN_RE = re.compile(
    r"\\begin\{(?:enumerate|itemize)\}|\\end\{(?:enumerate|itemize)\}"
    r"|\\setcounter\{enumi\}\{(?P<counter>\d+)\}"
    r"|(?m:^[ \t]*\\item(?:\[(?P<label>\d{1,3})\.?\])?)")


def list_items(zone: str) -> list[tuple[int, str]]:
    """Пункты списков зоны: номер по счётчику ``enumerate`` (с
    ``\\setcounter``) или из метки ``\\item[4.]`` ``itemize``."""
    items: list[tuple[int, int, int]] = []
    counter = 0
    tokens = list(ITEM_TOKEN_RE.finditer(zone))
    for index, token in enumerate(tokens):
        raw = token.group(0)
        if raw.startswith("\\begin{enumerate}"):
            counter = 0
            continue
        if raw.startswith(("\\begin", "\\end")):
            continue
        if token.group("counter") is not None:
            counter = int(token.group("counter"))
            continue
        if token.group("label") is not None:
            counter = int(token.group("label"))
        else:
            counter += 1
        end = tokens[index + 1].start() if index + 1 < len(tokens) else len(zone)
        items.append((counter, token.end(), end))
    return [(number, zone[start:end].strip()) for number, start, end in items]


def task_zones(text: str, answers_at: int) -> list[tuple[int, str, str, int]]:
    """(раздел, уровень, зона, смещение) — зоны «Задачи» до раздела ответов.

    «Общие сведения» и подзаголовки теории («Объем пирамиды») в зону не
    входят: зона идёт от «Задачи» / «Уровень X» до следующего заголовка.
    """
    zones: list[tuple[int, str, str, int]] = []
    section = 0
    in_tasks = False
    heads = list(OTHER_SECTION_RE.finditer(text, 0, answers_at))
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else answers_at
        section_match = SECTION_RE.fullmatch(head.group(0))
        if section_match:
            section, in_tasks = int(section_match.group("num")), False
            continue
        if TASKS_RE.fullmatch(head.group(0)):
            in_tasks = True
            if section == 1:
                zones.append((section, "", text[head.end():end], head.end()))
            continue
        level = LEVEL_RE.fullmatch(head.group(0))
        if level and in_tasks:
            zones.append((section, level.group("level").translate(LEVEL_LATIN),
                          text[head.end():end], head.end()))
            continue
        in_tasks = False
    return zones


# --------------------------------------------------------------------------
# Оформление
# --------------------------------------------------------------------------

def prose_dashes(value: str) -> str:
    """«точки \\(E\\) и \\(F\\) - середины» — тире между словами."""
    return _prose(value, lambda chunk: re.sub(r"(?:(?<=\s)|^)-(?=\s)", "—", chunk))


# «углом \(60^{\circ}\) Боковое ребро» — OCR потерял точку между фразами.
_LOST_PERIOD_RE = re.compile(r"(?<=\\\))(?=\s+[А-ЯЁ][а-яё])")


def condition_text(value: str) -> tuple[str, bool]:
    """Условие задачи: тире, потерянные точки, точка в конце."""
    value = prose_dashes(value)
    # «призмы.\\» + рисунок — перенос строки перед \taskpic не нужен.
    value = re.sub(r"[ \t]*\\\\[ \t]*(?=\n?\\taskpic\{)", "", value)
    added = False
    value, lost = _LOST_PERIOD_RE.subn(".", value)
    added = bool(lost)
    # Точка в конце условия: перед рисунком \taskpic{1}, если её нет.
    match = re.search(r"(?P<tail>\S)(?P<gap>\s*(?:\\\\\s*)?)(?P<pic>\\taskpic\{\d+\}\s*)$", value)
    if match and match.group("tail") not in ".?!:":
        value = value[:match.end("tail")] + "." + value[match.end("tail"):]
        added = True
    elif not match and value and value.rstrip()[-1] not in ".?!:":
        value = value.rstrip() + "."
        added = True
    return value, added


def answer_latex(value: str) -> str:
    """Ответ из таблицы: «60°» → \\(60^{\\circ}\\), голое выражение — в формулу."""
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = re.sub(r"\s*\.\s*$", "", value)
    if not value:
        return ""
    if not MATH_RE.search(value) and not re.search(r"[А-Яа-яЁё]", value):
        value = value.replace("°", "^{\\circ}")
        return "\\(" + value + "\\)"
    return degrees(value)


# Вопрос об угле, а не о его косинусе: «найдите угол между…», «найдите угол
# \(SAC\)», «найдите двугранный угол». Ответ книги — градусы без знака.
ANGLE_QUESTION_RE = re.compile(
    r"(?:[Нн]айдите|[Вв]ычислите|[Оо]пределите|[Чч]ему равен)\s+"
    r"(?:(?:величину|двугранный|линейный)\s+)*угол(?![а-яё])")
# «В правильном тетраэдре \(A B C D E\) — точка» — OCR склеил ABCD и E.
GLUED_NAMES_RE = re.compile(r"тетраэдр[а-яё]*\s+\\\((?:\s*[A-Z]){5}\s*\\\)\s*—")


def degree_answer(condition: str, answer: str) -> str:
    """Угол в градусах: книга печатает «90» (оговорено во введении), по
    канону ответ — \\(90^{\\circ}\\); значение не меняется."""
    if ANGLE_QUESTION_RE.search(condition) and re.fullmatch(r"\\\(\d+(?:\{,\}\d+)?\\\)", answer):
        return answer[:-2] + "^{\\circ}\\)"
    return answer


_PLAIN_NUMBER_RE = re.compile(r"-?\d+(?:(?:\{,\}|,)\d+)?")
_DEGREE_ANSWER_RE = re.compile(r"(?P<num>\d+(?:(?:\{,\}|,)\d+)?)\s*\^\s*\{?\\circ\}?")


def answer_core(answer: str) -> str:
    """Содержимое единственной формулы ответа или «»."""
    spans = list(MATH_RE.finditer(answer))
    if len(spans) != 1 or answer.replace(spans[0].group(0), "").strip(" .") != "":
        return ""
    core = spans[0].group(0)
    core = re.sub(r"^(?:\\\(|\\\[|\$\$|\$)|(?:\\\)|\\\]|\$\$|\$)$", "", core).strip()
    return re.sub(r"\\displaystyle\s*", "", core).strip()


def answer_mask(answer: str) -> str:
    """Маска по напечатанному ответу.

    Целое или десятичное число (уровни А и В — часть B ЕГЭ) — ``decimal``;
    градусы — ``{{number: 60}}°``; одно числовое выражение (корни, дроби,
    \\pi, arccos/arctg) — ``number``. Ответ из нескольких частей или с
    буквами — без маски: его разбирает редактор.
    """
    core = answer_core(answer)
    if not core:
        return ""
    if _PLAIN_NUMBER_RE.fullmatch(core):
        return "{{decimal: " + core.replace("{,}", ",") + "}}"
    degree = _DEGREE_ANSWER_RE.fullmatch(core)
    if degree:
        return "{{number: " + degree.group("num").replace("{,}", ".").replace(",", ".") + "}}°"
    if re.search(r"[;=<>]|\\(?:text|mathrm|quad|cup|in)\b|(?<!\\)\b[a-zA-Z]\b(?![a-z])", _strip_commands(core)):
        return ""
    if "," in core.replace("{,}", ""):
        return ""
    return "{{number: " + core.replace("{,}", ".") + "}}"


def _strip_commands(core: str) -> str:
    """Имена команд и функций не считаются буквами-переменными ответа."""
    core = re.sub(r"\\operatorname\s*\{[^{}]*\}", " ", core)
    return re.sub(r"\\[A-Za-z]+", " ", core)


def _normalize_for_compare(value: str) -> str:
    value = re.sub(r"\\\(|\\\)|\$|\\displaystyle|\\left|\\right|\s|\{,\}", lambda m: "," if m.group(0) == "{,}" else "", value)
    value = value.replace("°", "^{\\circ}").rstrip(".")
    return value


# --------------------------------------------------------------------------
# Ответы TEX — только для сверки
# --------------------------------------------------------------------------

_INLINE_NUMBER_RE = re.compile(r"(?<![\d,{.\\])(?P<num>\d{1,2})\s*\.(?=\s|$)")


def tex_answer_zones(text: str, answers_at: int, structure: dict) -> list[tuple[int, str, str]]:
    """Зоны «Ответов» TEX: до первого «Уровень» — раздел 1, затем уровни
    по порядку таблицы структуры (заголовки разделов 2 и 3 Mathpix спрятал
    в списки, поэтому раздел узнаётся по номеру «Уровня» подряд)."""
    zone = text[answers_at:]
    heads = list(LEVEL_RE.finditer(zone))
    out = [(1, "", zone[:heads[0].start()] if heads else zone)]
    order = [(spec["number"], level) for spec in structure["sections"]
             for level in spec["counts"] if level]
    for index, head in enumerate(heads[:len(order)]):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(zone)
        section, level = order[index]
        if head.group("level").translate(LEVEL_LATIN) != level:
            continue
        out.append((section, level, zone[head.end():end]))
    return out


def tex_answer_chain(zone: str) -> dict[int, str]:
    """«… 10. 1. 11. 2. 12. 2.» → {11: «2», 12: «2»}: только ответы с
    читаемым номером в строке (номер следующий по порядку за предыдущим)."""
    flat = re.sub(r"\\(?:begin|end)\{(?:enumerate|itemize)\}|\\setcounter\{enum[iv]+\}\{\d+\}"
                  r"|\\section\*\{[^{}]*\}", " ", zone)
    flat = re.sub(r"\\item(?:\[[^\]]*\])?", " \x01 ", flat)
    # Таблицы ответов разделов 5–9: «\[\begin{aligned}& \text { 1. } \sqrt{2} \text {. 2. }…»
    # — формула целиком; номера и точки — в \text{…}, ячейки array — «&».
    flat = re.sub(r"\\begin\{(?:aligned|array)\}(?:\{[^{}]*\})?|\\end\{(?:aligned|array)\}"
                  r"|\\\[|\\\]", " ", flat)
    flat = re.sub(r"\\text\s*\{([^{}]*)\}", r" \1 ", flat)
    flat = re.sub(r"\\\\|(?<!\\)&", " ", flat)
    # «4.7 .» в ячейке array — «4. 7.»: десятичная запятая книги — «,», не точка.
    flat = re.sub(r"(?<=\d)\.(?=\d)", ". ", flat)
    found: dict[int, str] = {}
    for chunk in flat.split("\x01"):
        spans = [(m.start(), m.end()) for m in MATH_RE.finditer(chunk)]
        marks = [m for m in _INLINE_NUMBER_RE.finditer(chunk)
                 if not any(a < m.start() < b for a, b in spans)]
        # Цепочка подряд идущих номеров: «10. 1. 11. 2.» — 1 и 2 ответы, не
        # номера; номер принимается, только если перед ним есть значение
        # («2. 3. 3. 54.» — ответ 2 равен 3, номер 3 — второе «3.»).
        best: list[re.Match] = []
        for start in range(len(marks)):
            chain = [marks[start]]
            for mark in marks[start + 1:]:
                if (int(mark.group("num")) == int(chain[-1].group("num")) + 1
                        and chunk[chain[-1].end():mark.start()].strip(" .\n")):
                    chain.append(mark)
            if len(chain) > len(best):
                best = chain
        if len(best) < 2:
            continue
        for index, mark in enumerate(best):
            end = best[index + 1].start() if index + 1 < len(best) else len(chunk)
            value = chunk[mark.end():end].strip()
            # Хвост последнего ответа в строке — до первой точки после значения.
            if index + 1 == len(best):
                value = re.split(r"(?<!\d)\.(?:\s|$)|(?<=\d)\.\s", value + " ")[0]
            found[int(mark.group("num"))] = value.strip(" .")
    return found


# --------------------------------------------------------------------------
# Разбор целиком
# --------------------------------------------------------------------------

FIX_FIELDS = {"text": "text_latex", "answer": "author_answer_latex"}


def apply_fixes(task: TaskDraft, fixes: list[dict], diagnostics: dict) -> None:
    for fix in fixes:
        if fix["task"] != task.external_id:
            continue
        attr = FIX_FIELDS[fix["field"]]
        value = getattr(task, attr)
        count = value.count(fix["old"])
        if count == 1:
            setattr(task, attr, value.replace(fix["old"], fix["new"], 1))
            diagnostics["fixes_applied"].append(fix["id"])
        elif count == 0 and fix["new"] and fix["new"] in value:
            diagnostics["fixes_skipped"].append(fix["id"])
        else:
            diagnostics["fixes_failed"].append(f"{fix['id']}: «было» встречается {count} раз")


def round_kinds(text: str, structure: dict) -> set[str]:
    """Разные тела вращения в условии: цилиндр, конус, шар (сфера)."""
    kinds = set()
    for kind, pattern in structure.get("round_kinds", {}).items():
        if re.search(pattern, text, re.I):
            kinds.add(kind)
    return kinds


def external_id(section: int, level: str, number: int) -> str:
    return f"S{section}/{level}{number}"


def _page(images: list[str]) -> int | None:
    """Страница PDF из имени картинки Mathpix: «…-112_403_468_387_392» → 112."""
    for name in images:
        match = re.search(r"-(\d{3})_\d+_\d+_\d+_\d+$", name)
        if match:
            return int(match.group(1))
    return None


def parse_smirnov(text: str, *, structure: dict | None = None,
                  repairs_path: Path = REPAIRS_PATH,
                  answers_path: Path = ANSWERS_PATH) -> tuple[list[TaskDraft], dict]:
    structure = structure or load_structure()
    text = text.replace("\r\n", "\n")
    if not SIGNATURE_RE.search(text) or "Уровень" not in text:
        raise ValueError("Не найдено пособие Смирнова «Стереометрия»")
    digest = source_digest(text)
    answers = load_answers(digest, answers_path)
    text, repairs, patches = load_repairs(text, repairs_path)
    answers_at = text.find(structure["answers_start"])
    if answers_at < 0:
        raise ValueError("Не найден раздел «Ответы»")
    diagnostics: dict = {
        "source_sha256": digest,
        "answers_table": bool(answers),
        "source_repairs_applied": patches,
        "count_mismatch": [],
        "missing_answers": [],
        "answers_without_task": [],
        "answers_tex_mismatch": [],
        "answers_tex_checked": 0,
        "masks_missing": [],
        "masks_by_kind": {},
        "periods_added": [],
        "angle_answers": [],
        "editor_answers": [],
        "glued_names": [],
        "figures_missing": [],
        "fixes_applied": [],
        "fixes_skipped": [],
        "fixes_failed": [],
        "pages": {},
    }
    sections = {spec["number"]: spec for spec in structure["sections"]}
    level_titles = structure["level_titles"]
    round_re = re.compile(structure["round_bodies_re"], re.I)
    combination_re = re.compile(structure.get("combination_re", r"(?!)"), re.I)

    tasks: list[TaskDraft] = []
    seen: dict[tuple[int, str], list[int]] = {}
    for section, level, zone, _offset in task_zones(text, answers_at):
        spec = sections.get(section)
        if spec is None:
            diagnostics["count_mismatch"].append(f"раздел {section} вне таблицы структуры")
            continue
        path = [spec["title"]] + ([level_titles[level]] if level else [])
        for number, body in list_items(zone):
            key = external_id(section, level, number)
            task = task_from_block(Marker(0, 0, key), clean(body), path)
            task.topic_code = spec["topic"]
            task.topic_original = spec["title"]
            # Тела вращения в разделах объёмов и площадей — своя ветвь;
            # комбинации тел — вписанное или описанное тело (многогранник
            # или тело вращения) и два разных тела вращения в одной задаче
            # («цилиндр и конус имеют общие основание и высоту»).
            if spec.get("round_bodies") and round_re.search(task.text_latex):
                task.topic_code = structure["round_bodies_topic"]
                if (combination_re.search(task.text_latex)
                        or len(round_kinds(task.text_latex, structure)) > 1):
                    task.topic_code = structure["combination_topic"]
            seen.setdefault((section, level), []).append(number)
            tasks.append(task)

    for spec in structure["sections"]:
        for level, total in spec["counts"].items():
            numbers = seen.get((spec["number"], level), [])
            if numbers != list(range(1, total + 1)):
                diagnostics["count_mismatch"].append(
                    f"{spec['number']}{('/' + level) if level else ''}: номера {numbers}, ожидалось 1–{total}")

    tex_answers = {(section, level): tex_answer_chain(zone)
                   for section, level, zone in tex_answer_zones(text, answers_at, structure)}

    by_id = {task.external_id: task for task in tasks}
    for section, levels in answers.items():
        for level, values in levels.items():
            for number in values:
                if external_id(int(section), level, int(number)) not in by_id:
                    diagnostics["answers_without_task"].append(external_id(int(section), level, int(number)))

    for task in tasks:
        section, rest = task.external_id[1:].split("/")
        level = rest.rstrip("0123456789")
        number = int(rest[len(level):])
        raw = answers.get(section, {}).get(level, {}).get(str(number), "")
        task.author_answer_latex = answer_latex(raw)
        tex_raw = tex_answers.get((int(section), level), {}).get(number)
        if raw and tex_raw:
            diagnostics["answers_tex_checked"] += 1
            if _normalize_for_compare(answer_latex(tex_raw)) != _normalize_for_compare(task.author_answer_latex):
                diagnostics["answers_tex_mismatch"].append(
                    f"{task.external_id}: таблица «{raw}», TEX «{tex_raw}»")
        task.text_latex, added = condition_text(
            tidy(canon_field(point_names(cyrillic_words(degrees(task.text_latex))))))
        if added:
            diagnostics["periods_added"].append(task.external_id)
        task.author_answer_latex = tidy(canon_field(task.author_answer_latex))
        degree = degree_answer(task.text_latex, task.author_answer_latex)
        if degree != task.author_answer_latex:
            task.author_answer_latex = degree
            diagnostics["angle_answers"].append(task.external_id)
        task.collection_title = task.source_path[-1]
        task.grade_band_codes = list(structure["grade_bands"])
        if not task.images:
            diagnostics["figures_missing"].append(task.external_id)
        finalize_draft_images(task)
        apply_fixes(task, repairs["fixes"], diagnostics)
        if GLUED_NAMES_RE.search(task.text_latex):
            task.warnings.append("Склеены обозначения: «тетраэдре \\(ABCDE\\)» — сверить со сканом")
            diagnostics["glued_names"].append(task.external_id)
        if not task.author_answer_latex:
            diagnostics["missing_answers"].append(task.external_id)
        task.answer_mask = repairs["answer_masks"].get(task.external_id) or answer_mask(task.author_answer_latex)
        editor = repairs["editor_answers"].get(task.external_id)
        if editor:
            # Ответ книги остаётся в авторском поле, маска — по верному ответу.
            task.answer_latex = editor["answer"]
            task.solution_latex = editor["solution"]
            task.answer_mask = editor["mask"]
            diagnostics["editor_answers"].append(task.external_id)
        if task.author_answer_latex and not task.answer_mask:
            diagnostics["masks_missing"].append(task.external_id)
        kind = re.match(r"\{\{(\w+)", task.answer_mask)
        if kind:
            diagnostics["masks_by_kind"][kind.group(1)] = diagnostics["masks_by_kind"].get(kind.group(1), 0) + 1
        page = _page(task.images)
        if page:
            diagnostics["pages"][task.external_id] = page

    diagnostics["unique_tasks"] = len(by_id)
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_section"] = dict(Counter(" / ".join(t.source_path) for t in tasks))
    diagnostics["topics"] = dict(Counter(t.topic_code for t in tasks))
    return tasks, diagnostics

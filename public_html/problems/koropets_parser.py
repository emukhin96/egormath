"""Профиль пособия Коропец «Нестандартные методы решения неравенств».

З. Л. Коропец, А. А. Коропец, Т. А. Алексеева. «Математика. Нестандартные
методы решения неравенств и их систем» (Госуниверситет — УНПК), OCR Mathpix
по PDF, свёрстанному в Word (формулы — векторные, страница PDF = страница
книги).

Особенности книги:

- глава 1 — теория метода замены множителя (МЗМ), задач нет; главы 2–9 —
  классы неравенств, в каждой «Примеры с решениями» и «Примеры для
  самостоятельного решения» с ответами в конце главы;
- пример: «Пример N. Решите неравенство …», «Решение. …», «Ответ: …»;
  ключ — «П2.5» (глава 2, пример 5), самостоятельная — «2.5»;
- метод интервалов в разборах — векторные числовые оси; Mathpix вырезает
  их через раз, а системы и совокупности рядом с осями превращает в мусор.
  Поэтому разборы, где OCR не годится, переписаны по скану в сверенных
  правках (``data/koropets_repairs.json``, поле ``tasks``), оси — рисунки
  ``koropets-pNNN-K`` из ZIP партии (вырезаны из PDF);
- заголовок главы 2 OCR превратил в пункт списка — границы глав ищутся
  по заголовкам разделов «N.2. Примеры с решениями» и т. п.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .textbook_parser import (
    Marker, TaskDraft, clean, finalize_draft_images, task_from_block)


DATA_DIR = Path(__file__).with_name("data")
STRUCTURE_PATH = DATA_DIR / "koropets_structure.json"
REPAIRS_PATH = DATA_DIR / "koropets_repairs.json"

# Ответ последнего примера главы 8.1 и следующий раздел теории
# разделены только заголовком: ответ — до пустой строки или заголовка.
EXAMPLE_RE = re.compile(
    r"(?m)^[ \t]*(?:\\item\[\][ \t]*)?Пример[ \t]+(?P<number>\d{1,2})\.")
SOLUTION_RE = re.compile(r"(?:\\section\*\{)?Решение\s*\.\s*\}?")
ANSWER_RE = re.compile(r"(?:\\item\[\]\s*)?Ответ\s*:")
SECTION_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:\\(?:sub)*section\*\{)?\d\.\d(?:\.\d)?\.[^\n]*$")


def _heading(number: int, section: str) -> re.Pattern:
    return re.compile(
        r"(?m)^[ \t]*(?:\\section\*\{)?" + str(number) + r"\.\d\.\s*" + section)


def load_structure(path: Path = STRUCTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_repairs(text: str, path: Path = REPAIRS_PATH) -> tuple[str, dict, list[str]]:
    """Сверенные с книгой правки, привязанные к sha256 исходного TEX.

    ``patches`` — точечные замены текста OCR (фрагмент встречается ровно
    один раз); ``tasks`` — переписанные по скану поля задачи целиком
    (``text``, ``answer``, ``solution``).
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
        overrides.update(edition.get("tasks", {}))
    return text, overrides, applied


def _items(zone: str) -> list[str]:
    """Пункты верхнего уровня ``enumerate`` (вложенных списков в книге нет)."""
    zone = re.sub(r"\\(?:begin|end)\{enumerate\}", "", zone)
    parts = re.split(r"(?m)^[ \t]*\\item\b(?:\[[^\]]*\])?", zone)
    return [part.strip() for part in parts[1:]]


def _answer_text(value: str) -> str:
    """Ответ книги — множество решений: формула целиком.

    OCR оставляет часть интервалов вне формулы («[-2; -1] \\(\\cup\\{1\\}\\)»)
    и тянет хвосты окружений — снимаем разметку и оборачиваем заново.
    """
    value = value.replace(r"\hspace{0pt}", "")
    value = re.sub(r"\\(?:end|begin)\{(?:enumerate|itemize)\}|\\section\*?\{?", "", value)
    value = re.sub(r"\\\\(?:\[0pt\])?", " ", value)
    value = re.sub(r"\\[()]", "", value).strip()
    value = re.sub(r"\s+", " ", value).rstrip(".").strip()
    if not value:
        return ""
    # Элементы ответа книга разделяет «;»: запятая между цифрами —
    # десятичная. «{0,5}» без {,} маска читает как множество {0; 5}.
    value = re.sub(r"(\d),(?=\d)", r"\1{,}", value)
    return clean("\\(" + value + "\\).")


def split_example(body: str) -> tuple[str, str, str]:
    """(условие, разбор, ответ). Ответ — после последнего «Ответ:»."""
    body = SECTION_LINE_RE.sub("", body)
    solution_at = SOLUTION_RE.search(body)
    answers = list(ANSWER_RE.finditer(body))
    if not answers:
        stem_end = solution_at.start() if solution_at else len(body)
        return body[:stem_end], body[solution_at.end():] if solution_at else "", ""
    last = answers[-1]
    tail = body[last.end():]
    stop = re.search(r"\n\s*\n|\\section|\\subsection", tail)
    answer = tail[:stop.start()] if stop else tail
    stem_end = solution_at.start() if solution_at else last.start()
    solution = body[solution_at.end():last.start()] if solution_at else ""
    return body[:stem_end], solution, answer


_STEM_PREFIX_RE = re.compile(r"^\s*Решите\s+(?:систему\s+)?неравенств[оа]\s*", re.I)


def build_example(chapter: dict, number: int, body: str, path: list[str]) -> TaskDraft:
    stem, solution, answer = split_example(body)
    key = f"П{chapter['number']}.{number}"
    stem = re.sub(r"\\\\\s*$", "", stem.strip())
    stem = re.sub(r"\\quad\s*", "", stem)
    # «(1)» — авторская метка неравенства для ссылок в разборе.
    task = task_from_block(Marker(0, 0, key), stem, path)
    task.author_solution_latex = clean(solution.strip())
    task.author_answer_latex = _answer_text(answer)
    return task


def build_exercise(chapter: dict, number: int, item: str, lead: str,
                   answer: str, path: list[str]) -> TaskDraft:
    key = f"{chapter['number']}.{number}"
    text = f"{lead} {item}".strip() if lead else item
    text = re.sub(r"\\quad\s*", "", text)
    task = task_from_block(Marker(0, 0, key), text, path)
    task.author_answer_latex = _answer_text(answer) if answer else ""
    return task


# «Решите неравенство \\(F\\).» — формула выносная: в PDF листка (A5)
# длинное неравенство в строке после слов уходит за поле.
_INLINE_STEM_RE = re.compile(
    r"^(?P<lead>Решите[^\\$]*?)\s*\\\(\s*(?:\\displaystyle\s*)?(?P<body>.*?)\s*(?<!\\right)\.?\s*\\\)"
    r"\s*\.?\s*(?P<label>\\quad\s*\(\d\))?\s*$",
    re.S)


def display_stem(text: str) -> str:
    """Формула условия «Решите … \\(…\\).» — выносной строкой."""
    match = _INLINE_STEM_RE.match(text)
    if not match or "\\(" in match.group("body") or "\\)" in match.group("body"):
        return text
    body = match.group("body")
    if match.group("label"):
        body += " " + match.group("label")
    return f"{match.group('lead').rstrip()} \\[{body}\\]"


_LABEL_COLUMN_RE = re.compile(
    r"\s*\\q?quad\s*\\begin\{array\}\{l\}\s*\(\d\)(?:\s*\\\\\s*\(\d\))*\s*\\end\{array\}")
_LABEL_RE = re.compile(r"\s*\\q?quad\s*\(\d\)|(?<=\\\))\s*\(\d\)\s*$")


def strip_labels(text: str) -> str:
    """Номера неравенств книги «(1)», «(2)» в условии не нужны: разбор
    ссылается на них словами «неравенство (1)», условие — без меток."""
    return _LABEL_RE.sub("", _LABEL_COLUMN_RE.sub("", text)).rstrip()


_DISPLAY_RE = re.compile(r"\\\[(?P<body>.*?)\\\]", re.S)
_TOKEN_RE = re.compile(
    r"\\(?:left|right)(?![a-zA-Z])|\\(?:begin|end)\{[^{}]*\}|\\Leftrightarrow(?![a-zA-Z])|(?<!\\)[{}]")


def split_chain(body: str) -> list[str]:
    """Части выносной формулы после каждого «⇔» верхнего уровня
    (вне скобок, \\left…\\right и окружений)."""
    parts, depth, start = [], 0, 0
    for token in _TOKEN_RE.finditer(body):
        value = token.group(0)
        if value in ("{", "\\left") or value.startswith("\\begin"):
            depth += 1
        elif value in ("}", "\\right") or value.startswith("\\end"):
            depth -= 1
        elif depth == 0:
            parts.append(body[start:token.end()].strip())
            start = token.end()
    tail = body[start:].strip()
    if tail:
        parts.append(tail)
    # Короткое звено («(1) ⇔», «I. ⇔») остаётся в строке со следующим.
    merged: list[str] = []
    for part in parts:
        if merged and len(re.sub(r"\\[a-zA-Z]+|[\s{}]", "", merged[-1])) < 8:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


_INLINE_RE = re.compile(r"\\\((?P<body>.*?)\\\)", re.S)
# «…, g(x)=…», «…; x_{2}=…» — перечисление обозначений в одной формуле.
_NAMED_RE = re.compile(
    r"\s*[,;]\s*(?=[a-zA-Z](?:_\{?\d\}?)?(?:\s*\(x\))?\s*=)")


def _top_level_split(body: str, pattern: re.Pattern, keep: bool) -> list[str]:
    """Режет формулу по ``pattern`` только вне скобок и окружений.
    keep — разделитель остаётся в конце левой части («⇔»)."""
    depth_at = []
    depth = 0
    for token in _TOKEN_RE.finditer(body):
        value = token.group(0)
        if value in ("{", "\\left") or value.startswith("\\begin"):
            depth += 1
        elif value in ("}", "\\right") or value.startswith("\\end"):
            depth -= 1
        depth_at.append((token.start(), depth))

    def depth_of(pos: int) -> int:
        current = 0
        for start, value in depth_at:
            if start >= pos:
                break
            current = value
        return current

    parts, start = [], 0
    for match in pattern.finditer(body):
        if depth_of(match.start()) != 0:
            continue
        cut = match.end() if keep else match.start()
        parts.append(body[start:cut].strip())
        start = match.end()
    parts.append(body[start:].strip())
    return [part for part in parts if part]


def break_chains(text: str) -> str:
    """Длинные строки книги (A4) — под листок A5, без правки содержания.

    Выносная формула-цепочка равносильностей — по строке на звено;
    строчная — на соседние формулы после «⇔» и перед «, g(x)=…»,
    чтобы строку можно было перенести.
    """
    def display(match: re.Match) -> str:
        parts = split_chain(match.group("body"))
        if len(parts) < 2:
            return match.group(0)
        return "\n".join(f"\\[{part}\\]" for part in parts)

    def inline(match: re.Match) -> str:
        parts = []
        for part in _top_level_split(match.group("body"), re.compile(r"\\Leftrightarrow(?![a-zA-Z])"), True):
            pieces = _top_level_split(part, _NAMED_RE, False)
            parts.extend(piece + "," if i < len(pieces) - 1 else piece
                         for i, piece in enumerate(pieces))
        if len(parts) < 2:
            return match.group(0)
        # Запятая между обозначениями — текстом после формулы.
        out = []
        for part in parts:
            if part.endswith(",") and not part.endswith("\\,"):
                out.append(f"\\({part[:-1].rstrip()}\\),")
            else:
                out.append(f"\\({part}\\)")
        return " ".join(out)

    return _INLINE_RE.sub(inline, _DISPLAY_RE.sub(display, text))


LEAD_RE = re.compile(r"(Решите[^\n]*?):\s*$", re.M)


def _lead(zone: str) -> str:
    """«Решите неравенства:» перед списком — общее требование задач."""
    match = LEAD_RE.search(zone.split("\\begin{enumerate}")[0])
    if not match:
        return ""
    lead = match.group(1).strip()
    return {"Решите неравенства": "Решите неравенство",
            "Решите системы неравенств": "Решите систему неравенств"}.get(lead, lead)


def _apply_override(task: TaskDraft, override: dict) -> None:
    if "text" in override:
        task.text_latex = override["text"]
    if "answer" in override:
        task.author_answer_latex = override["answer"]
    if "solution" in override:
        task.author_solution_latex = override["solution"]


def parse_koropets(text: str, *, structure: dict | None = None,
                   repairs_path: Path = REPAIRS_PATH) -> tuple[list[TaskDraft], dict]:
    structure = structure or load_structure()
    text = text.replace("\r\n", "\n")
    if "МЕТОД ЗАМЕНЫ МНОЖИТЕЛЯ" not in text:
        raise ValueError("Не найдено пособие Коропец «Нестандартные методы решения неравенств»")
    text, overrides, patches = load_repairs(text, repairs_path)
    diagnostics: dict = {
        "source_repairs_applied": patches,
        "overrides_applied": [],
        "count_mismatch": [],
        "missing_answers": [],
        "missing_solutions": [],
    }
    tasks: list[TaskDraft] = []
    chapters = structure["chapters"]
    # Оглавление повторяет заголовки разделов: ищем после него.
    body_at = text.find("\\section*{1. МЕТОД ЗАМЕНЫ")
    literature = text.find("ЛИТЕРАТУРА", max(body_at, 0))
    for index, chapter in enumerate(chapters):
        number = chapter["number"]
        exercises_at = _heading(number, "Примеры для самостоятельного").search(text, body_at)
        if exercises_at is None:
            raise ValueError(f"Не найден раздел «Примеры для самостоятельного решения» главы {number}")
        if index + 1 < len(chapters):
            nxt = re.compile(r"\\section\*\{" + str(chapters[index + 1]["number"]) + r"\.\s").search(text, body_at)
            chapter_end = nxt.start() if nxt else len(text)
        else:
            chapter_end = literature if literature > 0 else len(text)
        # Примеры: от конца предыдущей главы (её ответов) до самостоятельных.
        if index == 0:
            first = _heading(number, "Примеры с решениями").search(text, body_at)
            if first is None:
                raise ValueError(f"Не найден раздел «Примеры с решениями» главы {number}")
            start = first.start()
        else:
            start = previous_end
        previous_end = chapter_end
        zone = text[start:exercises_at.start()]
        markers = list(EXAMPLE_RE.finditer(zone))
        numbers = [int(m.group("number")) for m in markers]
        if numbers != list(range(1, chapter["examples"] + 1)):
            diagnostics["count_mismatch"].append(
                f"гл. {number}: примеры {numbers}, ожидалось 1–{chapter['examples']}")
        path = [chapter["title"], structure["examples_title"]]
        for i, match in enumerate(markers):
            end = markers[i + 1].start() if i + 1 < len(markers) else len(zone)
            tasks.append(build_example(chapter, int(match.group("number")),
                                       zone[match.end():end], path))

        rest = text[exercises_at.end():chapter_end]
        answers_at = re.search(r"(?m)^\s*Ответы\s*:", rest)
        if answers_at is None:
            raise ValueError(f"Не найдены ответы к главе {number}")
        exercise_zone, answer_zone = rest[:answers_at.start()], rest[answers_at.end():]
        items, answers = _items(exercise_zone), _items(answer_zone)
        if len(items) != chapter["exercises"] or len(answers) != chapter["exercises"]:
            diagnostics["count_mismatch"].append(
                f"гл. {number}: задач {len(items)}, ответов {len(answers)}, "
                f"ожидалось {chapter['exercises']}")
        lead = _lead(exercise_zone)
        path = [chapter["title"], structure["exercises_title"]]
        for i, item in enumerate(items, 1):
            answer = answers[i - 1] if i - 1 < len(answers) else ""
            tasks.append(build_exercise(chapter, i, item, lead, answer, path))

    by_chapter = {c["number"]: c for c in chapters}
    for task in tasks:
        chapter = by_chapter[int(task.external_id.lstrip("П").split(".")[0])]
        if task.external_id in overrides:
            _apply_override(task, overrides[task.external_id])
            diagnostics["overrides_applied"].append(task.external_id)
        task.text_latex = display_stem(strip_labels(task.text_latex))
        task.author_solution_latex = break_chains(task.author_solution_latex)
        task.topic_code = structure.get("topics", {}).get(task.external_id, chapter["topic"])
        task.topic_original = chapter["title"]
        task.collection_title = task.source_path[-1]
        task.grade_band_codes = list(structure["grade_bands"])
        if not task.author_answer_latex:
            diagnostics["missing_answers"].append(task.external_id)
        if task.external_id.startswith("П") and not task.author_solution_latex:
            diagnostics["missing_solutions"].append(task.external_id)
        finalize_draft_images(task)
    diagnostics["unique_tasks"] = len({t.external_id for t in tasks})
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_section"] = dict(Counter(" / ".join(t.source_path) for t in tasks))
    return tasks, diagnostics

"""Профиль книги В. В. Ткачука «Математика — абитуриенту».

МЦНМО, 18-е изд. (2022). OCR — Mathpix по скану 959 страниц
(страница PDF = страница книги + 1).

Книга состоит из справочника (часть I, задач нет), 50 уроков подготовки к
экзамену (часть II) и вариантов вступительных экзаменов в МГУ за 1970–2021
годы (часть III); ответы, указания и решения к домашним заданиям и
вариантам — в конце книги.

Часть II. Урок: теория, разобранные «Задача N [k].» с «Решение.» и
«Ответ:», затем «Домашнее задание» — пронумерованный список, ответы к нему
в разделе «1. Домашние задания» сплошным потоком «УРОК N. 1. … 2. …».
Ключи: задача урока — «У1.3», задача домашнего задания — «Д1.3».
В заголовках часть уроков OCR превратил в строку без \\section
(«Урок 11»), поэтому уроки ищутся по строке «Урок N» в начале строки,
а их названия берутся из сверенной таблицы
``data/tkachuk_structure.json``.

Часть III. Год → факультет (отделение, вариант) → пронумерованные
задачи; ответы — в разделе «2. Ответы к вариантам» с сокращёнными
названиями факультетов («Химический ф-т и отд. геофизики геологического
ф-та»). Ключ — «1970.ХИМ.3».

Сверенные со сканом правки (``data/tkachuk_repairs.json``) применяются
только к TEX с указанным SHA-256: ``patches`` — точечные замены текста OCR
до разбора, ``tasks`` — поля задачи, переписанные по скану целиком.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .merzlyak_parser import normalize_degrees, normalize_units, wrap_answer_numbers
from .textbook_parser import (
    Marker, SubitemDraft, TaskDraft, clean, finalize_draft_images,
    task_from_block)


DATA_DIR = Path(__file__).with_name("data")
STRUCTURE_PATH = DATA_DIR / "tkachuk_structure.json"
REPAIRS_PATH = DATA_DIR / "tkachuk_repairs.json"

BOOK_MARKER = "МАТЕМАТИКА - АБИТУРИЕНТУ"


# --------------------------------------------------------------------------
# Данные книги
# --------------------------------------------------------------------------

def load_structure(path: Path = STRUCTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Repairs:
    """Сверенные с книгой правки одного скана."""
    tasks: dict = field(default_factory=dict)       # id → поля целиком
    drop: list = field(default_factory=list)        # не задачи книги
    renumber: dict = field(default_factory=dict)    # id OCR → верный id
    insert: list = field(default_factory=list)      # задачи, потерянные OCR
    patches: list = field(default_factory=list)     # применённые замены


def load_repairs(text: str, path: Path = REPAIRS_PATH) -> tuple[str, Repairs]:
    """Сверенные с книгой правки, привязанные к sha256 исходного TEX.

    ``patches`` — точечные замены текста OCR (фрагмент встречается ровно
    один раз); ``tasks`` — переписанные по скану поля задачи целиком
    (``text``, ``answer``, ``solution``, ``subitems``); ``drop``,
    ``renumber``, ``insert`` — состав задач, исправленный по скану.
    """
    repairs = Repairs()
    if not path.exists():
        return text, repairs
    spec = json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for edition in spec.get("editions", []):
        if edition.get("source_sha256") != digest:
            continue
        for patch in edition.get("patches", []):
            count = text.count(patch["before"])
            if count != 1:
                raise ValueError(
                    f"Сверенный фрагмент {patch['id']} встречается {count} раз")
            text = text.replace(patch["before"], patch["after"], 1)
            repairs.patches.append(patch["id"])
        repairs.tasks.update(edition.get("tasks", {}))
        repairs.drop.extend(edition.get("drop", []))
        repairs.renumber.update(edition.get("renumber", {}))
        repairs.insert.extend(edition.get("insert", []))
    return text, repairs


def apply_composition(tasks: list[TaskDraft], repairs: Repairs, diagnostics: dict) -> list[TaskDraft]:
    """Состав задач по скану: лишние убрать, номера исправить, потерянные
    OCR вставить после указанной задачи (с тем же разделом)."""
    if repairs.drop:
        dropped = set(repairs.drop)
        diagnostics["dropped"] = [t.external_id for t in tasks if t.external_id in dropped]
        tasks = [t for t in tasks if t.external_id not in dropped]
    for task in tasks:
        new_id = repairs.renumber.get(task.external_id)
        if new_id:
            level = task.source_number[len(task.external_id):]
            task.external_id = new_id
            task.source_number = new_id + level
            diagnostics["renumbered"].append(new_id)
    for spec in repairs.insert:
        index = next((i for i, t in enumerate(tasks) if t.external_id == spec["after"]), None)
        if index is None:
            diagnostics["structure_problems"].append(
                f"вставка {spec['id']}: нет задачи {spec['after']}")
            continue
        anchor = tasks[index]
        task = task_from_block(Marker(0, 0, spec["id"]), spec.get("text", ""), list(anchor.source_path))
        for name in ("topic_original", "collection_title"):
            setattr(task, name, getattr(anchor, name))
        task.grade_band_codes = list(anchor.grade_band_codes)
        task.tags = list(anchor.tags)
        task.topic_code = anchor.topic_code
        task.author_answer_latex = spec.get("answer", "")
        task.author_solution_latex = spec.get("solution", "")
        if spec.get("section"):
            move_to_section(task, spec["section"])
        elif task.external_id[:1].isdigit():
            task.topic_code = content_topic(task.text_latex)
        tasks.insert(index + 1, task)
        diagnostics["inserted"].append(spec["id"])
    return tasks


def move_to_section(task: TaskDraft, section: str) -> None:
    """Задача варианта в другой секции года: «2008 год / Химический …»
    (OCR слил секции, заголовок восстановлен по скану)."""
    parts = [part.strip() for part in section.split(" / ") if part.strip()]
    task.source_path = [task.source_path[0], *parts]
    task.collection_key = "/".join(task.source_path)
    task.collection_title = parts[-1]
    task.topic_original = ". ".join(parts)
    task.topic_code = content_topic(task.text_latex)
    task.tags = [tag for tag in task.tags if tag != "Олимпиада"]
    if re.search(r"(?i)олимпиад", section):
        task.tags.append("Олимпиада")


def lessons_of(structure: dict) -> list[dict]:
    """Уроки части II с главой: ``[{"chapter": {...}, **lesson}]``."""
    result = []
    for chapter in structure["chapters"]:
        for lesson in chapter["lessons"]:
            result.append({**lesson, "chapter": chapter})
    return result


# --------------------------------------------------------------------------
# OCR: типовой брак Mathpix в этой книге
# --------------------------------------------------------------------------

# «si \(\mathrm{n}^{2} x\)», «\operatorname{si~} \mathrm{n} 2 x», «si n x»:
# OCR рвёт «sin» пробелом (в скане — разрядка курсивом).
_SIN_FIXES = (
    (re.compile(r"\\operatorname\{si~?\}\s*\\mathrm\{n\}"), r"\\sin"),
    (re.compile(r"\\operatorname\{\s*s\s*i\s*n\s*\}"), r"\\sin"),
    (re.compile(r"\\text\s*\{\s*si\s*n\s*\}"), r"\\sin"),
    (re.compile(r"\\operatorname\{si\}\s*\\mathrm\{n\}"), r"\\sin"),
    (re.compile(r"(?<![\\a-zA-Z])si\s*\\mathrm\{n\}"), r"\\sin"),
    (re.compile(r"\\sin\s*\\mathrm\{n\}"), r"\\sin"),
    (re.compile(r"\\text\s*\{\s*si\s+n\s*\}"), r"\\sin"),
    (re.compile(r"(?<![\\a-zA-Zа-яА-Я])si\s+n(?=\s*[\\({x2-9^]|\s+[a-zα-ω]\b)"), r"\\sin"),
)

_WORD_FIXES = (
    (re.compile(r"(?<![а-яА-Яa-zA-Z])[РP][еe]\s?ш\s?[еe]\s?[нn]\s?[иu]\s?[еe](?=\s*[.:])"), "Решение"),
    (re.compile(r"(?m)(^|\s)\(\)твет\s*:"), r"\1Ответ:"),
    (re.compile(r"(?<![а-яА-Яa-zA-Z])O(?=тве?т\s*:)"), "О"),
    (re.compile(r"(?<![а-яА-Яa-zA-Z])P(?=[eе]ш[ае])"), "Р"),
    (re.compile(r"(?<=[РP])e(?=ш[ае])"), "е"),
)


def heal_ocr(value: str) -> str:
    """Типовой OCR-брак книги, не меняющий содержания.

    «sin», разорванный пробелом (в книге — разрядка), латинские «O», «P»
    в словах «Ответ», «Решение».
    """
    if not value:
        return value
    for pattern, repl in _WORD_FIXES:
        value = pattern.sub(repl, value)
    # «si \(\mathrm{n}^{2} x\)»: часть слова вне формулы.
    value = re.sub(
        r"(?<![\\a-zA-Zа-яА-Я])si\s*\\\(\s*\\mathrm\{n\}", r"\\(\\sin", value)
    for pattern, repl in _SIN_FIXES:
        value = pattern.sub(repl, value)
    return value


# --------------------------------------------------------------------------
# Списки OCR: пункты, их номера и текст между списками
# --------------------------------------------------------------------------

@dataclass
class Item:
    label: str          # содержимое [..] у \item
    text: str           # текст пункта (без \item[..])


@dataclass
class Para:
    text: str           # абзац вне списков


LIST_ENV_RE = re.compile(r"\\(?P<kind>begin|end)\{(?:itemize|enumerate)\}")
ITEM_RE = re.compile(r"(?m)^[ \t]*\\item(?:\[(?P<label>[^\]]*)\])?[ \t]*")


def list_tokens(zone: str) -> list[Item | Para]:
    """Пункты списков верхнего уровня и абзацы между списками.

    Вложенные списки остаются в тексте пункта; ``\\setcounter`` внутри
    списков OCR выбрасывается.
    """
    tokens: list[Item | Para] = []
    depth = 0
    pos = 0
    current: Item | None = None

    def emit_text(chunk: str) -> None:
        nonlocal current
        if depth == 0 and not ITEM_RE.search(chunk):
            for para in re.split(r"\n\s*\n", chunk):
                if para.strip():
                    tokens.append(Para(para.strip()))
            current = None
            return
        if depth > 1:
            if current is not None:
                current.text += chunk
            return
        # depth == 1 (или пункты OCR без окружения): пункты верхнего уровня
        parts = list(ITEM_RE.finditer(chunk))
        head = chunk[:parts[0].start()] if parts else chunk
        if head.strip():
            if current is not None:
                current.text += head
            else:
                tokens.append(Para(head.strip()))
        for i, match in enumerate(parts):
            end = parts[i + 1].start() if i + 1 < len(parts) else len(chunk)
            current = Item(match.group("label") or "", chunk[match.end():end])
            tokens.append(current)

    for match in LIST_ENV_RE.finditer(zone):
        chunk = zone[pos:match.start()]
        emit_text(chunk)
        if match.group("kind") == "begin":
            if depth >= 1 and current is not None:
                current.text += match.group(0)
            depth += 1
        else:
            if depth > 1 and current is not None:
                current.text += match.group(0)
            depth = max(0, depth - 1)
            if depth == 0:
                current = None
        pos = match.end()
    emit_text(zone[pos:])
    for token in tokens:
        if isinstance(token, Item):
            token.text = re.sub(r"\\setcounter\{enum\w*\}\{\d+\}", "", token.text).strip()
    return tokens


# Номер пункта: «\item[-] 6.», «\item[] -3.», «\item[2.]», «\item 1-21.»,
# «\item[-] 16 [2].», «\item[11.]»; уровень [2]/[3] — после номера.
ITEM_NUMBER_RE = re.compile(
    r"^\s*-?\s*(?P<number>\d{1,2})(?:\s*-\s*(?P<last>\d{1,2}))?\s*"
    r"(?:\.\s*\[(?P<level_a>[23З])\]|\[(?P<level_b>[23З])\]\s*\.|\s*\[(?P<level_c>[23З])\]\s*\.?|\.)\s*")


def item_number(item: Item) -> tuple[int | None, int | None, int | None, str]:
    """(номер, последний номер диапазона, уровень, текст без номера)."""
    label = item.label.strip()
    text = item.text
    # OCR путает цифры и буквы в номере: «\item[b.]» — 6, «\item[З.]» — 3.
    label = {"b.": "6.", "б.": "6.", "З.": "3.", "З": "3"}.get(label, label)
    if re.fullmatch(r"\d{1,2}\.?", label):
        return int(label.rstrip(".")), None, None, text.strip()
    match = ITEM_NUMBER_RE.match(text)
    if not match:
        return None, None, None, text.strip()
    level = match.group("level_a") or match.group("level_b") or match.group("level_c")
    level_number = int(level.replace("З", "3")) if level else None
    last = int(match.group("last")) if match.group("last") else None
    return int(match.group("number")), last, level_number, text[match.end():].strip()


# --------------------------------------------------------------------------
# Часть II: уроки
# --------------------------------------------------------------------------

LESSON_RE = re.compile(
    r"(?m)^(?:\\section\*\{)?Урок\s+(?P<number>\d{1,2})(?:\s*\[(?P<level>[23])\])?[^\n]*$")
CHAPTER_RE = re.compile(r"(?m)^\\section\*\{Глава\s+\d+")
HOMEWORK_RE = re.compile(
    r"(?m)^[ \t]*\}?(?:\\section\*\{|\\textbackslash section\*\\\{)?"
    r"Домашнее задание(?:\}|\\\})?[ \t]*$")
LESSON_END_RE = re.compile(
    r"(?m)^[^\n]{0,40}(?:урок\w*|занятие)\s+(?:успешно\s+)?(?:закончен|окончен|завершен)")
TASK_RE = re.compile(
    r"(?m)^[ \t]*(?:\\item(?:\[[^\]]*\])?[ \t]*)?(?:-\s*)?Задача\s*(?P<number>\d{1,2})\s*"
    r"(?:\.\s*\[(?P<level_a>[23])\]|\[(?P<level_b>[23])\])?\s*\.?")
SOLUTION_RE = re.compile(r"(?<![а-яА-Я])Решение\s*[.:]")
ANSWER_RE = re.compile(r"(?<![а-яА-Я])Ответ\s*[:.]")
REMARK_RE = re.compile(r"^\s*(?:\\item(?:\[[^\]]*\])?\s*)?(?:Замечание|Примечание)\b")


@dataclass
class LessonSpan:
    lesson: dict
    start: int
    end: int
    level: int | None = None


def part_bounds(text: str) -> tuple[int, int, int]:
    """(начало части II, начало части III, начало ответов)."""
    part2 = text.find("\\section*{Часть II}")
    part3 = text.find("\\section*{Часть III}")
    answers = text.find("\\section*{Ответы, указания, решения}")
    if min(part2, part3, answers) < 0:
        raise ValueError("Не найдены части II, III или раздел ответов книги Ткачука")
    return part2, part3, answers


def lesson_spans(text: str, structure: dict) -> tuple[list[LessonSpan], list[str]]:
    part2, part3, _ = part_bounds(text)
    problems = []
    found: dict[int, re.Match] = {}
    for match in LESSON_RE.finditer(text, part2, part3):
        number = int(match.group("number"))
        if number not in found and (not found or number == max(found) + 1):
            found[number] = match
    lessons = lessons_of(structure)
    expected = [lesson["number"] for lesson in lessons]
    if sorted(found) != expected:
        problems.append(f"уроки: найдены {sorted(found)}")
    chapter_starts = [m.start() for m in CHAPTER_RE.finditer(text, part2, part3)]
    spans = []
    for index, lesson in enumerate(lessons):
        match = found.get(lesson["number"])
        if match is None:
            continue
        nxt = found.get(lesson["number"] + 1)
        end = nxt.start() if nxt else part3
        # Введение следующей главы (теория) — не часть урока.
        for start in chapter_starts:
            if match.start() < start < end:
                end = start
                break
        # Уровень урока — из сверенной таблицы: в части заголовков OCR потерял «[2]».
        level = int(match.group("level")) if match.group("level") else lesson.get("level")
        spans.append(LessonSpan(lesson, match.end(), end, level))
    return spans, problems


def _strip_tail_markup(value: str) -> str:
    value = re.sub(r"(?:\s*\\end\{(?:itemize|enumerate)\}|\s*\\begin\{(?:itemize|enumerate)\})+\s*$", "", value)
    value = re.sub(r"(?:\\\\\s*)+$", "", value.rstrip())
    return value.strip()


def _strip_lead_markup(value: str) -> str:
    value = re.sub(r"^\s*(?:\\end\{(?:itemize|enumerate)\}|\\begin\{(?:itemize|enumerate)\}|\\item(?:\[[^\]]*\])?)\s*", "", value)
    return value.strip()


def _paragraph_end(value: str) -> int:
    """Конец абзаца ответа: пустая строка, конец списка или следующий пункт.

    Выносная формула сразу после «Ответ:» («Ответ:\\n\\[…\\]») входит в ответ.
    """
    pos = 0
    while True:
        match = re.search(r"\n\s*\n|\\end\{itemize\}|\n\s*\\item\b", value[pos:])
        if not match:
            return len(value)
        end = pos + match.start()
        head = value[:end].strip()
        rest = value[pos + match.end():].lstrip()
        if (not head or head.endswith(":")) and rest.startswith("\\["):
            close = value.find("\\]", pos + match.end())
            if close < 0:
                return len(value)
            pos = close + 2
            continue
        return end


@dataclass
class WorkedTask:
    number: int
    level: int | None
    text: str
    solution: str
    answer: str
    warnings: list[str] = field(default_factory=list)


def split_worked(body: str) -> tuple[str, str, str, list[str]]:
    """(условие, решение, ответ, предупреждения) задачи урока.

    Решение — от «Решение.» до последнего «Ответ:»; ответ — абзац после
    него. Замечание автора сразу после ответа остаётся в решении; дальше
    идёт теория урока перед следующей задачей.
    """
    warnings = []
    solution_at = SOLUTION_RE.search(body)
    answers = list(ANSWER_RE.finditer(body))
    if solution_at is None:
        warnings.append("Не найдено «Решение.»: граница условия и решения — по абзацу")
        paragraph = re.search(r"\n\s*\n|\\end\{itemize\}", body)
        stem_end = paragraph.start() if paragraph else len(body)
        solution_start = stem_end
    else:
        stem_end = solution_at.start()
        solution_start = solution_at.end()
    answers = [match for match in answers if match.start() >= solution_start]
    if answers:
        last = answers[-1]
        tail = body[last.end():]
        answer_end = _paragraph_end(tail)
        answer = tail[:answer_end]
        solution = body[solution_start:last.start()]
        rest = tail[answer_end:]
        remarks = []
        for para in re.split(r"\n\s*\n", rest):
            if REMARK_RE.match(para):
                remarks.append(para)
            elif para.strip():
                break
        if remarks:
            solution = solution.rstrip() + "\n\nОтвет: " + answer.strip() + "\n\n" + "\n\n".join(remarks)
    else:
        answer = ""
        solution = body[solution_start:]
        # Без ответа: решение до конца блока (доказательства, построения).
    return body[:stem_end], solution, answer, warnings


def worked_tasks(zone: str) -> tuple[list[WorkedTask], list[str]]:
    markers = list(TASK_RE.finditer(zone))
    problems = []
    end_of_lesson = LESSON_END_RE.search(zone)
    stop = end_of_lesson.start() if end_of_lesson else len(zone)
    tasks = []
    for i, match in enumerate(markers):
        if match.start() >= stop:
            problems.append(f"«Задача {match.group('number')}» после конца урока")
            continue
        end = markers[i + 1].start() if i + 1 < len(markers) else stop
        end = min(end, stop)
        level = match.group("level_a") or match.group("level_b")
        text, solution, answer, warnings = split_worked(zone[match.end():end])
        tasks.append(WorkedTask(
            int(match.group("number")), int(level) if level else None,
            text, solution, answer, warnings))
    return tasks, problems


# Требование, опущенное в книге («Во всех задачах опущена фраза «решить
# уравнение»»): по виду формулы.
_WORDS_RE = re.compile(r"[а-яА-ЯёЁ]{3,}")


def _math_only(text: str) -> bool:
    """Условие — одна формула без слов (вне \\text{})."""
    bare = re.sub(r"\\text\s*\{[^{}]*\}|\\operatorname\{[^{}]*\}|\\mathrm\{[^{}]*\}", "", text)
    return not _WORDS_RE.search(bare)


def formula_kind(text: str) -> str:
    """eq / ineq / sys / sys_ineq / value («= ?») по формуле условия."""
    if re.search(r"=\s*\\?\)?\s*\?|=\s*\?|\?\s*\\?\)?\s*$", text):
        return "value"
    has_ineq = bool(re.search(r"\\(?:leqslant|geqslant|leq|geq|le|ge)(?![a-z])|<|>|\\lt|\\gt", text))
    system = bool(re.search(r"\\left\\\{|\\begin\{cases\}", text))
    if system:
        return "sys_ineq" if has_ineq else "sys"
    return "ineq" if has_ineq else "eq"


STEMS = {
    "eq": "Решите уравнение",
    "ineq": "Решите неравенство",
    "sys": "Решите систему уравнений",
    "sys_ineq": "Решите систему неравенств",
}


def _display_needed(body: str) -> bool:
    """Система или длинная формула — выносной строкой (листок A5)."""
    return bool(re.search(r"\\begin\{(?:array|cases|aligned)\}|\\left\\\{", body)) or len(body) > 70


def with_stem(text: str, stem: str | None) -> str:
    """Формула без слов — с требованием: «Решите уравнение \\(…\\).»."""
    text = text.strip()
    if not text or not _math_only(text):
        return text
    kind = formula_kind(text)
    if kind == "value" and not stem:
        return text
    lead = (stem or STEMS.get(kind) or "").rstrip(":").strip()
    if not lead:
        return text
    body = re.sub(r"\.?\s*$", "", text).strip()
    match = re.fullmatch(r"\\\((?P<body>.*)\\\)", body, re.S)
    if match and "\\(" not in match.group("body") and "\\)" not in match.group("body"):
        formula = re.sub(r"(?<!\\right)\.\s*$", "", match.group("body").strip()).strip()
        if _display_needed(formula):
            return f"{lead} \\[{formula}\\]"
        return f"{lead} \\({formula}\\)."
    match = re.fullmatch(r"\\\[(?P<body>.*)\\\]", body, re.S)
    if match:
        formula = re.sub(r"(?<!\\right)\.\s*$", "", match.group("body").strip()).strip()
        return f"{lead} \\[{formula}\\]"
    return f"{lead}: {body}"


# --------------------------------------------------------------------------
# Часть II: домашние задания
# --------------------------------------------------------------------------

@dataclass
class HomeworkTask:
    number: int
    level: int | None
    text: str
    lead: str = ""
    warnings: list[str] = field(default_factory=list)


# Абзац между списками — общее требование к следующим задачам, а не
# продолжение предыдущей («Решить системы:», «Все следующие задачи…»).
_LEAD_RE = re.compile(
    r"^(?:Все следующие задачи|Во всех задачах|Решить\s+(?:уравнения|неравенства|системы)|"
    r"Решите\s+(?:уравнения|неравенства|системы))", re.I)


def is_lead(text: str) -> bool:
    text = text.strip()
    return bool(_LEAD_RE.match(text)) or (text.endswith(":") and text[:1].isupper())


def homework_tasks(zone: str) -> tuple[list[HomeworkTask], str, list[str]]:
    """(задачи, общее требование ко всему заданию, проблемы)."""
    tokens = list_tokens(zone)
    tasks: list[HomeworkTask] = []
    problems: list[str] = []
    lead_all: list[str] = []
    lead = ""
    range_task: HomeworkTask | None = None
    range_last = 0
    for token in tokens:
        if isinstance(token, Para):
            text = token.text
            if not tasks and range_task is None:
                lead_all.append(text)
            elif is_lead(text):
                lead = text
            elif tasks:
                tasks[-1].text += "\n" + text
            continue
        number, last, level, body = item_number(token)
        previous = tasks[-1].number if tasks else 0
        if last:
            # «1-21. Построить треугольник по» + пункты «1. a, b, m_c;» …
            range_task = HomeworkTask(number, level, body, lead)
            range_last = last
            continue
        if range_task is not None and number is not None and number <= range_last:
            data = re.sub(r"[;.]\s*$", "", body).strip()
            tasks.append(HomeworkTask(
                number, level or range_task.level,
                f"{range_task.text.strip()} {data}.", lead))
            if number == range_last:
                range_task = None
            continue
        if number is None or number <= previous:
            if tasks:
                tasks[-1].text += "\n" + (token.text if number is None else body)
            else:
                lead_all.append(token.text)
            continue
        if number != previous + 1:
            problems.append(f"после {previous} идёт {number}")
        tasks.append(HomeworkTask(number, level, body, lead))
    return tasks, "\n".join(lead_all).strip(), problems


# --------------------------------------------------------------------------
# Ответы: поток «1. … 2. …» с номерами внутри формул
# --------------------------------------------------------------------------

MATH_SPAN_RE = re.compile(r"\\\((?:.|\n)*?\\\)|\\\[(?:.|\n)*?\\\]")

# Номер ответа: жирный в книге — «\mathbf{9} .», «\mathbf{1 5} .», «\mathbf{2 .}»
# внутри формулы, «12.» в тексте, «.4 .» / «.2\)» внутри формулы.
_BOLD_NUMBER_RE = re.compile(
    r"\\mathbf\s*\{\s*(?:Z\s*\.\s*~?\s*)?(?P<digits>\d(?:\s?\d)?)\s*(?P<dot>\.)?\s*~?\s*\}"
    r"\s*(?(dot)|(?:\\\)\s*)?(?:\.|\\cdot(?![a-z])))")
_TEXT_NUMBER_RE = re.compile(r"(?<![\w.,\-−\\{^_])(?P<digits>\d{1,2})\s?\.(?!\d)")
_MATH_NUMBER_RE = re.compile(
    r"(?<=[.;])\s*(?P<digits>\d{1,2})(?:\s\.|\.(?!\d))|(?<=\.)\s?(?P<tail>\d{1,2})\s*(?=\\\)$)")


@dataclass(frozen=True)
class NumberCandidate:
    start: int
    end: int
    value: int | None   # None — номер потерян OCR (WILDCARD)
    strength: int
    in_math: bool       # номер начинается внутри формулы: она закрывается перед ним
    reopen: bool = False  # формула продолжается после номера


def _math_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in MATH_SPAN_RE.finditer(text)]


def _inside(spans, pos: int) -> tuple[int, int] | None:
    for start, end in spans:
        if start < pos < end:
            return start, end
    return None


def number_candidates(text: str) -> list[NumberCandidate]:
    spans = _math_spans(text)
    found: dict[int, NumberCandidate] = {}

    def add(start, end, value, strength, in_math):
        old = found.get(start)
        span = _inside(spans, start)
        reopen = bool(span) and end < span[1] - 2
        if old is None or old.strength < strength:
            found[start] = NumberCandidate(start, end, value, strength, bool(span), reopen)

    for match in re.finditer(WILDCARD, text):
        add(match.start(), match.end(), None, 3, _inside(spans, match.start()) is not None)
    for match in _BOLD_NUMBER_RE.finditer(text):
        value = int(match.group("digits").replace(" ", ""))
        add(match.start(), match.end(), value, 3, _inside(spans, match.start()) is not None)
    for match in _TEXT_NUMBER_RE.finditer(text):
        if _inside(spans, match.start()):
            continue
        before = text[max(0, match.start() - 3):match.start()]
        strong = (match.start() == 0 or re.search(r"(?:[.;:)!?]|\\\)|\\\]|\})\s*$", before)
                  or before.endswith("\n"))
        add(match.start(), match.end(), int(match.group("digits")), 3 if strong else 1, False)
    for start, end in spans:
        inner_start = start + 2
        inner = text[inner_start:end]
        # Слабый кандидат: любое «N .» внутри формулы (десятичная дробь в
        # книге пишется через запятую); берётся, только если закрывает пропуск.
        for match in re.finditer(r"(?<![\\\w{^_.,])(?P<digits>\d{1,2})\s?\.", inner):
            add(inner_start + match.start(), inner_start + match.end(),
                int(match.group("digits")), 1, True)
        for match in re.finditer(r"(?<=\.)\s?(?P<digits>\d{1,2})(?=\s)", inner):
            add(inner_start + match.start("digits"), inner_start + match.end(),
                int(match.group("digits")), 1, True)
        for match in _MATH_NUMBER_RE.finditer(inner):
            digits = match.group("digits") or match.group("tail")
            group = "digits" if match.group("digits") else "tail"
            add(inner_start + match.start(group), inner_start + match.end(),
                int(digits), 2, True)
    return sorted(found.values(), key=lambda c: c.start)


def choose_chain(text: str, candidates: list[NumberCandidate], count: int,
                 first: int = 1) -> list[tuple[NumberCandidate, int]]:
    """Возрастающая цепочка номеров first..count с наибольшим весом.

    Пропуск номера дороже любого кандидата: OCR теряет номер редко, а
    числа в ответах («1. 3, 11.») встречаются часто. Пустой ответ между
    соседними номерами и текст до первого номера штрафуются. Кандидат
    ``WILDCARD`` принимает любое значение.
    """
    skip = 6
    neg = float("-inf")
    states: list[tuple[int, int]] = []          # (кандидат, значение)
    for i, cand in enumerate(candidates):
        values = range(first, count + 1) if cand.value is None else (
            [cand.value] if first <= cand.value <= count else [])
        for value in values:
            states.append((i, value))
    best: dict[tuple[int, int], tuple[float, tuple[int, int] | None]] = {}
    lead_cost = {}
    for i, cand in enumerate(candidates):
        lead = len(re.sub(r"\s|" + WILDCARD + r"|\\item(?:\[[^\]]*\])?|\\(?:begin|end)\{\w+\}", "", text[:cand.start]))
        lead_cost[i] = 0.5 * min(lead, 20)
    by_candidate: dict[int, list[tuple[int, int]]] = {}
    for state in states:
        by_candidate.setdefault(state[0], []).append(state)
    for i, cand in enumerate(candidates):
        for state in by_candidate.get(i, []):
            value = state[1]
            score = cand.strength - skip * (value - first) - lead_cost[i]
            prev = None
            for j in range(i):
                other = candidates[j]
                if other.end > cand.start:
                    continue
                gap = text[other.end:cand.start]
                empty = not re.sub(r"[\s.;,]|\\[()]|" + WILDCARD, "", gap)
                for other_state in by_candidate.get(j, []):
                    if other_state not in best or other_state[1] >= value:
                        continue
                    total = (best[other_state][0] + cand.strength
                             - skip * (value - other_state[1] - 1) - (5 if empty else 0))
                    if total > score:
                        score, prev = total, other_state
            best[state] = (score, prev)
    end_best, end_at = neg, None
    for state, (score, _) in best.items():
        value = score - skip * (count - state[1])
        if value > end_best:
            end_best, end_at = value, state
    chain = []
    while end_at is not None:
        chain.append((candidates[end_at[0]], end_at[1]))
        end_at = best[end_at][1]
    return list(reversed(chain))


def _balance_math(value: str) -> str:
    """Отрезок потока с половиной формулы: дописать недостающие \\( / \\)."""
    opens = len(re.findall(r"\\\(", value))
    closes = len(re.findall(r"\\\)", value))
    if closes > opens:
        first_close = value.find("\\)")
        first_open = value.find("\\(")
        if first_open < 0 or first_close < first_open:
            value = "\\(" + value
    opens = len(re.findall(r"\\\(", value))
    closes = len(re.findall(r"\\\)", value))
    if opens > closes:
        value = value + "\\)"
    return value


def split_stream(text: str, count: int, first: int = 1) -> tuple[dict[int, str], list[int]]:
    """Поток ответов → {номер: текст}; второй элемент — потерянные номера."""
    candidates = number_candidates(text)
    chain = choose_chain(text, candidates, count, first)
    pieces: dict[int, str] = {}
    for i, (cand, value) in enumerate(chain):
        end = chain[i + 1][0].start if i + 1 < len(chain) else len(text)
        chunk = text[cand.end:end]
        # Номер внутри формулы: формула закрывается перед ним и
        # открывается после.
        if cand.reopen:
            chunk = "\\(" + chunk
        if i + 1 < len(chain) and chain[i + 1][0].in_math:
            chunk = re.sub(r"[\s.;,]*$", "", chunk) + "\\)"
        chunk = chunk.replace(WILDCARD, " ")
        chunk = re.sub(r"\\\(\s*\.?\s*\\\)", " ", chunk)
        pieces[value] = _balance_math(chunk.strip())
    missing = [value for value in range(first, count + 1) if value not in pieces]
    return pieces, missing


# Начало книжного указания после ответа: «… n ∈ Z. Привести уравнение к виду …».
HINT_START_RE = re.compile(
    r"(?:(?<=[.;])|(?<=\\\))(?=\s+[А-ЯЁ]))\s*(?=(?:Привести|Приводится|Приведите|Переписать|"
    r"Перепишите|Воспольз|Выразить|Выразите|Указание|Сделайте|Сделать|Заметим|Заметьте|"
    r"Рассмотр|Обозначим|Обозначив|Обратите|Решение|Пусть|Положим|Используй|Использ|"
    r"Так как|Поскольку|Применить|Примените|Разделите|Разделив|Введ|Ввести|Свед|Свести|"
    r"Записать|Запишите|Умнож|Домнож|Возвести|Возведите|Преобраз|Разлож|Сравн|"
    r"Постройте|Построить|Нарисуйте|Нарисовать|Докажем|Доказательство|Покажем|"
    r"Указ\.|Подсказка|Проверьте|Проверить|Отметим|Найдем|Найдём|Найдите|Вычислим|"
    r"Решим|Решите|Решая|Подставим|Подставив|Подставьте|Учтите|Учесть|Имеем|"
    r"Обратим|Задача сводится|Уравнение|Неравенство|Система)\b)")
ANSWER_WORD_RE = re.compile(r"(?<![а-яА-Я])Ответ\s*:")
# Доказательство и построение: в разделе ответов — решение, ответа нет.
NO_ANSWER_TASK_RE = re.compile(r"^\s*(?:Доказать|Докажите|Построить|Постройте|Показать|Покажите)\b")


def split_answer_hint(value: str) -> tuple[str, str]:
    """(ответ, книжное указание) одного номера раздела ответов."""
    value = value.strip()
    answer_word = list(ANSWER_WORD_RE.finditer(value))
    if answer_word:
        last = answer_word[-1]
        hint = value[:last.start()].strip()
        answer = value[last.end():].strip()
        # Указание после ответа («Ответ: … . Привести …»).
        more = HINT_START_RE.search(answer)
        if more and more.start() > 0:
            hint = (hint + "\n" + answer[more.start():].strip()).strip()
            answer = answer[:more.start()].strip()
        return answer, hint
    if HINT_START_RE.match(" " + value) and re.match(r"[А-ЯЁ]", value):
        word = value.split(maxsplit=1)[0]
        if HINT_START_RE.search(". " + word + " "):
            return "", value
    match = HINT_START_RE.search(value)
    if match and match.start() > 0:
        return value[:match.start()].strip(), value[match.start():].strip()
    return value, ""


# --------------------------------------------------------------------------
# Раздел ответов к домашним заданиям
# --------------------------------------------------------------------------

HW_ANSWERS_RE = re.compile(r"\\section\*\{1\. Домашние задания\}")
VAR_ANSWERS_RE = re.compile(r"\\section\*\{2\. Ответы к вариантам")
# «УРОК 7.», OCR: «YPOK», «УPOK»
LESSON_ANSWER_RE = re.compile(
    r"(?:Y|У)\s?(?:P|Р)\s?(?:O|О)\s?(?:K|К)\s*(?P<number>\d{1,2})\s*\.")


_ENUM_TOKEN_RE = re.compile(
    r"\\begin\{enumerate\}|\\end\{enumerate\}|\\setcounter\{enum(?P<level>i+)\}\{(?P<value>\d+)\}"
    r"|\\item(?![a-zA-Z])(?P<label>\[[^\]]*\])?")


# Номер, потерянный OCR: строка ответов начиналась с «5.», а Mathpix сделал
# из неё пункт ``enumerate`` и пронумеровал заново. Значение такого номера
# выбирает цепочка (``choose_chain``) — следующее по порядку.
WILDCARD = "\ue000"


def number_enumerate_items(value: str) -> str:
    """«\\begin{enumerate}\\setcounter{enumi}{2}\\item Задача…» — это ответ 3:
    номер автоматического списка OCR вписываем текстом.

    Номер со ``\\setcounter`` перед пунктом надёжен (во вложенных списках
    OCR он несёт сам ответ: «1. 28. 2. −1.» → пункт «28»); пункт без
    счётчика — начало строки с неизвестным номером (``WILDCARD``).
    """
    out = []
    pos = 0
    stack: list[list] = []   # [счётчик, счётчик задан явно]
    for match in _ENUM_TOKEN_RE.finditer(value):
        token = match.group(0)
        out.append(value[pos:match.start()])
        pos = match.end()
        if token.startswith("\\begin"):
            stack.append([0, False])
        elif token.startswith("\\end"):
            if stack:
                stack.pop()
        elif token.startswith("\\setcounter"):
            if stack and len(match.group("level")) == len(stack):
                stack[-1] = [int(match.group("value")), True]
        else:
            if stack and match.group("label") is None:
                stack[-1][0] += 1
                if stack[-1][1]:
                    out.append(f" {stack[-1][0]}. ")
                    stack[-1][1] = False
                else:
                    out.append(f" {WILDCARD} ")
                continue
            out.append(token)
    out.append(value[pos:])
    return "".join(out)


def flatten_answer_stream(value: str) -> str:
    """Списки OCR в потоке ответов: «\\item[11.]» — номер, «\\item[в]» —
    слово, разорванное разметкой («в ОДЗ»)."""
    value = number_enumerate_items(value)
    value = re.sub(r"\\setcounter\{enum\w*\}\{\d+\}", " ", value)
    value = re.sub(r"\\(?:begin|end)\{(?:itemize|enumerate)\}", " ", value)
    value = re.sub(r"\\item\[(\d{1,2}\.)\]", r" \1 ", value)
    value = re.sub(r"\\item\[([^\]\-]+)\]", r" \1 ", value)
    value = re.sub(r"\\item(?:\[[^\]]*\])?", " ", value)
    value = re.sub(r"\\\\(?:\[\d+pt\])?", " ", value)
    return value


def homework_answer_streams(text: str) -> dict[int, str]:
    start = HW_ANSWERS_RE.search(text)
    end = VAR_ANSWERS_RE.search(text)
    if not start or not end:
        raise ValueError("Не найден раздел ответов «1. Домашние задания»")
    zone = text[start.end():end.start()]
    markers = []
    for match in LESSON_ANSWER_RE.finditer(zone):
        number = int(match.group("number"))
        if not markers or number == markers[-1][0] + 1:
            markers.append((number, match))
    streams = {}
    for i, (number, match) in enumerate(markers):
        stop = markers[i + 1][1].start() if i + 1 < len(markers) else len(zone)
        streams[number] = zone[match.end():stop]
    return streams


# --------------------------------------------------------------------------
# Темы по содержанию задачи
# --------------------------------------------------------------------------

def _has(text: str, *words: str) -> bool:
    low = text.lower()
    return any(word in low for word in words)


def _is_parametric(text: str) -> bool:
    return bool(re.search(r"(?i)параметр|при\s+каких|при\s+всех\s+\\\(a|для\s+каждого\s+(?:значения\s+)?\\\(a|"
                          r"найти\s+все\s+(?:значения\s+)?\\\(a|найдите\s+все\s+(?:значения\s+)?\\\(a", text))


def _algebra_topic(text: str) -> str:
    kind = formula_kind(text)
    if _is_parametric(text):
        return "ALG.08.02" if kind in ("ineq", "sys_ineq") else "ALG.08.01"
    if kind in ("sys", "sys_ineq") or _has(text, "систем"):
        return "ALG.03.11" if kind == "sys" else "ALG.04"
    if _has(text, "неравенств") or kind == "ineq":
        return "ALG.04"
    return "ALG.03"


def _solid_topic(text: str) -> str:
    if _has(text, "шар", "сфер"):
        return "GEO.10.05" if _has(text, "пирамид", "призм", "куб", "конус", "цилиндр", "тетраэдр", "вписан", "описан") else "GEO.10.03"
    if _has(text, "конус"):
        return "GEO.10.02"
    if _has(text, "цилиндр"):
        return "GEO.10.01"
    if _has(text, "призм", "параллелепипед", "куб"):
        return "GEO.09.01"
    if _has(text, "пирамид", "тетраэдр"):
        return "GEO.09.02"
    if _has(text, "трехгранн", "трёхгранн", "двугранн"):
        return "GEO.08.04"
    return "GEO.08"


TOPIC_RULES = {
    "progression": lambda t: ("ALG.06.03" if _has(t, "геометрическ") else
                              "ALG.06.02" if _has(t, "арифметическ") else "ALG.06"),
    "extremum": lambda t: "ALG.07.05" if _has(t, "наибольш", "наименьш", "максимум", "минимум") else "ALG.07.04",
    "area": lambda t: "GEO.03.07" if _has(t, "трапеци", "четырехугольн", "четырёхугольн", "параллелограм") else "GEO.02.08",
    "parallelogram": lambda t: "GEO.03.02" if _has(t, "трапеци") else "GEO.03.01",
    "polygon": lambda t: "GEO.03.06" if _has(t, "вписан", "описан") else "GEO.03.03",
    "construction": lambda t: "GEO.07.03" if _has(t, "треугольник", "окружност") else "GEO.07.02",
    "parameter": lambda t: "ALG.08.02" if formula_kind(t) in ("ineq", "sys_ineq") or _has(t, "неравенств") else "ALG.08.01",
    "algebra": _algebra_topic,
    "solid": _solid_topic,
    "vectors": lambda t: "GEO.11.01" if _has(t, "пространств", "\\{x") else "GEO.06.04",
}


def lesson_topic(lesson: dict, text: str) -> str:
    rule = lesson.get("topic")
    if isinstance(rule, str):
        return rule
    if "rule" in rule:
        return TOPIC_RULES[rule["rule"]](text)
    kind = formula_kind(text) if _math_only(text) or not _has(text, "уравнени", "неравенств") else (
        "ineq" if _has(text, "неравенств") else "eq")
    return rule["ineq"] if kind in ("ineq", "sys_ineq") else rule["eq"]


# --------------------------------------------------------------------------
# Часть II целиком
# --------------------------------------------------------------------------

def _lesson_path(structure: dict, lesson: dict, section: str) -> list[str]:
    chapter = lesson["chapter"]
    return [
        structure["part2_title"],
        f"Глава {chapter['number']}. {chapter['title']}",
        f"Урок {lesson['number']}. {lesson['title']}",
        section,
    ]


def _drop_unbalanced_lists(value: str) -> str:
    """Граница пункта OCR внутри решения: непарные itemize и \\item —
    разметка вёрстки, а не список автора."""
    begins = len(re.findall(r"\\begin\{itemize\}", value))
    ends = len(re.findall(r"\\end\{itemize\}", value))
    if begins == ends and begins == 0:
        return re.sub(r"(?m)^[ \t]*\\item(?:\[[^\]]*\])?[ \t]*", "", value)
    if begins != ends:
        value = re.sub(r"\\(?:begin|end)\{itemize\}", "", value)
        value = re.sub(r"(?m)^[ \t]*\\item(?:\[[^\]]*\])?[ \t]*", "", value)
    return value


_MATH_SPAN_ANY_RE = re.compile(r"\$\$.*?\$\$|\\\[.*?\\\]|\$.*?\$|\\\(.*?\\\)", re.S)


_LIST_RE = re.compile(r"\d,\s?-?\d+,\s?-?\d")
_PAIR_RE = re.compile(r"[\[(]\s*-?\d+,-?\d+\s*[\])]")


def decimal_commas(value: str) -> str:
    """Десятичная запятая в формулах — ``{,}``: «\\(2,5\\)» → «\\(2{,}5\\)».

    Книга пишет и списки через запятую без пробела: перечень «0,1,2» и
    пара или промежуток «[-1,1]», «(1,3)» не трогаются; список с пробелом
    после запятой («1, 2») — тоже.
    """
    def fix(match: re.Match) -> str:
        span = match.group(0)
        if _LIST_RE.search(span):
            return span
        pairs = [(m.start(), m.end()) for m in _PAIR_RE.finditer(span)]

        def comma(m: re.Match) -> str:
            if any(start < m.start() < end for start, end in pairs):
                return m.group(0)
            return "{,}"
        return re.sub(r"(?<=\d),(?=\d)", comma, span)
    return _MATH_SPAN_ANY_RE.sub(fix, value or "")


def paren_math(value: str) -> str:
    """Строчные ``$…$`` нормализаторов — в ``\\(…\\)``, как во всей книге."""
    return re.sub(r"(?<![\\$])\$(?!\$)([^$]+?)\$(?!\$)", r"\\(\1\\)", value or "")


def finish_text(value: str) -> str:
    """Единицы текстом, градусы, десятичная запятая (канон QA § 4.6, § 5.2)."""
    return paren_math(decimal_commas(normalize_degrees(normalize_units(value))))


def _prepare(value: str) -> str:
    value = _strip_tail_markup(_strip_lead_markup(heal_ocr(value)))
    return finish_text(clean(_drop_unbalanced_lists(value)))


def _answer_field(value: str) -> str:
    value = _strip_tail_markup(value.strip())
    value = re.sub(r"\s*\\square\s*$|\s*\\quad\s*\d\s*\\\)$", lambda m: "\\)" if m.group(0).endswith("\\)") else "", value)
    # Знак конца решения (◄) OCR читает как «4»: «… ∈ Z. \\quad 4».
    value = re.sub(r"\.\s*(?:\\quad\s*)?4\s*(?=\\\)$)", "", value.strip())
    value = re.sub(r"(?<=\.)\s+4\s*$", "", value)
    value = value.strip().rstrip(".").rstrip()
    value = re.sub(r"\s*\.\s*\\\)$", r"\\)", value)
    value = clean(heal_ocr(value))
    return paren_math(decimal_commas(wrap_answer_numbers(normalize_degrees(normalize_units(value)))))


def parse_part2(text: str, structure: dict, diagnostics: dict) -> list[TaskDraft]:
    spans, problems = lesson_spans(text, structure)
    diagnostics["structure_problems"].extend(problems)
    streams = homework_answer_streams(text)
    tasks: list[TaskDraft] = []
    for span in spans:
        lesson = span.lesson
        number = lesson["number"]
        body = text[span.start:span.end]
        homework_at = HOMEWORK_RE.search(body)
        worked_zone = body[:homework_at.start()] if homework_at else body
        homework_zone = body[homework_at.end():] if homework_at else ""
        if homework_at is None:
            diagnostics["structure_problems"].append(f"урок {number}: нет домашнего задания")

        worked, worked_problems = worked_tasks(worked_zone)
        diagnostics["structure_problems"].extend(f"урок {number}: {p}" for p in worked_problems)
        numbers = [w.number for w in worked]
        if numbers != list(range(1, len(numbers) + 1)):
            diagnostics["numbering"].append(f"урок {number}: задачи {numbers}")
        path = _lesson_path(structure, lesson, structure["lesson_tasks_title"])
        seen: Counter = Counter()
        for item in worked:
            seen[item.number] += 1
            key = f"У{number}.{item.number}" + ("" if seen[item.number] == 1 else f"-{seen[item.number]}")
            condition = with_stem(_prepare(item.text), lesson.get("task_stem"))
            task = task_from_block(Marker(0, 0, key), condition, path)
            task.author_solution_latex = _prepare(item.solution)
            task.author_answer_latex = _answer_field(item.answer)
            task.warnings.extend(item.warnings)
            _finish_task(task, structure, lesson, item.level or span.level)
            tasks.append(task)

        homework, lead_all, hw_problems = homework_tasks(homework_zone)
        diagnostics["structure_problems"].extend(f"урок {number}, ДЗ: {p}" for p in hw_problems)
        count = max((h.number for h in homework), default=0)
        stream = flatten_answer_stream(heal_ocr(streams.get(number, "")))
        answers, missing = split_stream(stream, count) if count else ({}, [])
        if missing:
            diagnostics["missing_answers"].append(f"Д{number}: {missing}")
        path = _lesson_path(structure, lesson, structure["homework_title"])
        stem_all = lesson.get("homework_stem")
        for item in homework:
            key = f"Д{number}.{item.number}"
            condition = _prepare(item.text)
            if stem_all:
                if _math_only(condition):
                    condition = with_stem(condition, stem_all)
            else:
                condition = with_stem(condition, None)
            task = task_from_block(Marker(0, 0, key), condition, path)
            raw = answers.get(item.number, "")
            if NO_ANSWER_TASK_RE.match(condition):
                answer, hint = "", raw
            else:
                answer, hint = split_answer_hint(raw)
            task.author_answer_latex = _answer_field(answer)
            task.author_solution_latex = _prepare(hint)
            if item.lead:
                task.warnings.append(f"Общее требование перед задачей: {item.lead[:200]}")
            _finish_task(task, structure, lesson, item.level or span.level)
            tasks.append(task)
        if lead_all and not stem_all:
            diagnostics["homework_leads"][str(number)] = lead_all[:300]
    return tasks


def _finish_task(task: TaskDraft, structure: dict, lesson: dict, level: int | None) -> None:
    task.topic_original = f"Урок {lesson['number']}. {lesson['title']}"
    task.collection_title = task.source_path[-1]
    task.grade_band_codes = list(structure["grade_bands"])
    task.tags = list(lesson.get("tags", []))
    task.topic_code = lesson_topic(lesson, task.text_latex)
    if level:
        task.source_number = f"{task.external_id} [{level}]"
    if _is_parametric(task.text_latex) and "задача с параметром" not in task.tags:
        task.tags.append("задача с параметром")


def parse_tkachuk(text: str, *, structure: dict | None = None,
                  repairs_path: Path = REPAIRS_PATH) -> tuple[list[TaskDraft], dict]:
    structure = structure or load_structure()
    text = text.replace("\r\n", "\n")
    if BOOK_MARKER not in text or "Ткачук" not in text:
        raise ValueError("Не найдена книга Ткачука «Математика — абитуриенту»")
    text, repairs = load_repairs(text, repairs_path)
    text = heal_ocr(text)
    diagnostics: dict = {
        "source_repairs_applied": repairs.patches,
        "overrides_applied": [],
        "dropped": [],
        "renumbered": [],
        "inserted": [],
        "structure_problems": [],
        "numbering": [],
        "missing_answers": [],
        "homework_leads": {},
        "sections_without_tasks": [],
        "sections_without_answers": [],
        "unused_answer_blocks": [],
    }
    tasks = parse_part2(text, structure, diagnostics)
    tasks += parse_part3(text, structure, diagnostics)
    tasks = apply_composition(tasks, repairs, diagnostics)
    for task in tasks:
        if task.external_id in repairs.tasks:
            apply_override(task, repairs.tasks[task.external_id])
            diagnostics["overrides_applied"].append(task.external_id)
        finalize_draft_images(task)
    diagnostics["unique_tasks"] = len({t.external_id for t in tasks})
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_section"] = dict(Counter(" / ".join(t.source_path[1:]) for t in tasks))
    return tasks, diagnostics


def apply_override(task: TaskDraft, override: dict) -> None:
    if "text" in override:
        task.text_latex = override["text"]
        # Условие переписано по скану целиком, с пунктами «а) б)» в тексте:
        # подпункты, нарезанные из OCR, устарели.
        if "subitems" not in override:
            task.subitems = []
    if "answer" in override:
        task.author_answer_latex = override["answer"]
    if "solution" in override:
        task.author_solution_latex = override["solution"]
    if "subitems" in override:
        task.subitems = [SubitemDraft(**item) for item in override["subitems"]]
    if "section" in override:
        move_to_section(task, override["section"])
    if "topic" in override:
        task.topic_code = override["topic"]
    if "tags" in override:
        task.tags = list(override["tags"])
    # Рисунки правки записаны путями (\includegraphics), а у полей OCR — уже
    # номерами \taskpic{N}. Если номеров не осталось, список рисунков
    # собирается заново по правке: рисунок из старого условия (чужой или
    # перенесённый в решение) не остаётся висеть у задачи.
    fields = [task.text_latex, task.author_answer_latex, task.author_solution_latex]
    fields += [value for item in task.subitems for value in vars(item).values() if isinstance(value, str)]
    if not any(NUMBERED_TASKPIC_RE.search(value or "") for value in fields):
        task.images = []


NUMBERED_TASKPIC_RE = re.compile(r"\\taskpic\{\d+\}")


# --------------------------------------------------------------------------
# Часть III: варианты вступительных экзаменов в МГУ
# --------------------------------------------------------------------------

YEAR_RE = re.compile(
    r"(?m)^(?:\\section\*\{)?(?P<year>(?:19[789]\d|20[0-2]\d)) год\.?\}?(?:\\\\)?[ \t]*$")

# Канонические коды факультетов и экзаменов по ключевым словам названия.
# Порядок важен: «отделение геофизики геологического ф-та» — ГФ, а не ГЛ.
FACULTY_KEYS = (
    ("ОЛ", r"олимпиад|первой смены|второй смены|\d-й поток"),
    ("ДВИ", r"дополнительное вступительное"),
    ("АЕГЭ", r"альтернативный\s+ЕГЭ"),
    ("ЦЭ", r"централизованный экзамен"),
    ("ДН", r"дополнительный набор"),
    ("ММ", r"механико"),
    ("ВМК", r"вычислительной"),
    ("ГФ", r"геофизик"),
    ("ФФ", r"(?<!гео)физическ"),
    ("ХФ", r"химическ"),
    ("ГЛ", r"геологи"),
    ("ФФМ", r"фундаментальной медицины"),
    ("ББИ", r"биоинженер"),
    ("БФ", r"биологи|биолого"),
    ("ПЧ", r"почвовед"),
    ("ГГ", r"географ"),
    ("ЭФ-ПЭ", r"полит\w*\.?\s+эконом"),
    ("ЭФ-ПК", r"планировани"),
    ("ЭФ-М", r"менеджмент"),
    ("ЭФ", r"экономи"),
    ("ФЛ", r"лингвист|филологич"),
    ("ПС", r"психолог"),
    ("ФС", r"философ"),
    ("ИСАА", r"азии и африки|стран а\w+ и африки|исаа"),
    ("СОЦ", r"социологич|социальных наук"),
    ("ГУ", r"государственного управления"),
    ("ВШБ", r"высшая школа бизнеса"),
    ("МШЭ", r"московская школа экономики"),
    ("ГП", r"глобальных процессов"),
    ("НМ", r"наук о материалах"),
)
_GEOLOGY_GENERAL_RE = re.compile(r"(?i)общей геологии")


def faculty_codes(title: str) -> list[str]:
    """Коды всех факультетов, названных в подписи («Химический ф-т и отд.
    геофизики геологического ф-та» → ХФ, ГФ)."""
    low = title.lower()
    codes = []
    for code, pattern in FACULTY_KEYS:
        if re.search(pattern, low, re.I):
            if code == "ГЛ" and "ГФ" in codes and not _GEOLOGY_GENERAL_RE.search(title):
                continue
            if code == "БФ" and "ББИ" in codes:
                continue
            if code == "ПЧ" and "БФ" in codes and re.search(r"(?i)отд\w*\.?\s+почвовед", title):
                codes.remove("БФ")
            if code == "БФ" and re.search(r"(?i)отд\w*\.?\s+почвовед", title) and not re.search(r"(?i)биологии", title):
                continue
            if code == "ЭФ" and any(c.startswith("ЭФ-") for c in codes):
                continue
            if code == "ЭФ" and "МШЭ" in codes:
                continue
            if code == "ФФ" and re.search(r"(?i)физическ\w*\s+культур", low):
                continue
            codes.append(code)
    # Институт стран Азии и Африки «социально-экономический», Московская
    # школа экономики — не экономический факультет.
    if "ИСАА" in codes or "МШЭ" in codes:
        codes = [c for c in codes if c != "ЭФ"]
    return codes


# Заголовок секции части III: \section* или строка-подпись без формул.
_HEADING_WORDS_RE = re.compile(
    r"(?i)факультет|отделени|олимпиад|вариант\s+\d|поток|смен[ыа]|испытани|экзамен|"
    r"дополнительный набор|институт|школа|задачи для")


@dataclass
class VariantSection:
    year: int
    title: str
    subtitle: str = ""
    items: list = field(default_factory=list)   # [(номер, текст)]
    notes: list = field(default_factory=list)
    code: str = ""


# Подпись секции без \\section: начинается с названия факультета или экзамена.
_PLAIN_HEADING_RE = re.compile(
    r"^(?:Механико|Факультет|Олимпиада|Вариант\s+\d|\d-й поток|Задачи (?:для )?(?:первой|второй)|"
    r"Дополнительн|Экзамен|Централизованн|Институт|Высшая школа|Московская школа|"
    r"[А-ЯЁ][а-яё-]+(?:ий|ый) факультет)")


def _heading_line(line: str) -> str | None:
    stripped = line.strip()
    match = re.match(r"^\\section\*\{(?P<title>.*)$", stripped)
    if match:
        return match.group("title")
    if (len(stripped) < 120 and "\\(" not in stripped and "\\item" not in stripped
            and _PLAIN_HEADING_RE.match(stripped) and not stripped.endswith((":", ","))
            and not re.match(r"(?i)^вариант был", stripped)):
        return stripped
    return None


def _clean_heading(title: str) -> str:
    title = re.sub(r"\\\\\s*", " ", title)
    title = title.replace("}", "").replace("{", "").replace("\\section*", "")
    title = re.sub(r"\s+", " ", title).strip().rstrip(".")
    title = title.replace("факупьтет", "факультет").replace('" Ломоносов"', "«Ломоносов»")
    return title


def explicit_enumerate_labels(zone: str) -> str:
    """Автонумерация OCR (``enumerate`` + ``\\setcounter``) — явными
    метками ``\\item[N.]`` списка ``itemize``."""
    out = []
    pos = 0
    stack: list[list] = []   # [вид, счётчик]
    token_re = re.compile(
        r"\\begin\{(?P<begin>enumerate|itemize)\}|\\end\{(?P<end>enumerate|itemize)\}"
        r"|\\setcounter\{enum(?P<level>i+)\}\{(?P<value>\d+)\}|\\item(?![a-zA-Z])(?P<label>\[[^\]]*\])?")
    for match in token_re.finditer(zone):
        out.append(zone[pos:match.start()])
        pos = match.end()
        if match.group("begin"):
            stack.append([match.group("begin"), 0])
            out.append("\\begin{itemize}")
        elif match.group("end"):
            if stack:
                stack.pop()
            out.append("\\end{itemize}")
        elif match.group("level"):
            enums = [entry for entry in stack if entry[0] == "enumerate"]
            if enums and len(match.group("level")) <= len(enums):
                enums[len(match.group("level")) - 1][1] = int(match.group("value"))
        else:
            if stack and stack[-1][0] == "enumerate" and match.group("label") is None:
                stack[-1][1] += 1
                out.append(f"\\item[{stack[-1][1]}.]")
            else:
                out.append(match.group(0))
    out.append(zone[pos:])
    return "".join(out)


def year_sections(year: int, zone: str) -> list[VariantSection]:
    """Секции года: заголовок факультета (+ «Вариант N» внутри него)."""
    # Многострочный \section*{…\\\n (отделение …)} → одна строка.
    zone = re.sub(r"\\section\*\{([^{}]*?)\\\\\s*\n\s*([^{}]*?)\}",
                  lambda m: "\\section*{" + m.group(1).strip() + " " + m.group(2).strip() + "}", zone)
    zone = explicit_enumerate_labels(zone)
    lines = zone.split("\n")
    blocks: list[tuple[str, list[str]]] = []
    current_title = ""
    buffer: list[str] = []
    for index, line in enumerate(lines):
        title = _heading_line(line)
        if title is not None and not re.match(r"^\s*\\item", line):
            blocks.append((current_title, buffer))
            current_title = _clean_heading(title)
            buffer = []
        elif (buffer == [] and current_title and re.match(r"^\s*\(отд", line)
              and lines[index - 1].rstrip().endswith("\\\\")):
            # «Геологический факультет\\» + «(отделение геофизики)»
            current_title = _clean_heading(current_title + " " + line)
        else:
            buffer.append(line)
    blocks.append((current_title, buffer))
    sections: list[VariantSection] = []
    parent = ""
    for title, body_lines in blocks:
        body = "\n".join(body_lines)
        if not title and not body.strip():
            continue
        variant = re.match(r"(?i)^(?:вариант\s+\d+|\d-й поток|задачи (?:для )?(?:первой|второй) смены)", title)
        if variant and parent:
            section = VariantSection(year, parent, title)
        else:
            # «Дополнительное вступительное испытание … Вариант 1» — шапка
            # испытания и первый вариант в одной строке.
            inline = re.match(r"(?i)^(?P<head>.+?)\s+(?P<variant>вариант\s+\d+)$", title)
            if inline and not re.match(r"(?i)^вариант", title):
                section = VariantSection(year, inline.group("head"), inline.group("variant").capitalize())
                parent = inline.group("head")
            else:
                section = VariantSection(year, title)
                parent = title
        for token in list_tokens(body):
            if isinstance(token, Para):
                if section.items and re.match(r"^[а-яё(\\]", token.text):
                    number, text = section.items[-1]
                    section.items[-1] = (number, text + "\n" + token.text)
                else:
                    section.notes.append(token.text)
                continue
            number, _, _, text = item_number(token)
            previous = section.items[-1][0] if section.items else 0
            if number is None or number <= previous or number > previous + 2:
                # «\\item[30] коп. Сколько стоят…» — продолжение задачи.
                if section.items:
                    n, t = section.items[-1]
                    extra = token.text if number is None else (
                        f"{token.label} {token.text}" if token.label.strip() else text)
                    section.items[-1] = (n, t + "\n" + extra)
                continue
            section.items.append((number, text))
        sections.append(section)
    # Заголовок «Вариант N» без задач у родителя: родитель — общая шапка.
    return sections


EXAM_KINDS = {"ОЛ", "ДВИ", "АЕГЭ", "ЦЭ", "ДН"}


def _section_code(section: VariantSection, used: Counter) -> str:
    codes = faculty_codes(section.title) or ["ВАР"]
    faculties = [c for c in codes if c not in EXAM_KINDS]
    code = faculties[0] if faculties else codes[0]
    if faculties and "ОЛ" in codes:
        code += "-ОЛ"
    variant = re.search(r"(?i)вариант\s+(\d+)", section.title)
    subtitle = section.subtitle
    if subtitle:
        sub = re.search(r"\d+", subtitle)
        if re.search(r"(?i)смен", subtitle):
            code += ".С1" if re.search(r"(?i)перв", subtitle) else ".С2"
        elif re.search(r"(?i)поток", subtitle):
            code += ".П" + (sub.group(0) if sub else "")
        else:
            code += ".В" + (sub.group(0) if sub else "")
    elif variant:
        code += ".В" + variant.group(1)
    if re.search(r"(?i)вечерн", section.title):
        code += "-В"
    if re.search(r"(?i)прикладной информатики", section.title):
        code += "-ПИ"
    if re.search(r"(?i)иностранных граждан", section.title):
        code += "-ИН"
    if re.search(r"(?i)бакалавр", section.title):
        code += "-Б"
    if re.search(r"(?i)специалист", section.title):
        code += "-С"
    used[code] += 1
    return code if used[code] == 1 else f"{code}{used[code]}"


# Подпись блока ответов: «Механико-математический факультет.», «Отд. общей
# геологии геологического ф-та.», «Вариант 2», «Задачи первой смены.».
ANSWER_LABEL_RE = re.compile(
    r"(?:(?<=\n)|(?<=\\\\)|(?<=[.;)]\s)|(?<=[.;)])|^)[ \t]*(?P<label>"
    r"(?:Механико|Факультет|Физико|[А-ЯЁ][а-яё-]+(?:ий|ый)\s+(?:факультет|ф-т)|Отд\.|Отделение|"
    r"Олимпиада|Экзамен|Централизованн|Дополнительн|Вариант\s+\d|Задачи\s+(?:для\s+)?(?:первой|второй)|"
    r"Институт|Высшая\s+школа|Московская\s+школа|\d-й\s+поток)"
    r"[^\\\n]{0,160}?)(?=\s*\.\s*(?:\d{1,2}\s*\.|\n|\\\\|$)|\s+\d{1,2}\s*\.\s|\s*\n|\s*\\\\|\s*$)")
LITERATURE_RE = re.compile(r"\\section\*\{Список использованной литературы\}")


@dataclass
class AnswerBlock:
    year: int
    label: str
    stream: str


def variant_answer_blocks(text: str) -> dict[int, list[AnswerBlock]]:
    start = VAR_ANSWERS_RE.search(text)
    end = LITERATURE_RE.search(text)
    if not start:
        raise ValueError("Не найден раздел «2. Ответы к вариантам»")
    zone = text[start.end():end.start() if end else len(text)]
    years = list(YEAR_RE.finditer(zone))
    result: dict[int, list[AnswerBlock]] = {}
    for i, match in enumerate(years):
        stop = years[i + 1].start() if i + 1 < len(years) else len(zone)
        year = int(match.group("year"))
        body = flatten_answer_stream(zone[match.end():stop])
        labels = [m for m in ANSWER_LABEL_RE.finditer(body)
                  if "\\(" not in m.group("label")]
        blocks = []
        for j, label in enumerate(labels):
            block_end = labels[j + 1].start() if j + 1 < len(labels) else len(body)
            stream = body[label.end():block_end]
            stream = re.sub(r"^\s*\.", " ", stream)
            blocks.append(AnswerBlock(year, _clean_heading(label.group("label")), stream))
        result[year] = blocks
    return result


def _label_matches(block: AnswerBlock, section: VariantSection) -> bool:
    label_codes = set(faculty_codes(block.label))
    section_codes = set(faculty_codes(section.title))
    variant = re.match(r"(?i)вариант\s+(\d+)", block.label)
    if variant:
        own = re.search(r"(?i)вариант\s+(\d+)", section.subtitle or section.title)
        return bool(own) and own.group(1) == variant.group(1)
    if re.match(r"(?i)задачи\s+(?:для\s+)?(?:первой|второй)", block.label):
        return bool(re.search(r"(?i)смен", section.subtitle))
    if re.match(r"(?i)\d-й\s+поток", block.label):
        return bool(re.search(r"(?i)поток", section.subtitle)) and block.label[0] == (re.search(r"\d", section.subtitle) or [""])[0]
    if not label_codes or not section_codes:
        return False
    faculties = label_codes - EXAM_KINDS
    own_faculties = section_codes - EXAM_KINDS
    if faculties and own_faculties:
        if ("ОЛ" in label_codes) != ("ОЛ" in section_codes):
            return False
        return bool(faculties & own_faculties)
    return bool(label_codes & section_codes)


def match_answer_blocks(sections: list[VariantSection], blocks: list[AnswerBlock]) -> dict[int, AnswerBlock]:
    """{индекс секции: блок ответов}. Порядок блоков — порядок секций книги,
    подпись блока сокращена («отд. геофизики геологического ф-та»)."""
    assigned: dict[int, AnswerBlock] = {}
    pointer = 0
    candidates = [i for i, section in enumerate(sections) if section.items]
    for block in blocks:
        if not re.search(r"\d|" + WILDCARD, block.stream):
            continue
        chosen = None
        ordered = [i for i in candidates if i >= pointer] + [i for i in candidates if i < pointer]
        for index in ordered:
            if index in assigned:
                continue
            if _label_matches(block, sections[index]):
                chosen = index
                break
        if chosen is None:
            continue
        assigned[chosen] = block
        pointer = chosen + 1
    return assigned


# --------------------------------------------------------------------------
# Темы задач вариантов: по содержанию условия
# --------------------------------------------------------------------------

_PLANE_RE = re.compile(r"(?i)треугольник|трапеци|окружност|четырехугольник|четырёхугольник|"
                       r"параллелограм|ромб|квадрат\s+\\\(|хорд|биссектрис|медиан|вписан|описан")
_SOLID_RE = re.compile(r"(?i)пирамид|призм|куб[аеу ]|шар|сфер|конус|цилиндр|тетраэдр|параллелепипед|"
                       r"многогранник|двугранн|плоскост")
_WORD_RE = re.compile(r"(?i)км/ч|скорост|рабоч|бригад|производител|раствор|сплав|процент|"
                      r"рубл|коп\.|стоимост|цена|поезд|автомобил|пешеход|велосипедист|лодк|"
                      r"бассейн|труб[аы]|насос|завод|изготов|магазин|ящик|станк|детал|"
                      r"изделий|комбайн|трактор|экскаватор|бак[аеу ]|автобус|катер|пароход|"
                      r"турист|самол[её]т|мотоцикл|грузовик|машин[аыу]|цех|предприяти|кг\b|литр")


def content_topic(text: str) -> str:
    """Основная тема задачи варианта по условию (в части III темы нет)."""
    kind = formula_kind(text) if _math_only(text) else (
        "ineq" if _has(text, "неравенств") else "sys" if _has(text, "систем") else "eq")
    ineq = kind in ("ineq", "sys_ineq")
    if _is_parametric(text):
        return "ALG.08.02" if ineq else "ALG.08.01"
    if _SOLID_RE.search(text) and not _has(text, "координатн"):
        return _solid_topic(text)
    if _PLANE_RE.search(text):
        if _has(text, "окружност", "хорд", "касательн", "вписан", "описан"):
            return "GEO.04"
        if _has(text, "трапеци", "параллелограм", "ромб", "четырехугольник", "четырёхугольник"):
            return "GEO.03"
        return "GEO.02"
    if _WORD_RE.search(text):
        if _has(text, "раствор", "сплав", "концентрац", "смес"):
            return "ALG.09.04"
        if _has(text, "км/ч", "скорост", "поезд", "автомобил", "пешеход", "велосипедист", "лодк"):
            return "ALG.09.02"
        if _has(text, "бригад", "производител", "рабоч", "бассейн", "насос", "труб",
                "станк", "детал", "изделий", "комбайн", "трактор", "экскаватор", "бак", "цех"):
            return "ALG.09.03"
        return "ALG.09.01"
    if _has(text, "прогресси"):
        return "ALG.06"
    if _has(text, "наибольш", "наименьш", "производн", "касательн"):
        return "ALG.07"
    if _has(text, "целых", "натуральн", "делит"):
        return "ARI.02.07"
    if re.search(r"\\(?:sin|cos|operatorname\{(?:tg|ctg)\}|tg|ctg)\b", text):
        return "ALG.04.09" if ineq else "ALG.03.10"
    if re.search(r"\\(?:log|lg|ln)\b", text):
        return "ALG.04.08" if ineq else "ALG.03.09"
    if re.search(r"\^\{[^{}]*x", text):
        return "ALG.04.07" if ineq else "ALG.03.08"
    if re.search(r"\\sqrt", text):
        return "ALG.04.06" if ineq else "ALG.03.07"
    if re.search(r"\|[^|]*x", text):
        return "ALG.04.05" if ineq else "ALG.03.06"
    if kind in ("sys", "sys_ineq") or _has(text, "систем"):
        return "ALG.03.11" if not ineq else "ALG.04"
    return "ALG.04" if ineq else "ALG.03"


# --------------------------------------------------------------------------
# Часть III целиком
# --------------------------------------------------------------------------

def parse_part3(text: str, structure: dict, diagnostics: dict) -> list[TaskDraft]:
    _, part3, answers_at = part_bounds(text)
    zone = text[part3:answers_at]
    years = list(YEAR_RE.finditer(zone))
    answer_blocks = variant_answer_blocks(text)
    tasks: list[TaskDraft] = []
    for i, match in enumerate(years):
        end = years[i + 1].start() if i + 1 < len(years) else len(zone)
        year = int(match.group("year"))
        sections = year_sections(year, zone[match.end():end])
        blocks = answer_blocks.get(year, [])
        assigned = match_answer_blocks(sections, blocks)
        used_blocks = {id(block) for block in assigned.values()}
        for block in blocks:
            if id(block) not in used_blocks and re.search(r"\d", block.stream):
                diagnostics["unused_answer_blocks"].append(f"{year}: {block.label}")
        used: Counter = Counter()
        for index, section in enumerate(sections):
            if not section.items:
                if section.title and section.notes:
                    diagnostics["sections_without_tasks"].append(
                        f"{year}: {section.title} — {section.notes[0][:120]}")
                continue
            code = _section_code(section, used)
            section.code = code
            block = assigned.get(index)
            if block is None:
                diagnostics["sections_without_answers"].append(f"{year}.{code} {section.title}")
                pieces, missing = {}, []
            else:
                # Номер задачи может пропускаться (OCR слил задачу с соседней):
                # ответы — по наибольшему номеру, иначе последний остаётся без ответа.
                pieces, missing = split_stream(block.stream, max(n for n, _ in section.items))
            numbers = [n for n, _ in section.items]
            gaps = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
            if gaps:
                diagnostics["numbering"].append(f"{year}.{code}: нет задач {gaps}")
            if missing and block is not None:
                diagnostics["missing_answers"].append(f"{year}.{code}: {missing}")
            title = section.title + (f". {section.subtitle}" if section.subtitle else "")
            path = [structure["part3_title"], f"{year} год", title]
            for number, body in section.items:
                key = f"{year}.{code}.{number}"
                condition = _prepare(body)
                task = task_from_block(Marker(0, 0, key), condition, path)
                answer, hint = split_answer_hint(pieces.get(number, ""))
                if NO_ANSWER_TASK_RE.match(condition):
                    answer, hint = "", (answer + " " + hint).strip()
                task.author_answer_latex = _answer_field(answer)
                task.author_solution_latex = _prepare(hint)
                task.topic_original = f"{year} год. {title}"
                task.collection_title = title
                task.grade_band_codes = list(structure["grade_bands"])
                task.topic_code = content_topic(task.text_latex)
                task.tags = []
                if "ОЛ" in faculty_codes(section.title) or re.search(r"(?i)олимпиад", title):
                    task.tags.append("Олимпиада")
                if _is_parametric(task.text_latex):
                    task.tags.append("задача с параметром")
                tasks.append(task)
    return tasks

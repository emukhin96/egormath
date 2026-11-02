"""Профиль учебников Волчкевича «Геометрия. Математическая вертикаль».

М. А. Волчкевич, 7, 8 и 9 классы, OCR Mathpix. Издание определяется по
sha256 исходного TEX (таблица ``data/volchkevich_structure.json``): главы,
параграфы и их начало в TEX — уникальный фрагмент (``anchor``) или страница
PDF (``page``: граница — первый рисунок этой страницы или дальше; имена
рисунков Mathpix содержат номер страницы).

Внутри параграфа три вида задач, у каждого своя нумерация:

- «Упражнения» по ходу теории — ключ ``§.УN``;
- «Примеры решения задач» («ПРИМЕР N», в 7 классе «ПРИМЕР 1.2») —
  ключ ``§.ПN``, разбор книги — авторское решение, «Ответ:» — ответ;
- «Задачи» / «Решите задачи» — ключ ``§.N`` (в 7 классе книга так и
  нумерует: «1.12»); задачи раздела «Для тех, кто хочет знать больше»
  продолжают нумерацию параграфа.

«Вопросы» на повторение в импорт не входят. Ответов к задачам в книге нет.
Звёзды уровня (★☆☆ … ★★★) OCR не различает — уровень не переносится.

Рисунки: в 7 классе «Рис. 1.34» со сквозной по параграфу нумерацией, в 8 и
9 классах «Рис. N» заново в каждом параграфе и подписи «» задача N» у
рисунков задач (ссылка в условии — «(» рис.)»). Подписи без номера и
рисунки без подписи (заставки, значки рубрик) в задачи не попадают.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .potoskuev_parser import (
    _finish_fields, apply_source_repairs, distribute_labeled_answer,
    lift_common_tail, prepare_text)
from .textbook_parser import (
    Marker, TaskDraft, clean, finalize_draft_images, remove_group_commands,
    task_from_block)


DATA_DIR = Path(__file__).with_name("data")
STRUCTURE_PATH = DATA_DIR / "volchkevich_structure.json"
REPAIRS_PATH = DATA_DIR / "volchkevich_repairs.json"

KIND_EXERCISE = "exercise"
KIND_EXAMPLE = "example"
KIND_TASK = "task"
KIND_TITLES = {
    KIND_EXERCISE: "Упражнения",
    KIND_EXAMPLE: "Примеры решения задач",
    KIND_TASK: "Задачи",
}
KIND_PREFIX = {KIND_EXERCISE: "У", KIND_EXAMPLE: "П", KIND_TASK: ""}

FIGURE_RE = re.compile(
    r"\\begin\{figure\}.*?\\end\{figure\}(?:\s*\n[ \t]*Рис\.\s*(?P<after>\d{1,2}(?:\.\d{1,3})?)[ \t]*(?=\n))?",
    re.S)
GRAPHICS_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{(?P<path>[^{}\s\\]+)\}")
BARE_GRAPHICS_RE = re.compile(
    r"(?:\\begin\{center\}\s*)?\\includegraphics\s*(?:\[[^\]]*\])?\s*\{[^{}\s\\]+\}"
    r"(?:\s*\\end\{center\})?")
CAPTION_RE = re.compile(r"\\caption\{(?P<text>[^{}]*)\}")
# «Рис. 36\\ Описание» — номер и пояснение под рисунком.
FIG_CAPTION_RE = re.compile(r"^\s*Рис\.?\s*(?P<num>\d{1,2}(?:\.\d{1,3})?)\s*(?:$|\\\\)")
TASK_CAPTION_RE = re.compile(
    r"задач[аи]\s*(?P<num>\d{1,3})(?:\s*(?:,|и)\s*(?P<more>\d{1,3}))?\s*$")
PAGE_RE = re.compile(r"-(?P<page>\d{3})_\d+_\d+_\d+_\d+\}")
# «(рис. 1.34)», «рисунке 1.28, а», «на рисунках 1.58-1.60», «рис. 17».
FIG_REF_RE = re.compile(
    r"(?P<word>[Рр]ис(?:ун(?:ок|ке|ка|ки|ках|кам|ком|ками))?\.?)\s*"
    r"(?P<first>\d{1,2}(?:\.\d{1,3})?)"
    r"(?:\s*[-–—]\s*(?P<last>\d{1,2}(?:\.\d{1,3})?))?(?![\d])")
# «(» рис.)» — ссылка на рисунок задачи с подписью «» задача N».
TASK_FIG_REF_RE = re.compile(
    r"\(\s*['\"‘’]?\s*(?:»|>>|►|▸|\\gg|\\triangleright)?\s*рис\.?\s*\)")

HEADING_RE = re.compile(r"\\section\*?\{(?P<title>(?:[^{}]|\{[^{}]*\})*)\}")
BARE_HEADING_RE = re.compile(
    r"(?m)^[ \t]*(?:\?[ \t]*)?(?P<title>УПРАЖНЕНИЯ|УПРАЖНЕНИЕ|ВОПРОСЫ|ЗАДАЧИ|РЕШИТЕ ЗАДАЧИ"
    r"|ПРИМЕРЫ РЕШЕНИЯ ЗАДАЧ|ДАВАЙТЕ РАЗБЕР[ЕЁ]М НЕСКОЛЬКО ПРИМЕРОВ"
    r"|ДЛЯ ТЕХ, КТО ХОЧЕТ ЗНАТЬ БОЛЬШЕ)[ \t]*(?:\\\\)?[ \t]*$")
EXAMPLE_RE = re.compile(
    r"(?m)^[ \t]*(?:\\item\[\][ \t]*)?(?:[★☆*][ \t]*){0,3}(?:ПРИМЕР|[Пп]ример)[ \t]+"
    r"(?P<label>\d{1,2}(?:\.\d{1,2})?)\.?")
ITEM_RE = re.compile(r"\\item\[(?P<label>\d{1,2}(?:\.\d{1,2})?|\+)\.?\]")
# 7 класс: задачи «1.18 ★★★ …» строкой без \item.
PLAIN_TASK_RE = re.compile(
    r"(?m)^[ \t]*(?P<label>\d{1,2}\.\d{1,2})\.?[ \t]+(?=[★☆*]|[А-ЯЁA-Z(\\])")
# 8–9 классы: «13. ★★ …» строкой без \item.
PLAIN_STAR_RE = re.compile(r"(?m)^[ \t]*(?P<label>\d{1,2})\.[ \t]+(?=[★☆*])")
# 8–9 классы: «13. На рисунке …» строкой без \item (OCR потерял список).
PLAIN_NUMBER_RE = re.compile(r"(?m)^[ \t]*(?P<label>\d{1,2})\.[ \t]+(?=[А-ЯЁ])")
# 7 класс: упражнение «1 Посмотрите …» строкой без \item.
PLAIN_EXERCISE_RE = re.compile(r"(?m)^[ \t]*(?P<label>\d{1,2})[ \t]+(?=[А-ЯЁ])")

SOLUTION_SPLIT_RE = re.compile(
    r"(?:\\section\*?\{\s*(?:РЕШЕНИЕ|ДОКАЗАТЕЛЬСТВО|ПЕРВЫЙ СПОСОБ)[^{}]*\}"
    r"|(?:(?<=\n)|(?<=[.?!)]\s)|(?<=\\\\\s))[ \t]*(?:РЕШЕНИЕ|ДОКАЗАТЕЛЬСТВО|Решение|Доказательство)\s*[:.]"
    r"|(?m:^[ \t]*(?:РЕШЕНИЕ|ДОКАЗАТЕЛЬСТВО)[ \t]*(?:\\\\)?[ \t]*$))")
ANSWER_WORD_RE = re.compile(
    r"(?m)^(?P<lead>[ \t]*)(?:Ответ|ОТВЕТ|OTBET|OmBem|Ombem|OmBеm|Omвem|Отвeт|Oтвет|ОmВеm|Om6em)[ \t]*:")
EXAMPLE_ANSWER_RE = re.compile(r"(?m)^[ \t]*Ответ\s*:\s*(?P<answer>[^\n]+)")
EXAMPLE_END_RE = re.compile(
    r"(?m)^[ \t]*(?:Ответ\s*:[^\n]*|[^\n]*Что и требовалось доказать\.?)[ \t]*(?:\\\\)?[ \t]*$")
# Звёзды уровня и след полой звезды OCR («★ Д», «★ 山», «0 Две …»).
LEAD_STARS_RE = re.compile(
    r"^\s*(?P<stars>(?:[★☆*]\s*){1,3})(?:(?:[Д山એ0О○◯]|\(\))\s+(?=[А-ЯЁA-Z\\]))?")
LIST_START_RE = re.compile(r"\\begin\{itemize\}\s*$")
FOOTNOTE_RE = re.compile(r"\\footnotetext\{")
STARRED_RE = re.compile(r"\s*[★☆]")
LEAD_JUNK_RE = re.compile(r"^\s*(?:[山એ0○◯]|\(\))\s+(?=[А-ЯЁA-Z\\])")


@dataclass
class Paragraph:
    key: str
    number: int | None
    title: str
    chapter_number: int
    chapter_title: str
    topic: str
    start: int = 0
    end: int = 0

    @property
    def heading(self) -> str:
        return f"§ {self.number}. {self.title}" if self.number else self.title

    @property
    def chapter_heading(self) -> str:
        if self.chapter_number:
            return f"Глава {self.chapter_number}. {self.chapter_title}"
        return ""


@dataclass
class Event:
    start: int
    end: int
    kind: str          # heading, example, item
    value: str = ""    # класс заголовка или метка
    plain: bool = False


@dataclass
class Item:
    kind: str
    number: int
    start: int
    end: int
    label: str
    body: str = ""
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Издание и параграфы
# --------------------------------------------------------------------------

def load_edition(text: str, path: Path = STRUCTURE_PATH) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for edition in spec["editions"]:
        if edition["source_sha256"] == digest:
            return edition
    raise ValueError(
        "Неизвестное издание Волчкевича: sha256 TEX не совпадает со сверенными "
        "(7, 8, 9 классы, см. docs/VOLCHKEVICH_IMPORT.md)")


def apply_skips(text: str, edition: dict) -> tuple[str, list[str]]:
    """Вырезает задвоенные OCR страницы по уникальным границам."""
    applied = []
    for skip in edition.get("skips", edition.get("skip", [])):
        if text.count(skip["start"]) != 1:
            raise ValueError(f"Граница пропуска «{skip['start'][:40]}» не уникальна")
        start = text.index(skip["start"])
        end = text.find(skip["end"], start + 1)
        if end < 0:
            raise ValueError(f"Не найден конец пропуска «{skip['end'][:40]}»")
        text = text[:start] + "\n" + text[end:]
        applied.append(skip.get("note", skip["start"][:40]))
    return text, applied


def paragraphs(text: str, edition: dict) -> list[Paragraph]:
    """Параграфы издания с границами в тексте."""
    images = [(m.start(), int(m.group("page"))) for m in PAGE_RE.finditer(text)]
    result = []
    for chapter in edition["chapters"]:
        for spec in chapter["paragraphs"]:
            number = spec.get("number")
            if "anchor" in spec:
                count = text.count(spec["anchor"])
                if count != 1:
                    raise ValueError(
                        f"Начало § {number or spec.get('key')} встречается {count} раз")
                start = text.index(spec["anchor"])
            else:
                start = next((pos for pos, page in images if page >= spec["page"]), None)
                if start is None:
                    raise ValueError(f"Нет рисунков со страницы {spec['page']}")
                # Текст страницы до её первого рисунка остаётся в прошлом
                # параграфе: на титульной странице параграфа задач нет, а хвост
                # прошлой страницы после её последнего рисунка — ещё прошлый §.
                env = text.rfind("\\begin{figure}", 0, start)
                if env >= 0 and start - env < 300:
                    start = env
                else:
                    start = text.rfind("\n", 0, start) + 1
            result.append(Paragraph(
                key=spec.get("key") or str(number),
                number=number,
                title=spec["title"],
                chapter_number=chapter["number"],
                chapter_title=chapter["title"],
                topic=spec.get("topic", ""),
                start=start,
            ))
    result.sort(key=lambda p: p.start)
    stop = len(text)
    if edition.get("end") and edition["end"] in text:
        stop = text.index(edition["end"])
    for index, paragraph in enumerate(result):
        paragraph.end = result[index + 1].start if index + 1 < len(result) else stop
    return result


# --------------------------------------------------------------------------
# Рисунки и колонтитулы
# --------------------------------------------------------------------------

@dataclass
class Figures:
    by_number: dict[str, list[str]] = field(default_factory=dict)
    by_task: dict[int, list[str]] = field(default_factory=dict)
    dropped: int = 0


def extract_figures(zone: str, figures: Figures) -> str:
    """Подписанные рисунки уходят в индекс, остальные — из текста."""
    def replace(match: re.Match) -> str:
        block = match.group(0)
        paths = [m.group("path") for m in GRAPHICS_RE.finditer(block)]
        captions = [m.group("text").strip() for m in CAPTION_RE.finditer(block)]
        if match.group("after"):
            captions.append(f"Рис. {match.group('after')}")
        if not paths:
            return "\n"
        for caption in captions:
            fig = FIG_CAPTION_RE.match(caption)
            if fig:
                figures.by_number.setdefault(fig.group("num"), []).extend(paths)
                return "\n"
            task = TASK_CAPTION_RE.search(caption)
            if task:
                for number in (task.group("num"), task.group("more")):
                    if number:
                        figures.by_task.setdefault(int(number), []).extend(paths)
                return "\n"
        figures.dropped += len(paths)
        return "\n"

    zone = FIGURE_RE.sub(replace, zone)
    # Подпись без рисунка (рисунок OCR потерял) и картинки вне figure —
    # заставки и значки рубрик.
    zone = re.sub(r"\\captionsetup\{[^{}]*\}\s*", "", zone)
    zone = re.sub(r"\\caption\{[^{}]*\}", "", zone)

    def bare(match: re.Match) -> str:
        figures.dropped += 1
        return "\n"
    return BARE_GRAPHICS_RE.sub(bare, zone)


def derived_figure(repair: dict) -> str:
    """Имя вырезанного рисунка: ``<файл>-2of3``, ``<файл>-1-3of4`` (части
    полосы слева направо), ``<файл>-box0_0_1120_670`` (прямоугольник:
    рисунки друг над другом) или ``scan-043-…`` (прямоугольник страницы
    скана); без части — сам файл."""
    if repair.get("pdf_page"):
        # Рисунок, которого нет среди картинок Mathpix: вырезан из скана
        # (страница PDF при 150 dpi).
        return f"scan-{int(repair['pdf_page']):03d}-" + "_".join(
            str(int(v)) for v in repair["pdf_box"])
    if repair.get("box"):
        return f"{repair['file']}-box" + "_".join(str(int(v)) for v in repair["box"])
    if repair.get("part"):
        return f"{repair['file']}-{repair['part']}of{repair['of']}"
    return repair["file"]


def load_figure_repairs(text: str, path: Path = REPAIRS_PATH) -> list[dict]:
    """Сверенные со сканом рисунки (``figures``) для этого TEX."""
    if not path.exists():
        return []
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spec = json.loads(path.read_text(encoding="utf-8"))
    for edition in spec.get("editions", []):
        if edition.get("source_sha256") == digest:
            return list(edition.get("figures", []))
    return []


def apply_figure_repairs(paragraph: Paragraph, figures: Figures,
                         repairs: list[dict], grade: int) -> None:
    """Подменяет рисунки задачи или «Рис. N» сверенными частями полос.

    Mathpix склеивает соседние рисунки в одну полосу с одной подписью; часть
    полосы режет ``tools/volchkevich_images.py`` по белым столбцам.
    """
    by_task: dict[int, list[str]] = {}
    by_number: dict[str, list[str]] = {}
    for repair in repairs:
        name = derived_figure(repair)
        if "task" in repair and repair.get("paragraph") == paragraph.key:
            by_task.setdefault(int(repair["task"]), []).append(name)
        elif "figure" in repair and (
                repair.get("paragraph") == paragraph.key
                or (grade == 7 and str(repair["figure"]).split(".")[0] == paragraph.key)):
            by_number.setdefault(str(repair["figure"]), []).append(name)
    figures.by_task.update(by_task)
    figures.by_number.update(by_number)


def running_headers(edition: dict) -> re.Pattern:
    """Колонтитулы «§5. Теоремы Чевы и Менелая», «Глава 2. Подобие»."""
    parts = []
    for chapter in edition["chapters"]:
        if chapter["number"]:
            title = r"\s+".join(re.escape(w) for w in chapter["title"].split())
            parts.append(rf"Глава\s*{chapter['number']}\.?\s*{title}")
            parts.append(rf"ГЛАВА\s*{chapter['number']}(?!\d)")
        for spec in chapter["paragraphs"]:
            if spec.get("number"):
                words = spec["title"].replace("́", "").split()
                title = r"\s+".join(re.escape(w) for w in words)
                parts.append(rf"§\s?{spec['number']}\.?\s+{title}")
    return re.compile(r"(?:\\item\[\][ \t]*)?(?:" + "|".join(parts) + r")[ \t]*(?:\\\\)?",
                      re.I)


def strip_running_headers(zone: str, pattern: re.Pattern) -> str:
    def replace(match: re.Match) -> str:
        # Заголовок раздела «\section*{§1 …}» — не колонтитул, но в задачи
        # он не попадает: граница параграфа уже найдена.
        return " "
    zone = pattern.sub(replace, zone.replace("́", ""))
    zone = re.sub(r"\\section\*?\{\s*\}", "", zone)
    # Номера страниц отдельной строкой.
    return re.sub(r"(?m)^[ \t]*\d{1,3}[ \t]*$", "", zone)


# --------------------------------------------------------------------------
# События внутри параграфа
# --------------------------------------------------------------------------

def heading_class(title: str) -> str:
    plain = re.sub(r"[^А-ЯЁA-Z ]", "", clean(title).upper().replace("\\\\", " "))
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain or plain.startswith("ВОПРОС"):
        return "questions"
    if plain.startswith("УПРАЖНЕН"):
        return "exercises"
    if "ПРИМЕР" in plain:
        return "examples"
    if plain.startswith(("РЕШЕНИ", "ДОКАЗАТЕЛЬСТВ")) or "СПОСОБ" in plain:
        return "solution"
    if re.search(r"(?:^|\s)ЗАДАЧИ$", plain):
        return "tasks"
    return "theory"


_ENUM_TOKEN_RE = re.compile(
    r"\\begin\{enumerate\}|\\end\{enumerate\}|\\setcounter\{enumi\}\{(?P<value>\d+)\}"
    r"|\\item(?![a-zA-Z\[])")


def number_enumerates(zone: str) -> str:
    """«\\setcounter{enumi}{4} \\item …» → «\\item[5.] …».

    OCR рвёт нумерованный список упражнений на куски со счётчиком; без
    номера пятое упражнение слилось бы с четвёртым. Списки без счётчика
    (пункты внутри решения) не трогаются.
    """
    out = []
    pos = 0
    stack: list[list] = []
    for match in _ENUM_TOKEN_RE.finditer(zone):
        token = match.group(0)
        if token.startswith("\\begin"):
            # Список сразу под «УПРАЖНЕНИЕ»: номер — следующий по порядку,
            # его поставит разбор (``\\item[+]``).
            after_heading = re.search(
                r"\\section\*?\{\s*УПРАЖНЕНИ[ЕЯ]\s*\}\s*$", zone[max(0, match.start() - 60):match.start()])
            stack.append([0, False, bool(after_heading)])
            continue
        if token.startswith("\\end"):
            if stack:
                stack.pop()
            continue
        if not stack or len(stack) > 1:
            continue
        if match.group("value"):
            stack[-1] = [int(match.group("value")), True, False]
            continue
        if stack[-1][2]:
            out.append(zone[pos:match.start()])
            out.append("\\item[+]")
            pos = match.end()
        elif stack[-1][1]:
            stack[-1][0] += 1
            out.append(zone[pos:match.start()])
            out.append(f"\\item[{stack[-1][0]}.]")
            pos = match.end()
    out.append(zone[pos:])
    return "".join(out)


def scan_events(zone: str, grade: int) -> list[Event]:
    events = []
    for match in HEADING_RE.finditer(zone):
        events.append(Event(match.start(), match.end(), "heading",
                            heading_class(match.group("title"))))
    for match in BARE_HEADING_RE.finditer(zone):
        events.append(Event(match.start(), match.end(), "heading",
                            heading_class(match.group("title"))))
    for match in EXAMPLE_RE.finditer(zone):
        events.append(Event(match.start(), match.end(), "example", match.group("label")))
    for match in ITEM_RE.finditer(zone):
        events.append(Event(match.start(), match.end(), "item", match.group("label")))
    plain = [PLAIN_STAR_RE, PLAIN_NUMBER_RE]
    if grade == 7:
        plain = [PLAIN_TASK_RE, PLAIN_EXERCISE_RE]
    for regex in plain:
        for match in regex.finditer(zone):
            events.append(Event(match.start(), match.end(), "item",
                                match.group("label"), plain=True))
    events.sort(key=lambda e: (e.start, e.kind != "heading"))
    deduped = []
    for event in events:
        if deduped and event.start < deduped[-1].end:
            continue
        deduped.append(event)
    return deduped


def classify_items(zone: str, events: list[Event], paragraph: Paragraph, grade: int,
                   diagnostics: dict) -> list[tuple[Event, Item | None]]:
    """Решает, какие номера — упражнения, задачи, примеры, а какие — нет."""
    mode = "theory"
    last = {KIND_EXERCISE: 0, KIND_TASK: 0, KIND_EXAMPLE: 0}
    last_list = None
    result: list[tuple[Event, Item | None]] = []

    def accept(kind: str, number: int) -> bool:
        previous = last[kind]
        return previous < number <= previous + 6

    def next_item(index: int) -> str:
        return next((e.value for e in events[index + 1:] if e.kind == "item"), "")

    for index, event in enumerate(events):
        if event.kind == "heading":
            if event.value == "solution" and mode == "example":
                continue
            mode = {"tasks": "tasks", "exercises": "exercises",
                    "questions": "questions", "examples": "examples"}.get(event.value, "theory")
            result.append((event, None))
            continue
        if event.kind == "example":
            number = int(event.value.split(".")[-1])
            if "." in event.value and event.value.split(".")[0] != paragraph.key:
                continue
            if not accept(KIND_EXAMPLE, number):
                diagnostics["rejected_numbers"].append(f"{paragraph.key}: ПРИМЕР {event.value}")
                continue
            last[KIND_EXAMPLE] = number
            mode = "example"
            result.append((event, Item(KIND_EXAMPLE, number, event.start, event.end, event.value)))
            continue
        label = event.value
        starred = bool(STARRED_RE.match(zone[event.end:event.end + 12]))
        if "." in label:
            # 7 класс: «1.12» — задача § 1; чужой параграф — ссылка.
            head, tail = label.split(".")
            if head != paragraph.key or mode == "questions":
                continue
            kind, number = KIND_TASK, int(tail)
        else:
            # «+» — пункт без номера в списке под «УПРАЖНЕНИЕ».
            number = last[KIND_EXERCISE] + 1 if label == "+" else int(label)
            if label == "+":
                mode = "exercises"
            if starred:
                # Звёзды уровня — только у задач: заголовок «ЗАДАЧИ» OCR
                # нередко теряет, и список идёт сразу за примерами.
                kind = KIND_TASK
            elif mode == "tasks":
                kind = KIND_TASK
            elif mode == "exercises":
                kind = KIND_EXERCISE
            elif mode == "questions":
                if not event.plain:
                    result.append((event, None))
                continue
            elif (mode == "example" and number == last[KIND_EXERCISE] + 1
                  and LIST_START_RE.search(zone[max(0, event.start - 40):event.start])):
                # Упражнения после примера посреди теории (9 класс): новый
                # список со следующим номером.
                kind = KIND_EXERCISE
            elif mode == "example":
                # Нумерованный список внутри разбора примера.
                continue
            elif last_list and number == last[last_list] + 1 and not event.plain:
                # Продолжение списка после ложного заголовка OCR.
                kind = last_list
            elif (mode == "theory" and paragraph.number and grade != 7
                  and number == last[KIND_EXERCISE] + 1 and not event.plain):
                # 7 класс заголовки упражнений сохранил, а нумерованные
                # списки в теории (аксиомы, свойства) там — не упражнения.
                # Упражнения по ходу теории, чей заголовок OCR потерял.
                kind = KIND_EXERCISE
            else:
                if not event.plain:
                    result.append((event, None))
                continue
            if starred:
                mode = "tasks"
            if (kind == KIND_EXERCISE and number == 1 and last[KIND_EXERCISE] >= 2
                    and next_item(index) == "2"):
                # Нумерация с 1 после упражнений — «Вопросы», чей заголовок
                # OCR потерял: в импорт не идут, но обрывают упражнение.
                mode = "questions"
                result.append((event, None))
                continue
            if grade == 7 and kind == KIND_TASK and event.plain:
                continue
            if event.plain and grade == 7 and kind == KIND_EXERCISE and mode != "exercises":
                continue
        if event.plain and not starred and number != last[kind] + 1:
            # Номер строкой без \item — только следующий по порядку: иначе
            # это нумерованный список внутри условия или теории.
            continue
        if not accept(kind, number):
            diagnostics["rejected_numbers"].append(f"{paragraph.key}: {KIND_TITLES[kind]} {label}")
            if not event.plain:
                result.append((event, None))
            continue
        last[kind] = number
        last_list = kind
        if kind == KIND_EXERCISE and mode == "example":
            mode = "exercises"
        result.append((event, Item(kind, number, event.start, event.end, label)))
    return result


def cut_bodies(zone: str, classified: list[tuple[Event, Item | None]]) -> list[Item]:
    items = []
    for index, (event, item) in enumerate(classified):
        if item is None:
            continue
        stop = len(zone)
        for next_event, next_item in classified[index + 1:]:
            if item.kind == KIND_EXAMPLE and next_event.kind == "heading" \
                    and next_event.value in ("solution", "theory"):
                # «ЛЕММА», «РЕШЕНИЕ» внутри разбора; хвост теории после
                # «Ответ:» отрежет split_example.
                continue
            stop = next_event.start
            break
        body = zone[item.end:stop]
        if item.kind != KIND_EXAMPLE:
            body = cut_at_list_end(body)
        if item.kind == KIND_EXERCISE:
            body = cut_at_paragraph_end(body)
        item.body = body
        items.append(item)
    return items


_NEXT_PART_RE = re.compile(
    r"\s*(?:\\item|\\begin\{(?:itemize|enumerate)\}|\\\[|[а-и]\)|\(?[а-и]\)|[a-z]\)\s)")


def cut_at_paragraph_end(body: str) -> str:
    """Упражнение — один абзац (с пунктами «а) б)»): дальше теория.

    Упражнения стоят посреди текста параграфа, и список OCR закрывает не
    всегда. Пустая строка перед пунктом, формулой или следующим списком —
    не конец упражнения.
    """
    text = body.lstrip()
    lead = len(body) - len(text)
    for match in re.finditer(r"\n[ \t]*\n", text):
        rest = text[match.end():]
        if not rest.strip():
            break
        if _NEXT_PART_RE.match(rest):
            continue
        if not re.search(r"[.?!:)»]\s*(?:\\\\)?\s*$", text[:match.start()]):
            continue
        return body[:lead + match.start()]
    return body


_LIST_EDGE_RE = re.compile(r"\\(?P<edge>begin|end)\{(?:itemize|enumerate)\}")


def cut_at_list_end(body: str) -> str:
    """Пункт кончается вместе со своим списком.

    После ``\\end{itemize}`` идёт теория или подписи — не условие. Исключение —
    перенос на другую колонку или страницу: следующий список начинается с
    пункта без номера (``\\item[]``) или фраза оборвана на полуслове.
    """
    depth = 0
    pos = 0
    while True:
        match = _LIST_EDGE_RE.search(body, pos)
        if not match:
            return body
        pos = match.end()
        if match.group("edge") == "begin":
            depth += 1
            continue
        if depth:
            depth -= 1
            continue
        before = body[:match.start()].rstrip()
        rest = body[match.end():]
        lead = re.sub(r"^(?:\s|\\footnotetext\{.*?\n\}|\\section\*?\{[^{}]*\})*", "", rest, flags=re.S)
        if re.match(r"\\begin\{(?:itemize|enumerate)\}\s*\\item\[\]", lead):
            # Продолжение пункта: ``\\item[]`` открывает следующий список.
            start = body.index("\\item[]", match.end())
            body = before + "\n" + body[start + len("\\item[]"):]
            pos = len(before)
            continue
        if re.search(r"[-,а-яё]$", before) and re.match(r"[а-яё]", lead):
            body = before + "\n" + lead
            pos = len(before)
            continue
        return before


# --------------------------------------------------------------------------
# Черновики
# --------------------------------------------------------------------------

def strip_lead(body: str) -> str:
    body = body.lstrip()
    match = LEAD_STARS_RE.match(body)
    if match:
        return body[match.end():].lstrip()
    return LEAD_JUNK_RE.sub("", body, count=1).lstrip()


_LATIN_LABEL = {"a": "а", "b": "б", "B": "в", "e": "е"}


def clean_body(body: str) -> str:
    body = remove_group_commands(body, FOOTNOTE_RE)
    # «Рис. 6.18» строкой — подпись рисунка, оставшаяся без figure.
    body = re.sub(r"(?m)^[ \t]*Рис\.\s*\d{1,2}(?:\.\d{1,3})?[ \t]*(?:\\\\)?[ \t]*$", "", body)
    body = re.sub(r"\\setcounter\{[^{}]*\}\{\d+\}", "", body)
    # Звёзды уровня у вопросов внутри задачи («★★ Найдите …») и след полой
    # звезды OCR.
    body = re.sub(r"(?m)(^|\\item\[\]|\\\\)[ \t]*(?:[★☆][ \t]*)+(?:[Д山એ][ \t]+)?", r"\1", body)
    body = re.sub(r"[ \t]*(?:[★☆][ \t]*)+", " ", body)
    # «\(a\) ) большой комнаты» — метка пункта ушла в формулу.
    body = re.sub(r"\\\(\s*([abBe])\s*\\\)\s*\)", lambda m: _LATIN_LABEL[m.group(1)] + ")", body)
    # «\left(\mathrm{~m}^{2}\right)» — скобки вокруг единицы: иначе
    # нормализация единиц разорвёт \left и \right по разным формулам.
    body = re.sub(r"\\left\(\s*(\\mathrm\{[^{}]*\}(?:\^\{?\d\}?)?)\s*\\right\)", r"(\1)", body)
    body = ANSWER_WORD_RE.sub(r"\g<lead>Ответ:", body)
    body = HEADING_RE.sub(lambda m: "\n" + clean(m.group("title")) + "\n", body)
    body = re.sub(r"\\(?:begin|end)\{(?:center|figure)\}", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def split_example(body: str) -> tuple[str, str, str]:
    """Условие, решение примера и длина отрезанного хвоста теории."""
    match = SOLUTION_SPLIT_RE.search(body)
    if match:
        condition = body[:match.start()].rstrip()
        solution = body[match.end():]
    elif EXAMPLE_END_RE.search(body) and "\n" in body.strip():
        # Заголовок «РЕШЕНИЕ» OCR потерял: условие примера — первый абзац.
        head, _, solution = body.strip().partition("\n")
        condition = head.rstrip()
    else:
        return body, "", ""
    solution = re.sub(r"^\s*(?:\\\\)?\s*", "", solution)
    # Разбор кончается первым «Ответ:», а без ответа — первым «Что и
    # требовалось доказать»: дальше в 8–9 классах идёт теория параграфа.
    end = EXAMPLE_ANSWER_RE.search(solution) or EXAMPLE_END_RE.search(solution)
    trimmed = ""
    if end:
        trimmed = solution[end.end():].strip()
        solution = solution[:end.end()]
    return condition, solution.strip(), trimmed


def attach_figures(task: TaskDraft, item: Item, figures: Figures,
                   global_index: dict[str, list[str]] | None) -> list[str]:
    """«рис. 17» → рисунок параграфа, «(» рис.)» → рисунок «задача N»."""
    index = global_index if global_index is not None else figures.by_number
    missing: list[str] = []
    placed: set[str] = set()

    def tokens(paths: list[str]) -> str:
        out = []
        for path in paths:
            if path not in placed:
                placed.add(path)
                out.append(rf"\taskpic{{{path}}}")
        return " ".join(out)

    def numbers(first: str, last: str | None) -> list[str]:
        if not last:
            return [first]
        if "." in first:
            head, a = first.split(".")
            b = last.split(".")[-1]
            if last.count(".") and last.split(".")[0] != head:
                return [first, last]
        else:
            head, a, b = "", first, last
        if not (a.isdigit() and b.isdigit()) or not 0 <= int(b) - int(a) <= 12:
            return [first, last]
        return [f"{head}.{n}" if head else str(n) for n in range(int(a), int(b) + 1)]

    def rewrite(value: str) -> str:
        def replace(match: re.Match) -> str:
            found = []
            for number in numbers(match.group("first"), match.group("last")):
                paths = index.get(number)
                if paths:
                    found.extend(paths)
                else:
                    missing.append(number)
            text = tokens(found)
            return match.group(0) + (" " + text if text else "")
        return FIG_REF_RE.sub(replace, value or "")

    own = figures.by_task.get(item.number, []) if item.kind == KIND_TASK else []

    def own_ref(value: str) -> str:
        def replace(match: re.Match) -> str:
            text = tokens(own)
            return "(рис.)" + (" " + text if text else "")
        return TASK_FIG_REF_RE.sub(replace, value or "")

    for attr in ("text_latex", "author_solution_latex", "author_answer_latex"):
        setattr(task, attr, rewrite(own_ref(getattr(task, attr))))
    for sub in task.subitems:
        sub.text_latex = rewrite(own_ref(sub.text_latex))
    rest = [path for path in own if path not in placed]
    if rest:
        task.text_latex = task.text_latex.rstrip() + "\n" + tokens(rest)
    if item.kind == KIND_TASK and TASK_FIG_REF_RE.search(" ".join(
            [task.text_latex] + [s.text_latex for s in task.subitems])) and not own:
        missing.append(f"задача {item.number}")
    return missing


def build_draft(item: Item, paragraph: Paragraph, diagnostics: dict) -> TaskDraft:
    external_id = f"{paragraph.key}.{KIND_PREFIX[item.kind]}{item.number}"
    path = [p for p in (paragraph.chapter_heading, paragraph.heading,
                        KIND_TITLES[item.kind]) if p]
    body = clean_body(item.body)
    solution = ""
    if item.kind == KIND_EXAMPLE:
        body, solution, trimmed = split_example(body)
        if len(trimmed) > 200:
            # Хвост после «Ответ:» — обычно теория; начало — для сверки.
            diagnostics["examples_trimmed_tail"].append(
                f"{external_id}: {len(trimmed)} зн., «{trimmed[:80]}…»")
    body = prepare_text(strip_lead(body))
    task = task_from_block(Marker(0, 0, external_id), body, path)
    task.stars = 0
    task.source_number = external_id
    task.collection_title = paragraph.heading
    task.topic_original = paragraph.heading
    task.topic_code = paragraph.topic
    if item.kind == KIND_EXAMPLE:
        if solution:
            solution = prepare_text(solution)
            task.author_solution_latex = clean(solution)
            answer = EXAMPLE_ANSWER_RE.search(solution)
            if answer:
                value = re.sub(r"\s*\\\\\s*$", "", answer.group("answer")).strip()
                task.author_answer_latex = re.sub(r"\.$", "", value).strip()
        else:
            task.warnings.append("У примера не найдено решение: сверить с книгой")
            diagnostics["examples_without_solution"].append(external_id)
    if re.search(r"-\s*$", task.text_latex) or (
            task.subitems and re.search(r"-\s*$", task.subitems[-1].text_latex)):
        task.warnings.append("Условие обрывается переносом: сверить с книгой")
        diagnostics["cut_bodies"].append(external_id)
    return task


# --------------------------------------------------------------------------
# Разбор целиком
# --------------------------------------------------------------------------

def parse_volchkevich(text: str, edition: dict | None = None) -> tuple[list[TaskDraft], dict]:
    """Разбор TEX; ``edition`` — описание издания вместо поиска по sha256."""
    text = text.replace("\r\n", "\n")
    edition = edition or load_edition(text)
    figure_repairs = load_figure_repairs(text)
    text, source_repairs = apply_source_repairs(text, REPAIRS_PATH)
    text, skipped = apply_skips(text, edition)
    grade = edition["grade"]
    headers = running_headers(edition)
    diagnostics: dict = {
        "edition": edition["title"],
        "source_repairs_applied": source_repairs,
        "skipped_duplicates": skipped,
        "tasks_by_paragraph": {},
        "missing_task_ids": [],
        "rejected_numbers": [],
        "figures_numbered": 0,
        "figures_by_task": 0,
        "figures_dropped": 0,
        "figure_repairs": len(figure_repairs),
        "figures_missing_by_task": {},
        "figures_unreferenced": [],
        "examples_without_solution": [],
        "examples_trimmed_tail": [],
        "cut_bodies": [],
        "lifted_tails": [],
        "labeled_answers_distributed": [],
    }
    zones = []
    global_index: dict[str, list[str]] | None = {} if grade == 7 else None
    for paragraph in paragraphs(text, edition):
        figures = Figures()
        zone = extract_figures(text[paragraph.start:paragraph.end], figures)
        zone = number_enumerates(strip_running_headers(zone, headers))
        apply_figure_repairs(paragraph, figures, figure_repairs, grade)
        if global_index is not None:
            for number, paths in figures.by_number.items():
                global_index.setdefault(number, []).extend(paths)
        diagnostics["figures_numbered"] += len(figures.by_number)
        diagnostics["figures_by_task"] += len(figures.by_task)
        diagnostics["figures_dropped"] += figures.dropped
        zones.append((paragraph, zone, figures))

    tasks: list[TaskDraft] = []
    for paragraph, zone, figures in zones:
        events = scan_events(zone, grade)
        items = cut_bodies(zone, classify_items(zone, events, paragraph, grade, diagnostics))
        counts = Counter(item.kind for item in items)
        diagnostics["tasks_by_paragraph"][paragraph.key] = {
            KIND_TITLES[kind]: counts.get(kind, 0) for kind in KIND_TITLES}
        for kind in KIND_TITLES:
            numbers = sorted(item.number for item in items if item.kind == kind)
            if numbers:
                diagnostics["missing_task_ids"].extend(
                    f"{paragraph.key}.{KIND_PREFIX[kind]}{n}"
                    for n in range(1, numbers[-1] + 1) if n not in numbers)
        order = {KIND_EXERCISE: 0, KIND_EXAMPLE: 1, KIND_TASK: 2}
        for item in sorted(items, key=lambda i: (order[i.kind], i.number)):
            task = build_draft(item, paragraph, diagnostics)
            missing = attach_figures(task, item, figures, global_index)
            for number in missing:
                diagnostics["figures_missing_by_task"].setdefault(
                    task.external_id, []).append(number)
            if missing:
                task.warnings.append(
                    "Не найден рисунок по подписи: " + ", ".join(missing))
            if lift_common_tail(task):
                diagnostics["lifted_tails"].append(task.external_id)
            if distribute_labeled_answer(task):
                diagnostics["labeled_answers_distributed"].append(task.external_id)
            _finish_fields(task)
            finalize_draft_images(task)
            tasks.append(task)
        unused_task_figures = sorted(
            n for n in figures.by_task
            if n not in {i.number for i in items if i.kind == KIND_TASK})
        if unused_task_figures:
            diagnostics["figures_unreferenced"].extend(
                f"{paragraph.key}: задача {n}" for n in unused_task_figures)
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["unique_tasks"] = len(tasks)
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_kind"] = dict(Counter(t.source_path[-1] for t in tasks))
    return tasks, diagnostics

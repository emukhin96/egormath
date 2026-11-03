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
    _LABEL_GUARD, _finish_fields, apply_source_repairs, distribute_labeled_answer,
    lift_common_tail, prepare_text)
from .merzlyak_parser import MATH_SPAN_RE, wrap_answer_numbers
from .textbook_parser import (
    Marker, SubitemDraft, TaskDraft, clean, finalize_draft_images, remove_group_commands,
    strip_subitem_punct,
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

# ``table`` — сетка подрисунков «а) … е)» под общей подписью «Рис. 4».
FIGURE_RE = re.compile(
    r"\\begin\{(?P<env>figure|table)\}.*?\\end\{(?P=env)\}(?:\s*\n[ \t]*Рис\.\s*(?P<after>\d{1,2}(?:\.\d{1,3})?)[ \t]*(?=\n))?",
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
_FIG_NUM = r"\d{1,2}(?:\.\d{1,3})?"
# Буквы частей рисунка: «, а», «, а и б», «, а–в»; «, а показан» — союз.
_FIG_SUBS = (r"(?P<subs>(?:\s*,?\s*[а-зa-e](?:\s*(?:[-–—]|и|,)\s*[а-зa-e])*"
             r"(?=\u2060?\s*[).,;:]|\s*$|\s+(?:показан|изображ|дан|приведен|видн)))?)")
# «(рис. 1.34)», «(см. рис. 14.18, а)», «(рисунок 6, а–в)».
PAREN_FIG_REF_RE = re.compile(
    r"\(\s*(?:см\.\s*)?[Рр]ис(?:ун(?:ок|ке|ки|ках))?\.?\s*(?P<first>" + _FIG_NUM + r")"
    r"(?:\s*[-–—]\s*(?P<last>" + _FIG_NUM + r"))?"
    r"(?P<more>(?:\s*,\s*" + _FIG_NUM + r"(?!\d|\.\d))*)" + _FIG_SUBS + r"\s*\u2060?\)")
# «на рисунке 1.28, а показан», «рисунках 4–18».
INLINE_FIG_REF_RE = re.compile(
    r"(?P<word>[Рр]ис(?:ун(?:ок|ке|ка|ки|ках|кам|ком|ками))?\.?)\s*"
    r"(?P<first>" + _FIG_NUM + r")(?:\s*[-–—]\s*(?P<last>" + _FIG_NUM + r"))?(?!\d)"
    r"(?P<more>(?:\s*(?:,|и)\s*" + _FIG_NUM + r"(?!\d|\.\d))*)" + _FIG_SUBS)
# «(» рис.)» — ссылка на рисунок задачи с подписью «» задача N».
TASK_FIG_REF_RE = re.compile(
    r"\(\s*['\"‘’`]{0,3}\s*(?:»|》|>>|►|▸|\\gg|\\triangleright)?\s*рис\.?\s*\)")

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
    r"(?m)(?:^|(?<=[.!?]))(?P<lead>[ \t]*)(?:Ответ|ОТВЕТ|OTBET|OmBem|Ombem|OmBеm|Omвem|Отвeт|Oтвет|ОmВеm|Om6em)[ \t]*:")
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
    topics: dict = field(default_factory=dict)
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
                topics=spec.get("topics", {}),
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
    # Рисунок, на который задача ссылается без номера («в таблице»).
    by_draft: dict[str, list[str]] = field(default_factory=dict)
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


def load_restructures(text: str, path: Path = REPAIRS_PATH) -> dict[str, dict]:
    """Сверенные «пункты из подрисунков» (``subitems``) для этого TEX."""
    if not path.exists():
        return {}
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spec = json.loads(path.read_text(encoding="utf-8"))
    for edition in spec.get("editions", []):
        if edition.get("source_sha256") == digest:
            return dict(edition.get("subitems", {}))
    return {}


def load_text_fixes(text: str, path: Path = REPAIRS_PATH) -> list[dict]:
    """Сверенные точечные правки готового текста карточки (``fixes``)."""
    if not path.exists():
        return []
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spec = json.loads(path.read_text(encoding="utf-8"))
    for edition in spec.get("editions", []):
        if edition.get("source_sha256") == digest:
            return list(edition.get("fixes", []))
    return []


def apply_text_fix(task: TaskDraft, fix: dict) -> None:
    """«old» → «new» в одном поле карточки; «old» обязан встречаться ровно раз.

    Поле — ``text_latex``, ``author_solution_latex``, ``author_answer_latex``
    или ``subitem:<метка>``. Правка применяется к тексту после всей
    нормализации профиля, поэтому совпадает с тем, что видно на сверке.
    """
    field = fix["field"]
    if field.startswith("subitem:"):
        label = field.split(":", 1)[1]
        target = next((item for item in task.subitems if item.label == label), None)
        if target is None:
            raise ValueError(f"{task.external_id}: нет пункта {label}")
        obj, attr = target, "text_latex"
    else:
        obj, attr = task, field
    value = getattr(obj, attr) or ""
    if fix["old"] == "":
        # Пустое поле, которое заполняет правка (ответ книги, потерянный OCR).
        if value:
            raise ValueError(f"{task.external_id} {field}: поле не пустое")
        setattr(obj, attr, fix["new"])
        return
    count = value.count(fix["old"])
    if count != 1:
        raise ValueError(f"{task.external_id} {field}: «{fix['old'][:40]}» встречается {count} раз")
    setattr(obj, attr, value.replace(fix["old"], fix["new"], 1))


def restructure(task: TaskDraft, spec: dict) -> None:
    """Задача, где пункты — подрисунки «а) … м)»: шапка без ссылок на
    рисунок, у каждого пункта свой подрисунок и своя пометка.

    ``pics`` — номера рисунков задачи по порядку (1 — первый поставленный).
    """
    fields = [task.text_latex] + [item.text_latex for item in task.subitems]
    paths = list(dict.fromkeys(re.findall(r"\\taskpic\{([^{}]+)\}", " ".join(fields))))
    used = {n for item in spec["items"] for n in item.get("pics", [])} | set(spec.get("pics", []))
    if used and (min(used) < 1 or max(used) > len(paths)):
        raise ValueError(f"{task.external_id}: в правке пунктов рисунки {sorted(used)}, "
                         f"а у задачи их {len(paths)}")
    stem_pics = " ".join(rf"\taskpic{{{paths[n - 1]}}}" for n in spec.get("pics", []))
    task.text_latex = " ".join(part for part in (spec["text"], stem_pics) if part)
    task.subitems = []
    for item in spec["items"]:
        pics = " ".join(rf"\taskpic{{{paths[n - 1]}}}" for n in item.get("pics", []))
        text = " ".join(part for part in (item.get("text", ""), pics) if part)
        task.subitems.append(SubitemDraft(item["label"], text))


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
        if "draft" in repair:
            if repair["draft"].split(".")[0] == paragraph.key:
                figures.by_draft.setdefault(repair["draft"], []).append(name)
        elif "task" in repair and repair.get("paragraph") == paragraph.key:
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
    for header in edition.get("extra_headers", []):
        # Колонтитул, которого нет в оглавлении (опечатка вёрстки); раньше
        # «ГЛАВА N», иначе та съест начало.
        parts.insert(0, r"\s+".join(re.escape(w) for w in header.split()))
    return re.compile(r"(?:\\item\[\][ \t]*)?(?:" + "|".join(parts) + r")[ \t]*(?:\\\\)?",
                      re.I)


def strip_running_headers(zone: str, pattern: re.Pattern) -> str:
    def replace(match: re.Match) -> str:
        # Заголовок раздела «\section*{§1 …}» — не колонтитул, но в задачи
        # он не попадает: граница параграфа уже найдена. «\item[] §6. … ность,
        # касающуюся» — продолжение пункта после колонтитула: метка остаётся.
        return "\\item[] " if match.group(0).startswith("\\item[]") else " "
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


def _leading_table(text: str) -> str:
    """Таблица в начале текста целиком, с вложенными ``tabular``."""
    start = re.match(r"(?:\\begin\{center\}\s*)?\\begin\{tabular\}", text)
    if not start:
        return ""
    depth = 0
    for edge in re.finditer(r"\\(begin|end)\{tabular\}", text):
        depth += 1 if edge.group(1) == "begin" else -1
        if depth == 0:
            tail = re.match(r"\s*\\end\{center\}", text[edge.end():])
            return text[:edge.end() + (tail.end() if tail else 0)]
    return ""


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
        table = _leading_table(lead)
        if table and re.search(r"(?i)таблиц", before):
            # «Заполните таблицу…» — таблица стоит сразу за списком.
            return before + "\n" + table
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


def _fig_ref_rest(rest: str) -> str:
    """«a-e», «a, b, b» после номера рисунка — буквы частей, не формула."""
    if not rest:
        return ""
    if re.fullmatch(r"[a-eа-е\d\s,\-–—]+", rest):
        letters = re.sub(r"\s*([,\-–—])\s*", lambda m: ", " if m.group(1) == "," else "–", rest.strip())
        return ", " + letters.translate(_LATIN_PART_LETTERS)
    return f", \\({rest}\\)"


_LOOKALIKE_LEAD = str.maketrans({"B": "В", "C": "С", "K": "К"})


def _flatten_nested_tabular(body: str) -> str:
    """Таблица в ячейке таблицы («Прямое утверждение | Обратное…») — строки
    внутренней таблицы через пробел: KaTeX не знает вложенный ``tabular``."""
    inner = re.compile(r"\\begin\{tabular\}(?:\[[^\]]*\])?\{[^{}]*\}(?P<body>(?:(?!\\begin\{tabular\}).)*?)\\end\{tabular\}", re.S)
    while True:
        found = [m for m in inner.finditer(body)
                 if body[:m.start()].count("\\begin{tabular}") > body[:m.start()].count("\\end{tabular}")]
        if not found:
            return body
        m = found[0]
        # «&» внутренней таблицы — разделитель «|», иначе у внешней строки
        # окажется больше столбцов, чем в её преамбуле.
        rows = [re.sub(r"\s*(?<!\\)&\s*", " | ", r.strip())
                for r in re.split(r"\\\\", m.group("body").replace("\\hline", "")) if r.strip()]
        body = body[:m.start()] + " ".join(rows) + body[m.end():]


def clean_body(body: str) -> str:
    body = remove_group_commands(body, FOOTNOTE_RE)
    body = _flatten_nested_tabular(body)
    # «( » рис.)» внутри выносной формулы: «\\text { ( } \\text { » рис.) }».
    body = re.sub(r"\\text\s*\{\s*\(\s*\}\s*\\text\s*\{\s*[»》]\s*рис\.?\)\s*\}", "", body)
    # «км», «мм», «см» в формуле OCR разрывает пробелом: «\\(0,02 к м^{2}\\)».
    body = re.sub(r"(?<=\d)\s*([кмсд])\s+м(?=\s*\^|\s*\\\)|[^а-яё])", r" \1м", body)
    body = re.sub(r"\\mathrm\{\s*KM\s*\}", r"\\mathrm{км}", body)
    # «Рис. 6.18» и «» задача 23» строкой или в конце строки — подписи
    # рисунков, оставшиеся без figure.
    body = re.sub(r"(?m)(?:^|(?<=[.?!)]))[ \t]*Рис\.\s*\d{1,2}(?:\.\d{1,3})?[ \t]*(?:\\\\)?[ \t]*$", "", body)
    body = re.sub(r"(?m)^[ \t]*(?:[»\-–—\"]|b\))?[ \t]*задач[аи][ \t]+\d{1,3}[ \t]*(?:\\\\)?[ \t]*$", "", body)
    # Подписи подрисунков «а)» и пустые строки «\\» из сетки рисунков.
    body = re.sub(r"(?m)^[ \t]*(?:[а-г]\)|\\\\)[ \t]*$", "", body)
    # Сноска «*» после вопроса — пометка сноски на поле страницы.
    body = re.sub(r"(?<=[.?!])\*(?=\s|$)", "", body)
    body = re.sub(r"\\setcounter\{[^{}]*\}\{\d+\}", "", body)
    # ``displayquote`` — врезка на полях (история, справка), не задание.
    body = re.sub(r"\\begin\{displayquote\}.*?\\end\{displayquote\}", "\n", body, flags=re.S)
    # «(рис. 22, \(a-г\))» — буквы частей рисунка в формуле.
    body = re.sub(
        r"(?P<head>[Рр]ис[а-я]*\.?\s*\d{1,2}(?:\.\d{1,3})?\s*,\s*)\\\(\s*(?P<subs>[a-eа-е3](?:\s*-\s*(?:[a-eа-е3]|\\beta))?)\s*\\\)",
        lambda m: m.group("head") + m.group("subs").replace("\\beta", "в").replace("3", "з").replace(" ", ""),
        body)
    # «рисунке \(2.21 a\)», «рис. \(4, a-e\)» — номер рисунка ушёл в формулу.
    body = re.sub(
        r"(?P<word>[Рр]ис(?:ун[а-я]*)?\.?)\s*\\\(\s*(?P<num>\d{1,2}(?:\.\d{1,3})?)\s*,?\s*(?P<rest>[^()]*?)\s*\\\)",
        lambda m: f"{m.group('word')} {m.group('num')}" + _fig_ref_rest(m.group("rest")),
        body)
    # «(рис. 16, а, б, в)» — «в)» не метка пункта: скобка защищается
    # невидимым знаком, его убирает _finish_fields.
    body = re.sub(r"(\((?:см\.\s*)?[Рр]ис[а-я]*\.?\s*\d[^()\n]{0,30}?[а-зa-e])\)", "\\1" + _LABEL_GUARD + ")", body)
    # Звёзды уровня у вопросов внутри задачи («★★ Найдите …») и след полой
    # звезды OCR.
    body = re.sub(r"(?m)(^|\\item\[\]|\\\\)[ \t]*(?:[★☆][ \t]*)+(?:[Д山એ][ \t]+)?", r"\1", body)
    body = re.sub(r"[ \t]*(?:[★☆][ \t]*)+", " ", body)
    # «\(a\) ) большой комнаты» — метка пункта ушла в формулу.
    body = re.sub(r"\\\(\s*([abBe])\s*\\\)\s*\)", lambda m: _LATIN_LABEL[m.group(1)] + ")", body)
    # «\left(\mathrm{~m}^{2}\right)» — скобки вокруг единицы: иначе
    # нормализация единиц разорвёт \left и \right по разным формулам.
    def unit_out(match: re.Match) -> str:
        unit = re.sub(r"[~\s]", "", match.group("unit")).replace("m", "м").replace("c", "с").replace("k", "к")
        power = f"$^{{{match.group('power')}}}$" if match.group("power") else ""
        return f"\\) ({unit}{power}) \\("
    unit_paren = r"\\left\(\s*\\mathrm\{(?P<unit>[^{}]*)\}(?:\^\{?(?P<power>\d)\}?)?\s*\\right\)"

    def unit_text(match: re.Match) -> str:
        unit = re.sub(r"[~\s]", "", match.group("unit")).replace("m", "м").replace("c", "с").replace("k", "к")
        power = f"^{{{match.group('power')}}}" if match.group("power") else ""
        return f"\\;(\\text{{{unit}}}{power})"
    # В выносной формуле единица остаётся в ней текстом.
    body = re.sub(r"\\\[.*?\\\]", lambda m: re.sub(unit_paren, unit_text, m.group(0)), body, flags=re.S)
    # Единица в скобках выносится из формулы: «7,5 (м$^{2}$)».
    body = re.sub(r"\\left\(\s*\\mathrm\{(?P<unit>[^{}]*)\}(?:\^\{?(?P<power>\d)\}?)?\s*\\right\)", unit_out, body)
    # «… \\(n=4,5,6\\). OTBET: 4, 5, 6.» — ответ всегда с новой строки.
    body = ANSWER_WORD_RE.sub("\nОтвет:", body)
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
    # «ДЛЯ ТЕХ, КТО ХОЧЕТ ЗНАТЬ БОЛЬШЕ», «ЗАДАЧИ» — начало следующего раздела.
    tail = re.search(r"(?m)^[ \t]*(?:\$?\d*\$?\s*)?(?:ДЛЯ ТЕХ, КТО ХОЧЕТ ЗНАТЬ БОЛЬШЕ|РЕШИТЕ ЗАДАЧИ|ЗАДАЧИ)[ \t]*$", solution)
    if tail:
        solution = solution[:tail.start()]
    # Разбор кончается первым «Ответ:», а без ответа — первым «Что и
    # требовалось доказать»: дальше в 8–9 классах идёт теория параграфа.
    end = EXAMPLE_ANSWER_RE.search(solution) or EXAMPLE_END_RE.search(solution)
    trimmed = ""
    if end:
        trimmed = solution[end.end():].strip()
        solution = solution[:end.end()]
    return condition, solution.strip(), trimmed


# Буквы частей рисунка, которые OCR дал латиницей, — по начертанию
# («e» — «е», а не пятая буква). «b» в книге — «б» (вид курсива).
_LATIN_PART_LETTERS = str.maketrans("abeBdc", "абевдс")


def _sub_labels(raw: str | None) -> str:
    """«, a и b» → «а и б»: буквы частей рисунка кириллицей."""
    value = re.sub(r"^\s*,?\s*", "", raw or "").strip()
    return value.translate(_LATIN_PART_LETTERS)


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

    def resolve(match: re.Match) -> list[str]:
        found = []
        more = re.findall(_FIG_NUM, match.groupdict().get("more") or "")
        for number in numbers(match.group("first"), match.group("last")) + more:
            paths = index.get(number)
            if paths:
                found.extend(paths)
            else:
                missing.append(number)
        return found

    def rewrite(value: str) -> str:
        # Номер рисунка книги в задаче не нужен — рисунок стоит в ней самой:
        # «(рис. 1.34)» → \taskpic, «на рисунке 1.34» → «на рисунке \taskpic»,
        # буква части остаётся: «(рис. 14.18, а)» → «\taskpic (а)».
        # Ссылка на рисунок, которого у задачи нет, остаётся как в книге.
        def paren(match: re.Match) -> str:
            found = resolve(match)
            if not found:
                return match.group(0)
            subs = _sub_labels(match.group("subs"))
            text = tokens(found)
            return (text + (f" (рис. {subs})" if subs else "")) or (f"(рис. {subs})" if subs else "\x00")

        def inline(match: re.Match) -> str:
            found = resolve(match)
            if not found:
                return match.group(0)
            subs = _sub_labels(match.group("subs"))
            text = tokens(found)
            return match.group("word") + (" " + text if text else "") + (f" {subs}" if subs else "")

        value = PAREN_FIG_REF_RE.sub(paren, value or "")
        # Повторная ссылка на уже поставленный рисунок исчезает целиком —
        # вместе с пробелом перед ней: «углом (рис. 1).» → «углом.».
        value = re.sub(r"[ \t]*\x00", "", value)
        value = INLINE_FIG_REF_RE.sub(inline, value)
        return re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", value)

    own = figures.by_task.get(item.number, []) if item.kind == KIND_TASK else []

    def own_ref(value: str) -> str:
        def replace(match: re.Match) -> str:
            if not own:
                # Своего рисунка нет: маркер OCR («\\gg», «►») — к «(рис.)».
                return "(рис.)"
            # Повторная ссылка на уже поставленный рисунок исчезает, как
            # и ссылка по номеру (маркер \x00 убирает rewrite).
            return tokens(own) or "\x00"
        return TASK_FIG_REF_RE.sub(replace, value or "")

    # Сначала условие и его пункты: рисунок встаёт туда, где его видит
    # ученик, а повторная ссылка исчезает уже в решении и ответе.
    task.text_latex = rewrite(own_ref(task.text_latex))
    for sub in task.subitems:
        sub.text_latex = rewrite(own_ref(sub.text_latex))
    for attr in ("author_solution_latex", "author_answer_latex"):
        setattr(task, attr, rewrite(own_ref(getattr(task, attr))))
    # Ссылка в скобках без рисунка проверяется дважды (в скобках и в тексте).
    missing[:] = list(dict.fromkeys(missing))
    extra = figures.by_draft.get(task.external_id, [])
    if extra:
        task.text_latex = task.text_latex.rstrip() + " " + tokens(extra)
    rest = [path for path in own if path not in placed]
    if rest:
        task.text_latex = task.text_latex.rstrip() + "\n" + tokens(rest)
    if item.kind == KIND_TASK and TASK_FIG_REF_RE.search(" ".join(
            [task.text_latex] + [s.text_latex for s in task.subitems])) and not own:
        missing.append(f"задача {item.number}")
    return missing


_INLINE_LABEL_RE = re.compile(r"(?<![\w(\\\u2060])(?P<label>[а-и])\)(?=\s)")
_LABEL_ORDER = "абвгдежзи"


def split_inline_labels(body: str) -> str:
    """«Докажите, что а) …; б) …» — пункты посреди фразы: с новой строки.

    Общий разбор делит пункты, только когда метка стоит в начале строки или
    после «:»/«;». Здесь метки идут подряд с «а)» вне формул — значит, это
    пункты; общая фраза после последнего уйдёт в шапку (lift_common_tail).
    """
    spans = [(m.start(), m.end()) for m in MATH_SPAN_RE.finditer(body)]
    labels = [m for m in _INLINE_LABEL_RE.finditer(body)
              if not any(a <= m.start() < b for a, b in spans)]
    chain = []
    for match in labels:
        if match.group("label") == _LABEL_ORDER[len(chain)]:
            chain.append(match)
        if len(chain) == len(_LABEL_ORDER):
            break
    if len(chain) < 2 or all(body[:m.start()].rstrip(" \t").endswith(("\n", ":", ";")) or
                             not body[:m.start()].strip() for m in chain):
        return body
    out = []
    pos = 0
    for match in chain:
        out.append(body[pos:match.start()].rstrip(" \t"))
        out.append("\n")
        pos = match.start()
    out.append(body[pos:])
    return "".join(out)


def lift_last_item_tail(task: TaskDraft) -> bool:
    """Общее к пунктам из последнего пункта — в шапку.

    «в) 120°. Найдите длину общей хорды…» — фраза с заглавной после точки.
    lift_common_tail Потоскуева этого не делает, если пункты — числа.
    """
    if len(task.subitems) < 2:
        return False
    last = task.subitems[-1]
    changed = False
    def fragment(value: str) -> bool:
        head = MATH_SPAN_RE.sub("x", value or "").lstrip()[:1]
        return head.islower() or head.isdigit()
    if not all(fragment(item.text_latex) for item in task.subitems):
        return changed
    plain = MATH_SPAN_RE.sub(lambda m: "x" * len(m.group(0)), last.text_latex)
    tail = re.search(r"(?<=[.?!])\s+(?=[А-ЯЁ][^\n]{8,}$)", plain)
    if tail and last.text_latex[:tail.start()].strip():
        sentence = last.text_latex[tail.end():].strip()
        last.text_latex = strip_subitem_punct(last.text_latex[:tail.start()].strip())
        if not re.search(r"[.?!]\)?$", sentence):
            sentence += "."
        task.text_latex = task.text_latex.rstrip() + "\n" + sentence
        changed = True
    return changed


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
    body = split_inline_labels(prepare_text(strip_lead(body)))
    task = task_from_block(Marker(0, 0, external_id), body, path)
    task.stars = 0
    # «(» рис.)» в конце последнего пункта — рисунок всей задачи, не пункта.
    if task.subitems:
        last = task.subitems[-1]
        marker = re.search(r"\s*" + TASK_FIG_REF_RE.pattern + r"\s*$", last.text_latex)
        if marker:
            last.text_latex = last.text_latex[:marker.start()].rstrip()
            task.text_latex = task.text_latex.rstrip() + " " + marker.group(0).strip()
    # «а)» без текста в конце — подпись подрисунка из сетки рисунков.
    task.text_latex = re.sub(r"\n[ \t]*[а-г]\)[ \t]*$", "", task.text_latex)
    task.source_number = external_id
    task.collection_title = paragraph.heading
    task.topic_original = paragraph.heading
    task.topic_code = paragraph.topics.get(external_id, paragraph.topic)
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
# Канон оформления (docs/TEXTBOOK_PARSE_QA.md, § 5)
# --------------------------------------------------------------------------

_UNITS = r"(?:мм|см|дм|км|м|га|кг|мг|г|т|ч|мин|с|л|мл|руб|р|Н)"
# «\(2,5 м^{2}\)», «\(AB=2 см\)» — единица внутри формулы.
_MATH_UNIT_RE = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?:\\mathrm\{\s*~?\s*)?(?P<unit>" + _UNITS + r")"
    r"(?:\s*\})?(?P<power>\s*\^\{?[23]\}?)?(?![а-яёА-ЯЁA-Za-z])")
# «5см», «$5$см» — единица вплотную к числу.
_GLUED_UNIT_RE = re.compile(r"(?<=[\d$])(?=" + _UNITS + r"(?![а-яё]))")


def _split_math_units(value: str) -> str:
    """Число — математика, единица — текст: «\\(2,5 м^{2}\\)» → «$2,5$ м$^{2}$»."""
    def fix(match: re.Match) -> str:
        raw = match.group(0)
        if raw.startswith(("\\[", "$$")) or not re.search("[а-яё]", raw, re.I):
            return raw
        inner = raw[2:-2] if raw.startswith("\\(") else raw[1:-1]
        if "\\text" in inner:
            return raw
        parts: list[str] = []
        pos = 0
        for unit in _MATH_UNIT_RE.finditer(inner):
            math = inner[pos:unit.end("num")].strip()
            if math:
                parts.append((" " if parts else "") + f"${math}$")
            power = re.sub(r"[\s{}^]", "", unit.group("power") or "")
            parts.append(" " + unit.group("unit") + (f"$^{{{power}}}$" if power else ""))
            pos = unit.end()
        if not parts:
            return raw
        tail = inner[pos:].strip()
        if tail:
            parts.append(f" ${tail}$")
        return "".join(parts).strip()
    return MATH_SPAN_RE.sub(fix, value or "")


def _tidy_dollars(value: str) -> str:
    """Пустые «$ $» и пробелы у краёв формул после разреза."""
    value = re.sub(r"\$\s*\$", " ", value)
    value = re.sub(r"\$\s+([^$]*?)\s*\$", lambda m: "$" + m.group(1).strip() + "$", value)
    return re.sub(r"[ \t]{2,}", " ", value).strip()


def _protect_decimal_commas(value: str) -> str:
    """«$11,25$» → «$11{,}25$»: ординарная запятая не разделитель списка."""
    def fix(match: re.Match) -> str:
        return re.sub(r"(?<=\d),(?=\d)", "{,}", match.group(0))
    return MATH_SPAN_RE.sub(fix, value or "")


_ROMAN_RE = re.compile(r"^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$")
# Буквы частей рисунка в формуле после картинки: «\\taskpic{1}, \\(a-i\\)».
_PART_RANGE_MATH_RE = re.compile(
    r"(?P<pics>\\taskpic\{[^{}]+\}(?:\s*\\taskpic\{[^{}]+\})*)\s*,\s*\\\(\s*(?P<a>[a-zа-я])\s*-\s*(?P<b>[a-zа-я])\s*\\\)")
_PART_SHAPES = str.maketrans("abeBdciu", "абевдсии")


def _prose(value: str, fix) -> str:
    """Применяет ``fix`` только к тексту вне формул."""
    out = []
    pos = 0
    for match in MATH_SPAN_RE.finditer(value):
        out.append(fix(value[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(fix(value[pos:]))
    return "".join(out)


def _wrap_point_names(chunk: str) -> str:
    """«треугольника CKE», «угла CKD» — обозначения точек в «$…$»."""
    def wrap(match: re.Match) -> str:
        word = match.group(0)
        # «XIX веке», «XII в.» — век римскими цифрами, «CD» — отрезок.
        if _ROMAN_RE.match(word) and re.match(r"\s+(?:век|в\.|столет)", chunk[match.end():]):
            return word
        return "$" + word + "$"
    chunk = re.sub(r"(?<![\w\\{$])[A-Z]{2,4}(?![\w}$])", wrap, chunk)
    # «C лежит на отрезке» — точка в начале фразы (предлоги уже кириллицей).
    chunk = re.sub(r"(?m)(?:(?<=^)|(?<=[.!?] ))([A-Z])(?= [а-яё])", r"$\1$", chunk)
    # «Буква H», «точкой P» — одиночная латинская буква после слова.
    return re.sub(r"(?<=[а-яё] )([A-Z])(?=[\s.,;:!?)]|$)", r"$\1$", chunk)


# «в 9:00», «после 16:00 и 20:00», «показывают 10:30» — время, а не отношение;
# только в тексте про часы, иначе «делится в $1:10$» — отношение.
_CLOCK_RE = re.compile(r"[Чч]ас(?:ы|ов|ах|ам)\b|стрелк|момент времени")
_TIME_RE = re.compile(r"(?P<lead>(?:\b(?:после|показывают|в|до|к)|\d и) )\$(?P<time>(?:[01]?\d|2[0-3]):[0-5]\d)\$")
_ALIGNED_RE = re.compile(r"\\begin\{aligned\}(?P<body>.*?)\\end\{aligned\}", re.S)


def _join_wrapped_formula(match: re.Match) -> str:
    """Строка формулы, перенесённая в книге по знаку («…+ \\\\ & +…»), — одной строкой."""
    rows = [row.strip() for row in re.split(r"\\\\", match.group("body"))]
    rows = [row for row in rows if row]
    joined = [rows[0]]
    for row in rows[1:]:
        tail = re.search(r"([+\-=])\s*$", joined[-1])
        head = re.match(r"&\s*([+\-=])\s*", row)
        if tail and head and tail.group(1) == head.group(1):
            joined[-1] = joined[-1][:tail.end(1)] + " " + row[head.end():]
        else:
            joined.append(row)
    if len(joined) == len(rows):
        return match.group(0)
    if len(joined) == 1:
        # Без aligned метки выравнивания — ошибка LaTeX: убираются все.
        return re.sub(r"\s*(?<!\\)&\s*", " ", joined[0]).strip()
    return "\\begin{aligned}\n" + " \\\\\n".join(joined) + "\n\\end{aligned}"


def canon_field(value: str) -> str:
    if not value:
        return value
    value = _ALIGNED_RE.sub(_join_wrapped_formula, value)
    # «B четырёхугольнике», «C помощью» — латинский двойник предлога в начале
    # фразы; перед глаголом («C лежит…», «K находится…») это точка.
    value = re.sub(r"(?m)(?:(?<=^)|(?<=[.!?:] ))([BCK])(?= [а-яё]{2,})(?! [а-яё]*(?:ит|ет|ют|ут|ат|ят|ся|ен|ена|ено|ны|на|но)\b)",
                   lambda m: m.group(1).translate(_LOOKALIKE_LEAD), value)
    # Перенос строки посреди фразы: «Пусть эта\\ прямая», «специ-\\ альной».
    value = re.sub(r"(?<=[а-яё])-\s*\\\\\s*\n?\s*(?=[а-яё])", "", value)
    value = re.sub(r"(?<=[а-яё,)])\s*\\\\\s*\n\s*(?=[а-яё])", " ", value)
    # Заголовки внутри разбора — словами: «РЕШЕНИЕ» → «Решение.».
    value = re.sub(r"(?m)^[ \t]*(РЕШЕНИЕ|ДОКАЗАТЕЛЬСТВО)[ \t]*:?[ \t]*$",
                   lambda m: m.group(1).capitalize() + ".", value)
    value = _PART_RANGE_MATH_RE.sub(
        lambda m: m.group("pics") + " (рис. " + m.group("a").translate(_PART_SHAPES)
        + "–" + m.group("b").translate(_PART_SHAPES) + ")", value)
    value = _prose(value, _wrap_point_names)
    # «( \\(A C\\) )», «( \\(2 ;-3\\) )» — скобки OCR вынес из формулы.
    value = re.sub(r"\(\s*\\\(([^()]*?)\\\)\s*\)", r"\\((\1)\\)", value)
    # «(рис. а, б), \\(в\\)» — последняя буква части ушла в формулу.
    value = re.sub(r"\(рис\. ([а-з](?:, [а-з])*)\),\s*\\\(\s*([а-з])\s*\\\)", r"(рис. \1, \2)", value)
    value = re.sub(r"(?<=[)$])[ \t]+(?=[.,;:)](?:\s|$|[)»]))", "", value)
    value = re.sub(r"(?<=\\\))[ \t]+(?=[.,;:)](?:\s|$))", "", value)
    # Пустые формулы и формулы из одного знака препинания после разреза.
    value = re.sub(r"\\\(\s*\\\)|\$\s+\$", "", value)
    value = re.sub(r"\s*\\\(\s*([.,;:])\s*\\\)", r"\1", value)
    # «\\mathbf{4 , 6 4 к м}» — жирный ответ OCR: без \\mathbf, иначе
    # разрез единицы рвёт скобки.
    value = re.sub(r"\\mathbf\{([^{}]*[а-яё][^{}]*)\}", r"\1", value)
    value = _split_math_units(value)
    value = _prose(value, lambda chunk: _GLUED_UNIT_RE.sub(" ", chunk))
    value = wrap_answer_numbers(value)
    # «(3, 4, 6)» — последнее число перед скобкой wrap_answer_numbers не
    # трогает (боится метки «6)»); в перечислении после запятой это число.
    value = _prose(value, lambda chunk: re.sub(r"(?<=, )(\d+(?:[.,]\d+)?)(?=\))", r"$\1$", chunk))
    value = _protect_decimal_commas(value)
    for _ in range(2 if _CLOCK_RE.search(value) else 0):  # второй проход — «16:00 и 20:00»
        value = _TIME_RE.sub(r"\g<lead>\g<time>", value)
    return _GLUED_UNIT_RE.sub(" ", value)


def canon_fields(task: TaskDraft) -> None:
    """Голые числа — в «$…$», запятая «{,}», единицы текстом через пробел."""
    task.text_latex = canon_field(task.text_latex)
    task.author_solution_latex = canon_field(task.author_solution_latex)
    task.author_answer_latex = canon_field(task.author_answer_latex)
    for item in task.subitems:
        item.text_latex = canon_field(item.text_latex)
        item.author_solution_latex = canon_field(item.author_solution_latex)
        item.author_answer_latex = canon_field(item.author_answer_latex)


# --------------------------------------------------------------------------
# Разбор целиком
# --------------------------------------------------------------------------

def parse_volchkevich(text: str, edition: dict | None = None) -> tuple[list[TaskDraft], dict]:
    """Разбор TEX; ``edition`` — описание издания вместо поиска по sha256."""
    text = text.replace("\r\n", "\n")
    edition = edition or load_edition(text)
    figure_repairs = load_figure_repairs(text)
    restructures = load_restructures(text)
    text_fixes: dict[str, list[dict]] = {}
    for fix in load_text_fixes(text):
        text_fixes.setdefault(fix["id"], []).append(fix)
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
        "restructured": [],
        "text_fixes_applied": 0,
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
    seen_ids: set[str] = set()
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
            seen_ids.add(task.external_id)
            if task.external_id in restructures:
                restructure(task, restructures[task.external_id])
                diagnostics["restructured"].append(task.external_id)
            if lift_common_tail(task) or lift_last_item_tail(task):
                diagnostics["lifted_tails"].append(task.external_id)
            if distribute_labeled_answer(task):
                diagnostics["labeled_answers_distributed"].append(task.external_id)
            _finish_fields(task)
            canon_fields(task)
            finalize_draft_images(task)
            for fix in text_fixes.get(task.external_id, []):
                apply_text_fix(task, fix)
                diagnostics["text_fixes_applied"] += 1
            tasks.append(task)
        unused_task_figures = sorted(
            n for n in figures.by_task
            if n not in {i.number for i in items if i.kind == KIND_TASK})
        if unused_task_figures:
            diagnostics["figures_unreferenced"].extend(
                f"{paragraph.key}: задача {n}" for n in unused_task_figures)
    # Правка, не нашедшая задачу, — ошибка: иначе после смены разбора она
    # молча перестала бы работать.
    drafts = {repair["draft"] for repair in figure_repairs if "draft" in repair}
    orphans = sorted((set(restructures) | set(text_fixes) | drafts) - seen_ids)
    if orphans:
        raise ValueError("Правки subitems/fixes/draft для отсутствующих задач: " + ", ".join(orphans))
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["unique_tasks"] = len(tasks)
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_kind"] = dict(Counter(t.source_path[-1] for t in tasks))
    return tasks, diagnostics

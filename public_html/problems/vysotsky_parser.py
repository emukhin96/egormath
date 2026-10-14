"""Профиль дидактических материалов Высоцкого по теории вероятностей, 8–9.

И. Р. Высоцкий. «Дидактические материалы по теории вероятностей.
8–9 классы» (МЦНМО, 2018, электронное издание), OCR Mathpix.

Особенности книги:

- 11 параграфов в трёх разделах, сквозная нумерация задач 1–396; в каждом
  параграфе «Задачи для работы в классе» и «Задания для домашней работы»,
  границы — в сверенной таблице ``data/vysotsky_structure.json``;
  вводное «Пояснение.» параграфа — теория, в импорт не входит;
- звёздочка после номера («29*.») — задача повышенной сложности;
- «Пример решения.» и «Указание.» после условия — авторский разбор задачи,
  стоящей перед ними: в авторское решение; «Ответы» в конце книги дают
  ответ и к этим задачам;
- карточки для индивидуальной работы (И1.1 … И11.3, по две задачи),
  самостоятельные работы (С1.1 … С11.2) и контрольные работы (КI.1 …
  КIII.2): метки карточек и самостоятельных стоят на полях, OCR их теряет
  и оставляет только номер варианта («1», «\\section*{2}»). Метки
  восстанавливаются по порядку книги, номер варианта в OCR сверяется с
  ожидаемым;
- ответы: «Ответы» (1–396), затем «Индивидуальные карточки»,
  «Самостоятельные работы», «Контрольные работы» с теми же метками;
- водяной знак электронного издания («AOdV/Gns8v48cw==») OCR вставляет
  в текст и формулы — удаляется.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .merzlyak_parser import (
    LEFTOVER_LABEL_RE, _heal_ocr_math, _heal_ocr_words, normalize_degrees,
    normalize_units, wrap_answer_numbers)
from .potoskuev_parser import (
    monotonic_numbers, renumber_appendix_lists, tabular_to_array)
from .textbook_parser import (
    Marker, TaskDraft, blocks, clean, cyrillic_item_label, finalize_draft_images,
    merge_solutions, task_from_block)


DATA_DIR = Path(__file__).with_name("data")
STRUCTURE_PATH = DATA_DIR / "vysotsky_structure.json"
REPAIRS_PATH = DATA_DIR / "vysotsky_repairs.json"

PART_RE = re.compile(r"\\section\*?\{\s*Раздел\s+(?P<part>I{1,3})\b")
PARAGRAPH_RE = re.compile(r"\\section\*?\{\s*§\s*(?P<number>\d{1,2})\.")
HOME_RE = re.compile(r"\\section\*?\{\s*Задания для домашней работы\s*\}")
CARDS_RE = re.compile(r"\\section\*?\{\s*Карточки для индивидуальной работы\s*\}")
WORKS_RE = re.compile(r"\\section\*?\{\s*Самостоятельные работы\s*\}")
TESTS_RE = re.compile(r"\\section\*?\{\s*Контрольные работы\s*\}")
HANDBOOK_RE = re.compile(r"\\section\*?\{\s*Справочник\s*\}")
ANSWERS_RE = re.compile(r"\\section\*?\{\s*Ответы\s*\}")
ANSWERS_CARDS_RE = re.compile(r"\\section\*?\{\s*Индивидуальные карточки\s*\}")
TOC_RE = re.compile(r"\\section\*?\{\s*Содержание\s*\}")
SECTION_RE = re.compile(r"\\section\*?\{[^{}]*\}")

# Водяной знак электронного издания: «AOdV/Gns8v48cw==», «aodvncissufaciv==»,
# внутри формулы — «\underset{\text { Aodv }(\text { nssuys cw }==}{…}».
WATERMARK_RE = re.compile(
    r"(?i)(?:\\caption\{)?\b[a-z0-9/+]*aod[a-z0-9/+]{4,}={1,2}\}?")

# Номер задачи в начале строки: «4.», «29*.», «2 .»; OCR ставит звёздочку
# и после точки: «179.*.», «239.*».
TASK_RE = re.compile(
    r"(?m)^[ \t]*(?P<number>\d{1,3})(?P<star>\*?)[ \t]?\.(?P<late>\*\.?)?(?=\s)")
# Авторский разбор после условия.
AUTHOR_MATERIAL_RE = re.compile(
    r"(?:(?<=\n)|(?<=\\\\)|(?<=[.?!»)]\s))[ \t]*"
    r"(?:Пример решения(?: и обсуждения)?|Пример возможного решения"
    r"|Пример доказательства|Указание|Решение|Обсуждение)\s*[.:]")
# Номер ответа: «12.», «77.» после пробела, не десятичная дробь «0,5.».
ANSWER_NUMBER_RE = re.compile(r"(?<![\w,.\\])(?P<number>\d{1,3})\s?\.(?=\s|$|\\\\)")


def load_structure(path: Path = STRUCTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def strip_watermarks(text: str) -> str:
    text = WATERMARK_RE.sub("", text)
    return re.sub(r"\\caption\{\s*\}", "", text)


_LIST_TOKEN_RE = re.compile(
    r"\\begin\{(?P<begin>enumerate|itemize)\}|\\end\{(?:enumerate|itemize)\}"
    r"|\\setcounter\{enum(?P<depth>i+)\}\{(?P<value>\d+)\}"
    r"|\\item(?:\[(?P<label>[^\[\]]*)\])?[ \t]*")
_EXPLICIT_NUMBER_RE = re.compile(r"(?<![\w,.\\§{])(?P<number>\d{1,3})\*?\s?\.(?=\s|$)")


def renumber_lists(text: str) -> str:
    """Списки → строки «N. …» с номерами книги.

    Mathpix ведёт счётчик ``enumerate`` по ``\\item``, но в строке книги
    бывает несколько номеров («186. … 187. …»), а следующий ``\\item``
    он считает 187-м. Номер пункта — следующий за наибольшим из счётчика
    и явных номеров, встреченных после предыдущего пункта. Во вложенных
    списках счётчик OCR бессмыслен (``\\setcounter{enumiii}{197}``) —
    там действует тот же сквозной номер.
    """
    out = []
    pos = 0
    depth = 0
    counter = 0
    last = 0

    def seen(chunk: str) -> None:
        nonlocal last
        for match in _EXPLICIT_NUMBER_RE.finditer(chunk):
            number = int(match.group("number"))
            if last < number <= last + 8:
                last = number

    for match in _LIST_TOKEN_RE.finditer(text):
        chunk = text[pos:match.start()]
        out.append(chunk)
        seen(chunk)
        pos = match.end()
        token = match.group(0)
        if match.group("begin"):
            depth += 1
            out.append("\n")
        elif token.startswith("\\end"):
            depth = max(0, depth - 1)
            out.append("\n")
        elif match.group("depth"):
            if len(match.group("depth")) == 1:
                counter = int(match.group("value"))
        elif match.group("label") is not None:
            label = match.group("label").strip()
            out.append("\n" + label + " ")
            seen(label + " ")
        elif depth:
            number = max(counter, last) + 1
            counter = last = number
            out.append(f"\n{number}. ")
        else:
            out.append("\n")
    out.append(text[pos:])
    return "".join(out)


# Ссылка на пункт «в п. а)» — не метка пункта: склеивается невидимым
# знаком, который снимается в готовых полях.
_LABEL_GUARD = "\u2060"
_POINT_REF_RE = re.compile(r"(?<=\bп\.)\s*(?=[а-е]\))")
# Латинские двойники меток пунктов в начале строки: «B)» → «в)».
_LATIN_LABEL_RE = re.compile(r"(?m)^(?P<lead>[ \t]*(?:\\item\[)?)B\)")


_PICTURE = r"\\includegraphics(?:\[[^\]]*\])?\{[^{}]+\}"
_INLINE_PICTURE_RE = re.compile(
    r"(?P<pre>[А-Яа-яЁё,])(?P<hy>-?)[ \t]*\\\\\n(?P<img>" + _PICTURE + r")\\\\\n"
    r"(?P<post>[а-яё][^\n]*?)(?P<end>\\\\\n|\n|$)")


def lift_inline_pictures(text: str) -> str:
    """«дере-⏎рисунок⏎во некоторого…»: рисунок стоял в обтекание посреди
    фразы — фраза склеивается (и разорванное слово), рисунок встаёт
    после неё."""
    def fix(match: re.Match) -> str:
        glue = "" if match.group("hy") else " "
        return (match.group("pre") + glue + match.group("post") + "\\\\\n"
                + match.group("img") + match.group("end"))
    return _INLINE_PICTURE_RE.sub(fix, text)


def prepare_text(text: str, *, through: bool = True) -> str:
    """``through`` — сквозная нумерация книги; иначе (карточки, работы)
    каждый список нумеруется с 1."""
    text = text.replace("\r\n", "\n")
    text = lift_inline_pictures(text)
    text = renumber_lists(text) if through else renumber_appendix_lists(text)
    text = re.sub(r"\\\\\[0pt\]", r"\\\\", text)
    text = _POINT_REF_RE.sub(" " + _LABEL_GUARD, text)
    text = _LATIN_LABEL_RE.sub(r"\g<lead>в)", text)
    text = _heal_ocr_words(text)
    # Латинские двойники кириллицы в словах книги.
    text = re.sub(r"\bCMC\b", "СМС", text).replace("Bceго", "Всего")
    text = tabular_to_array(text)
    text = re.sub(r"\\(?:begin|end)\{(?:table|center)\}(?:\[[^\]]*\])?", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# --------------------------------------------------------------------------
# Параграфы
# --------------------------------------------------------------------------

def paragraph_zones(text: str) -> list[tuple[int, int, int]]:
    """(номер параграфа, начало, конец) по заголовкам «§ N.»."""
    found = [(int(m.group("number")), m.start()) for m in PARAGRAPH_RE.finditer(text)]
    zones = []
    for index, (number, start) in enumerate(found):
        end = found[index + 1][1] if index + 1 < len(found) else len(text)
        zones.append((number, start, end))
    return zones


def task_markers(text: str, first: int, last: int) -> list[Marker]:
    candidates = [(m.start(), m.end(), int(m.group("number")))
                  for m in TASK_RE.finditer(text)]
    chain = monotonic_numbers(candidates, first - 1, 4, last)
    stars = {m.start(): bool(m.group("star") or m.group("late"))
             for m in TASK_RE.finditer(text)}
    return [Marker(begin, end, str(number), "star" if stars.get(begin) else "")
            for begin, end, number in chain]


def split_author_material(body: str) -> tuple[str, str]:
    match = AUTHOR_MATERIAL_RE.search(body)
    if not match:
        return body, ""
    return body[:match.start()].rstrip(), body[match.start():].strip()


def _clean_body(body: str) -> str:
    body = SECTION_RE.sub("\n", body)
    body = re.sub(r"\\footnotetext\{.*?\n\}", "\n", body, flags=re.S)
    body = re.sub(r"(?m)^\s*\}\s*$", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


_FOOTNOTE_RE = re.compile(r"\\footnotetext\{\s*\\\(\{\s*\}\^\{1\}\\\)\s*(?P<text>.*?)\n\}", re.S)
_FOOTNOTE_MARK_RE = re.compile(r"\s*\\\(\{\s*\}\^\{1\}\\\)")


def attach_footnotes(pairs: list[tuple[Marker, str]]) -> list[tuple[Marker, str]]:
    """Текст сноски внизу страницы OCR ставит в тело следующей задачи:
    сноска уходит к задаче со знаком «¹»."""
    result = [list(pair) for pair in pairs]
    for index in range(1, len(result)):
        body = result[index][1]
        if (not _FOOTNOTE_RE.search(body)
                or _FOOTNOTE_MARK_RE.search(_FOOTNOTE_RE.sub("", body))):
            continue
        # Ближайшая задача выше (до трёх назад) со знаком без своей сноски.
        for back in range(index - 1, max(-1, index - 4), -1):
            previous = result[back][1]
            if (_FOOTNOTE_MARK_RE.search(_FOOTNOTE_RE.sub("", previous))
                    and not _FOOTNOTE_RE.search(previous)):
                notes = "".join(m.group(0) for m in _FOOTNOTE_RE.finditer(body))
                result[index][1] = _FOOTNOTE_RE.sub("\n", body)
                result[back][1] = previous + "\n" + notes
                break
    return [tuple(pair) for pair in result]


def build_task(marker: Marker, body: str, path: list[str]) -> TaskDraft:
    # Сноска книги к задаче — методическое примечание: в разбор.
    notes = [clean(m.group("text")) for m in _FOOTNOTE_RE.finditer(body)]
    body = _FOOTNOTE_MARK_RE.sub("", _FOOTNOTE_RE.sub("\n", body))
    body, solution = split_author_material(_clean_body(body))
    task = task_from_block(marker, body, path)
    if marker.kind == "star":
        task.stars = max(task.stars, 1)
    if solution:
        task.author_solution_latex = clean(solution)
    if notes:
        task.author_solution_latex = "\n\n".join(
            ([task.author_solution_latex] if task.author_solution_latex else [])
            + ["Примечание. " + note for note in notes])
    return task


def parse_paragraphs(text: str, structure: dict, diagnostics: dict) -> list[TaskDraft]:
    parts = {part["number"]: part["title"] for part in structure["parts"]}
    specs = {item["number"]: item for item in structure["paragraphs"]}
    tasks: list[TaskDraft] = []
    seen = set()
    for number, start, end in paragraph_zones(text):
        spec = specs.get(number)
        if spec is None or number in seen:
            continue
        seen.add(number)
        zone = text[start:end]
        markers = task_markers(zone, spec["first"], spec["last"])
        found = {int(m.external_id) for m in markers}
        diagnostics["missing_task_ids"].extend(
            str(n) for n in range(spec["first"], spec["last"] + 1) if n not in found)
        diagnostics["tasks_by_paragraph"][number] = len(markers)
        home = HOME_RE.search(zone)
        home_at = home.start() if home else len(zone)
        first_home = next((int(m.external_id) for m in markers if m.start > home_at), None)
        if first_home != spec["home"]:
            diagnostics["home_boundary_mismatch"].append(
                f"§{number}: в тексте {first_home}, в таблице {spec['home']}")
        for marker, body in attach_footnotes(list(blocks(zone, markers))):
            sub = structure["class_title"] if marker.start < home_at else structure["home_title"]
            path = [parts[spec["part"]], spec["title"], sub]
            task = build_task(marker, body, path)
            task.collection_title = sub
            task.topic_original = spec["title"]
            task.topic_code = spec["topic"]
            if task.author_solution_latex:
                diagnostics["worked_examples"].append(task.external_id)
            tasks.append(task)
    for number in sorted(set(specs) - seen):
        spec = specs[number]
        diagnostics["paragraphs_without_zone"].append(number)
        diagnostics["missing_task_ids"].extend(
            str(n) for n in range(spec["first"], spec["last"] + 1))
    return tasks


# --------------------------------------------------------------------------
# Карточки, самостоятельные и контрольные работы
# --------------------------------------------------------------------------

# Номер варианта, оставшийся от метки на полях: строка «1», «2\\»,
# «\section*{3}», а также «1 1. …» (номер варианта приклеен к задаче 1).
VARIANT_RE = re.compile(
    r"(?m)^[ \t]*\}?[ \t]*(?:\\section\*?\{\s*(?P<sec>[1-3])\s*\}|(?P<line>[1-3])[ \t]*(?:\\\\)?[ \t]*$"
    r"|(?P<glued>[1-3])[ \t]+(?=1\.\s))")


def variant_zones(text: str) -> list[tuple[int, int, int]]:
    """(номер варианта из OCR, начало, конец) по меткам вариантов."""
    found = []
    for match in VARIANT_RE.finditer(text):
        value = match.group("sec") or match.group("line") or match.group("glued")
        found.append((int(value), match.start(), match.end()))
    zones = []
    for index, (value, start, end) in enumerate(found):
        stop = found[index + 1][1] if index + 1 < len(found) else len(text)
        zones.append((value, end, stop))
    return zones


ITEM_RE = re.compile(r"(?m)^[ \t]*(?P<number>[1-9])(?P<star>\*?)[ \t]?\.(?=\s)")


def item_markers(text: str, key: str) -> list[Marker]:
    candidates = [(m.start(), m.end(), int(m.group("number")))
                  for m in ITEM_RE.finditer(text)]
    stars = {m.start(): bool(m.group("star")) for m in ITEM_RE.finditer(text)}
    chain = monotonic_numbers(candidates, 0, 1)
    return [Marker(begin, end, f"{key}/{number}", "star" if stars.get(begin) else "")
            for begin, end, number in chain]


def parse_variant_series(zone: str, kind: str, structure: dict,
                         diagnostics: dict) -> list[TaskDraft]:
    """Карточки «И» или самостоятельные «С»: метки по порядку книги."""
    spec = structure["cards" if kind == "И" else "works"]
    paragraphs = structure["paragraphs"]
    expected = [(p["number"], v) for p in paragraphs
                for v in range(1, spec["variants"] + 1)]
    zones = variant_zones(zone)
    report = diagnostics.setdefault("variant_series", {})[kind] = {
        "expected": len(expected), "found": len(zones), "mismatched": []}
    tasks = []
    for (paragraph, variant), (ocr_value, start, end) in zip(expected, zones):
        key = f"{kind}{paragraph}.{variant}"
        if ocr_value != variant:
            report["mismatched"].append(f"{key}: в OCR {ocr_value}")
        # Номера внутри варианта: и ``\item``, и «2.» в тексте пункта.
        body = prepare_text(zone[start:end])
        spec_par = paragraphs[paragraph - 1]
        path = [spec["title"], f"{key}"]
        markers = item_markers(body, key)
        # Рисунок на полях перед «1.» (И5.1) OCR ставит до номера задачи.
        preamble = body[:markers[0].start] if markers else ""
        pictures = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{[^{}]+\}", preamble)
        for index, (marker, raw) in enumerate(blocks(body, markers)):
            if index == 0 and pictures:
                raw = raw.rstrip() + "\n" + "\n".join(pictures)
            task = build_task(marker, raw, path)
            task.collection_title = key
            task.topic_original = spec_par["title"]
            task.topic_code = spec_par["topic"]
            tasks.append(task)
    return tasks


TEST_HEADING_RE = re.compile(
    r"(?:\\section\*?\{\s*)?[KК](?P<roman>I{1,3}|І{1,3}|ІI|IІ)\s*\.\s*(?P<variant>[1-4])")


def parse_tests(zone: str, structure: dict, diagnostics: dict) -> list[TaskDraft]:
    spec = structure["tests"]
    items = {item["key"]: item for item in spec["items"]}
    found = []
    for match in TEST_HEADING_RE.finditer(zone):
        roman = match.group("roman").replace("І", "I")
        key = f"К{roman}.{match.group('variant')}"
        if key in items and key not in [k for k, _s, _e in found]:
            found.append((key, match.start(), match.end()))
    diagnostics["tests_found"] = [key for key, _s, _e in found]
    tasks = []
    for index, (key, start, end) in enumerate(found):
        stop = found[index + 1][1] if index + 1 < len(found) else len(zone)
        body = zone[end:stop]
        body = re.sub(r"\\section\*?\{\s*(?:Вариант|Bap)[^{}]*\}", "\n", body)
        body = prepare_text(body)
        # Остаток заголовка: «. «Случайные события» \\ Вариант 1 …}».
        body = re.sub(r"^[^\n]*\n", "\n", body)
        body = re.sub(r"\\section\*?\{\s*(?:Вариант|Bap)[^{}]*\}", "\n", body)
        item = items[key]
        path = [spec["title"], item["title"]]
        markers = item_markers(body, key)
        if len(markers) != item["tasks"]:
            diagnostics["tests_task_count_mismatch"].append(
                f"{key}: {len(markers)} из {item['tasks']}")
        topics = {p["number"]: p for p in structure["paragraphs"]}
        for marker, raw in blocks(body, markers):
            task = build_task(marker, raw, path)
            task.collection_title = item["title"]
            task.topic_original = item["title"]
            number = int(marker.external_id.split("/")[1])
            paragraph = item.get("paragraphs", [])[number - 1:number]
            if paragraph:
                task.topic_code = topics[paragraph[0]]["topic"]
            tasks.append(task)
    return tasks


# --------------------------------------------------------------------------
# Ответы
# --------------------------------------------------------------------------

def answer_markers(text: str, allowed: set[str]) -> list[Marker]:
    candidates = [(m.start(), m.end(), int(m.group("number")))
                  for m in ANSWER_NUMBER_RE.finditer(text)
                  if m.group("number") in allowed]
    return [Marker(begin, end, str(number))
            for begin, end, number in monotonic_numbers(candidates, 0, 6)]


LABEL_ANSWER_RE = re.compile(
    r"(?P<key>[ИиCСKК](?:I{1,3}|І{1,3})?\s?\d{0,2}\s?\.\s?\d)\s?\.(?=\s)")


def labeled_answer_blocks(text: str) -> dict[str, str]:
    """«И1.1. 1. а) …» → {"И1.1": "1. а) …"}."""
    result = {}
    found = []
    for match in re.finditer(
            r"(?:(?<=\s)|^)(?P<kind>[ИиCСKК])(?P<roman>I{1,3}|І{1,3})?\s?"
            r"(?P<a>\d{1,2})?\s?\.\s?(?P<b>\d)\s?\.?(?=\s)", text):
        kind = {"и": "И", "C": "С", "K": "К"}.get(match.group("kind"), match.group("kind"))
        if kind == "К":
            roman = (match.group("roman") or "").replace("І", "I")
            if not roman or match.group("a"):
                continue
            key = f"К{roman}.{match.group('b')}"
        else:
            if not match.group("a"):
                continue
            key = f"{kind}{match.group('a')}.{match.group('b')}"
        found.append((key, match.start(), match.end()))
    for index, (key, start, end) in enumerate(found):
        stop = found[index + 1][1] if index + 1 < len(found) else len(text)
        result.setdefault(key, SECTION_RE.sub("", text[end:stop]))
    return result


def keep_examples(tasks: list[TaskDraft], examples: dict[str, str]) -> None:
    """Разбор из текста параграфа — перед указанием из раздела ответов."""
    for task in tasks:
        inline = examples.get(task.external_id)
        if not inline:
            continue
        extra = task.author_solution_latex
        def letters(value: str) -> str:
            return re.sub(r"[^А-Яа-яЁё]", "", value or "")
        if extra and letters(extra) in letters(inline):
            # Указание книги повторено и в разделе ответов (166).
            extra = ""
        task.author_solution_latex = inline + ("\n\n" + extra if extra else "")


def attach_labeled_answers(tasks: list[TaskDraft], text: str, diagnostics: dict) -> None:
    by_key: dict[str, list[TaskDraft]] = {}
    for task in tasks:
        by_key.setdefault(task.external_id.split("/")[0], []).append(task)
    raw = labeled_answer_blocks(text)
    diagnostics["labeled_answer_keys"] = sorted(raw)
    diagnostics["labeled_answers_missing"] = sorted(set(by_key) - set(raw))
    for key, group in by_key.items():
        body = raw.get(key)
        if body is None:
            continue
        examples = {t.external_id: t.author_solution_latex
                    for t in group if t.author_solution_latex}
        local = {task.external_id.split("/")[1]: task for task in group}
        candidates = [(m.start(), m.end(), int(m.group("number")))
                      for m in re.finditer(
                          r"(?<![\w,.])(?P<number>[1-9])\s?\.(?=\s|$|\\\\)", body)
                      if m.group("number") in local]
        markers = [Marker(b, e, f"{key}/{n}")
                   for b, e, n in monotonic_numbers(candidates, 0, 2)]
        result = merge_solutions(group, body, lambda value, m=markers: m, missing_ok=True)
        for name in ("missing_solution_ids",):
            diagnostics.setdefault("labeled_" + name, []).extend(result.get(name, []))
        keep_examples(group, examples)


# --------------------------------------------------------------------------
# Поля
# --------------------------------------------------------------------------

_JOINT_RE = re.compile(r"^\s*и\s+(?P<label>[б-е])\)\s*")


def share_joint_answers(task: TaskDraft) -> bool:
    """«а) и б) 25» — один ответ двух пунктов: OCR отдаёт его пункту а)."""
    labels = {item.label: item for item in task.subitems}
    changed = False
    for item in task.subitems:
        match = _JOINT_RE.match(item.author_answer_latex or "")
        if not match or match.group("label") not in labels:
            continue
        item.author_answer_latex = item.author_answer_latex[match.end():]
        other = labels[match.group("label")]
        if not other.author_answer_latex:
            other.author_answer_latex = item.author_answer_latex
        changed = True
    return changed


_TAIL_LINE_RE = re.compile(r"\n\s*(?P<tail>[А-ЯЁ][^\n]{8,})\s*$")


def lift_common_tail(task: TaskDraft) -> bool:
    """«г) \\(n\\) раз.⏎При необходимости результаты округляйте…» —
    общее требование ко всем пунктам отдельной строкой после последнего
    пункта: переносится в условие, иначе при выборе части пунктов
    пропадёт."""
    if len(task.subitems) < 2:
        return False
    last = task.subitems[-1]
    match = _TAIL_LINE_RE.search(last.text_latex or "")
    if not match:
        return False
    head = last.text_latex[:match.start()].strip()
    if not head:
        return False
    last.text_latex = re.sub(r"\s*(?:\\\\)?\s*$", "", head).rstrip(".;")
    task.text_latex = task.text_latex.rstrip() + "\n" + match.group("tail").strip()
    return True


def move_answer_notes(task: TaskDraft) -> bool:
    """«… Примечание. Важно, решая эту…» — сноска книги к ответу:
    в разбор, а не в ответ (по ответу строится маска)."""
    moved = False
    for item in [task, *task.subitems]:
        answer = item.author_answer_latex or ""
        match = re.search(r"\s*Примечание\.\s*", answer)
        if not match:
            continue
        note = answer[match.end():].strip()
        item.author_answer_latex = answer[:match.start()].rstrip()
        item.author_solution_latex = "\n\n".join(
            part for part in (item.author_solution_latex, "Примечание. " + note) if part)
        moved = True
    return moved


_PICTURE_TOKEN_RE = re.compile(r"\s*(?:\\\\\s*)?(?P<pic>\\taskpic\{\d+\}|" + _PICTURE + r")\s*(?:\\\\)?\s*$")


def lift_stem_pictures(task: TaskDraft) -> bool:
    """Рисунок условия, который OCR поставил в конец последнего пункта
    (книга даёт его справа от всех пунктов), — в общее условие."""
    if len(task.subitems) < 2:
        return False
    last = task.subitems[-1]
    match = _PICTURE_TOKEN_RE.search(last.text_latex or "")
    if not match or any(re.search(_PICTURE + r"|\\taskpic", item.text_latex or "")
                        for item in task.subitems[:-1]):
        return False
    last.text_latex = last.text_latex[:match.start()].rstrip()
    task.text_latex = task.text_latex.rstrip() + "\\\\\n" + match.group("pic")
    return True


_WHOLE_WARNING = "Авторский материал не удалось распределить по подпунктам"


def _finish_fields(task: TaskDraft) -> None:
    def text_field(value: str) -> str:
        value = (value or "").replace(_LABEL_GUARD, "")
        # Голый «%» в LaTeX — комментарий: съедает конец строки и ломает PDF.
        value = re.sub(r"(?<!\\)%", r"\\%", value)
        return normalize_degrees(normalize_units(_heal_ocr_math(value)))

    def answer_field(value: str) -> str:
        value = wrap_answer_numbers(text_field(value))
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
    answers = [task.author_answer_latex] + [
        item.author_answer_latex for item in task.subitems]
    if any(LEFTOVER_LABEL_RE.search(value or "") for value in answers):
        task.warnings.append(
            "В ответе остались метки других пунктов: сверить с книгой")
        task.confidence = max(0.0, task.confidence - 0.3)


def parse_vysotsky(text: str) -> tuple[list[TaskDraft], dict]:
    if not ANSWERS_RE.search(text) or not CARDS_RE.search(text):
        raise ValueError("Не найдены задачи и «Ответы» Высоцкого")
    text, source_repairs = apply_source_repairs(text)
    text = strip_watermarks(text)
    structure = load_structure()
    first_part = PART_RE.search(text)
    cards = CARDS_RE.search(text)
    works = WORKS_RE.search(text, cards.end())
    tests = TESTS_RE.search(text, works.end())
    handbook = HANDBOOK_RE.search(text, tests.end())
    answers = ANSWERS_RE.search(text, handbook.end())
    answers_cards = ANSWERS_CARDS_RE.search(text, answers.end())
    toc = TOC_RE.search(text, answers_cards.end())

    diagnostics: dict = {
        "source_repairs_applied": source_repairs,
        "tasks_by_paragraph": {},
        "paragraphs_without_zone": [],
        "missing_task_ids": [],
        "worked_examples": [],
        "tests_task_count_mismatch": [],
        "home_boundary_mismatch": [],
    }
    main = prepare_text(text[first_part.start():cards.start()])
    tasks = parse_paragraphs(main, structure, diagnostics)
    allowed = {task.external_id for task in tasks}
    examples = {task.external_id: task.author_solution_latex
                for task in tasks if task.author_solution_latex}
    answer_text = prepare_text(text[answers.end():answers_cards.start()])
    solution = merge_solutions(
        tasks, answer_text, lambda value: answer_markers(value, allowed),
        missing_ok=True)
    diagnostics.update(solution)
    keep_examples(tasks, examples)

    extra: list[TaskDraft] = []
    extra += parse_variant_series(
        text[cards.end():works.start()], "И", structure, diagnostics)
    extra += parse_variant_series(
        text[works.end():tests.start()], "С", structure, diagnostics)
    extra += parse_tests(
        text[tests.end():handbook.start()], structure, diagnostics)
    labeled = prepare_text(text[answers_cards.end():toc.start() if toc else len(text)], through=False)
    attach_labeled_answers(extra, labeled, diagnostics)
    tasks += extra

    grades = structure.get("grade_bands", [])
    whole = set(structure.get("answers_whole", {}))
    diagnostics["joint_answers"] = []
    diagnostics["lifted_tails"] = []
    for task in tasks:
        if lift_common_tail(task):
            diagnostics["lifted_tails"].append(task.external_id)
        move_answer_notes(task)
        if lift_stem_pictures(task):
            diagnostics.setdefault("stem_pictures", []).append(task.external_id)
        if share_joint_answers(task):
            diagnostics["joint_answers"].append(task.external_id)
        if task.external_id in whole:
            # Книга даёт один рисунок-ответ на все пункты: сверено.
            task.warnings = [w for w in task.warnings if w != _WHOLE_WARNING]
        task.grade_band_codes = list(grades)
        _finish_fields(task)
        finalize_draft_images(task)
    diagnostics["unique_tasks"] = len({t.external_id for t in tasks})
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_section"] = dict(Counter(" / ".join(t.source_path) for t in tasks))
    return tasks, diagnostics

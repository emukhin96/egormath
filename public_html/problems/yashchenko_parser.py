"""Профиль ``yashchenko_ege``: «ЕГЭ. Математика. Профильный уровень.
36 вариантов» под ред. И. В. Ященко (ФИПИ — школе, 2027), TEX Mathpix.

Книга — 36 полных вариантов по проекту КИМ ЕГЭ-2027: 20 заданий в каждом
(часть 1 — №1–13 с кратким ответом, часть 2 — №14–20). Ключ задачи —
«В<вариант>/<номер>» (``В7/14``), подборка — вариант. Номер задания сразу
даёт метку линии ``EGE_PROFILE_2027_NN`` и основную тему (как у банка
Остромогильского, ``ege_metadata.SECTION_TOPICS``); маски строит загрузка
в каталог по формату линии (``assignments.checks.ege_policy``).

Ответы — таблицы «Вариант N» в конце книги; «а) …; б) …» делятся по
подпунктам (у №15 и №18 пункт а — доказательство, ответа нет). Решения
части 2 есть у вариантов 1, 7, 11, 17, 21, 27, 31: каждое задание
кончается таблицей критериев, по ним разбор режется на №14–20.

Ловушки OCR (разобраны ниже): рисунок справа от текста (№1, №3) Mathpix
вставляет посреди фразы или перед маркером задания, иногда повторяя
начало фразы; маркер задания бывает голым числом в начале строки
(«3 Шар описан…»), заголовок варианта 8 испорчен («ВАРИകΗ 8»).
Сверенные с PDF правки OCR — ``data/yashchenko_repairs.json`` (только
для sha256 этого TEX).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .ege_metadata import SECTION_TOPICS
from .merzlyak_parser import apply_source_repairs
from .textbook_parser import (
    SubitemDraft, TaskDraft, finalize_draft_images, normalize_imported_text,
    read_group)
from .volchkevich_parser import canon_fields

DATA_DIR = Path(__file__).resolve().parent / "data"
REPAIRS_PATH = DATA_DIR / "yashchenko_repairs.json"
STRUCTURE_PATH = DATA_DIR / "yashchenko_structure.json"

VARIANTS = 36
TASKS_PER_VARIANT = 20
SOLVED_VARIANTS = (1, 7, 11, 17, 21, 27, 31)
# Номер задания → подпункты, если книга делит его на пункты.
LINE_TITLES = {
    1: "Планиметрия", 2: "Векторы", 3: "Стереометрия",
    4: "Вероятность", 5: "Вероятность сложных событий",
    6: "Случайные величины", 7: "Уравнения",
    8: "Вычисления и преобразования", 9: "Производная и график",
    10: "Прикладная задача", 11: "Текстовая задача",
    12: "Графики функций", 13: "Финансовая математика",
    14: "Уравнение с отбором корней", 15: "Стереометрическая задача",
    16: "Неравенство", 17: "Экстремальная задача",
    18: "Планиметрическая задача", 19: "Задача с параметром",
    20: "Числа и их свойства",
}

VARIANT_RE = re.compile(r"\\section\*\{В[^\s{}\\]{2,10}\s+(\d{1,2})\b")
ANSWERS_RE = re.compile(r"\\section\*\{ОТВЕТЫ\}")
SOLUTIONS_RE = re.compile(r"\\section\*\{РЕШЕНИЯ И КРИТЕРИИ")
SOLUTION_VARIANT_RE = re.compile(r"\\section\*\{Вариант (\d{1,2})\}")
SOLUTIONS_END_RE = re.compile(r"\\section\*\{ЧОУ ДПО")
IMAGE_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^{}]+)\}")
# «Ответ: \_\_\_\_.» — поле краткого ответа; OCR: «Oтвет», «Omвет».
BLANK_RE = re.compile(r"(?:Ответ|Oтвет|OТВЕТ|Omвет|Отвeт)\s*:?(?:\s|\\\\)*(?:\\_){2,}\s*\.?")
# Служебный текст варианта: инструкции, «Часть 2», напоминания о бланке.
BOILERPLATE = [
    re.compile(r"\\section\*\{\s*Часть\s*[12]\s*\}"),
    re.compile(r"\\textbackslash\s*section\*\\\{\s*Часть\s*2\s*\\\}(?:\\\\)?"),
    re.compile(r"Ответом к заданиям 1-13 является[^\n]*"),
    re.compile(r"Не забудьте перенести все ответы[^\n]*"),
    re.compile(r"Проверьте, чтобы каждый ответ[^\n]*"),
    re.compile(r"Для записи решений и ответов на задания 14-20[^\n]*"),
    re.compile(r"\s*Часть\s*1\s*\}"),
    re.compile(r"(?m)^[ \t]*Часть[ \t]*2[ \t]*(?:\\\\)?[ \t]*$"),
]
LIST_RE = re.compile(r"\\(?:begin|end)\{(?:itemize|enumerate|center)\}")
SUB_LABELS = {"а": "а", "a": "а", "б": "б", "6": "б", "в": "в", "B": "в"}
SUB_LABEL_RE = re.compile(r"(?m)(?:^|(?<=\\\\))[ \t]*(?P<label>[аaб6вB])\)[ \t]*")
ANSWER_LABEL_RE = re.compile(r"(?:^|(?<=[\s;.,]))(?P<label>[аaб6вB])\)\s*")
SOLUTION_WORD_RE = re.compile(r"[РP][еe]ш[еe]ни[еe]\.?")
TABULAR_RE = re.compile(r"\\(begin|end)\{tabular\}")
# Обёртки таблицы критериев: center, table с подписью «Окончание табл.».
CRITERIA_WRAP_RE = re.compile(
    r"(?:\\begin\{(?:center|table)\}(?:\[h\])?\s*|\\captionsetup\{[^{}]*\}\s*"
    r"|\\caption\{[^{}]*\}\s*|\\end\{(?:center|table)\}\s*|Окончание табл\.\s*)*$")


def criteria_spans(block: str) -> list[tuple[int, int]]:
    """Таблицы «Содержание критерия … Баллы» верхнего уровня (с обёртками)."""
    spans = []
    depth = 0
    start = 0
    for match in TABULAR_RE.finditer(block):
        if match.group(1) == "begin":
            if depth == 0:
                start = match.start()
            depth += 1
            continue
        depth -= 1
        if depth == 0 and "Содержание критерия" in block[start:match.end()]:
            end = match.end()
            after = re.match(r"\s*\\end\{(?:center|table)\}", block[end:])
            if after:
                end += after.end()
            lead = CRITERIA_WRAP_RE.search(block[:start])
            spans.append((lead.start() if lead else start, end))
    return spans


def load_edition(text: str, path: Path = STRUCTURE_PATH) -> dict:
    """Описание издания по sha256 TEX; для чужого скана — пустое."""
    if not path.exists():
        return {}
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spec = json.loads(path.read_text(encoding="utf-8"))
    for edition in spec.get("editions", []):
        if edition.get("source_sha256") == digest:
            return edition
    return {}


FIELDS = {"text": "text_latex", "answer": "author_answer_latex",
          "solution": "author_solution_latex"}


def load_repairs(text: str, path: Path = REPAIRS_PATH) -> dict:
    """Правки этого скана (TEX ``patches`` применяет ``apply_source_repairs``)."""
    if not path.exists():
        return {}
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spec = json.loads(path.read_text(encoding="utf-8"))
    for edition in spec.get("editions", []):
        if edition.get("source_sha256") == digest:
            return edition
    return {}


def apply_text_fix(task: TaskDraft, fix: dict) -> None:
    """Сверенная с PDF правка готового поля: ``before`` — ровно один раз.

    ``field``: text / answer / solution; ``label`` — подпункт. Пустой
    ``before`` с ``replace: true`` задаёт поле целиком (потерянный OCR текст).
    """
    target = task
    if fix.get("label"):
        matches = [item for item in task.subitems if item.label == fix["label"]]
        if len(matches) != 1:
            raise ValueError(f"{fix['id']}: нет подпункта {fix['label']}")
        target = matches[0]
    attr = FIELDS[fix["field"]]
    value = getattr(target, attr)
    if "images" in fix:
        # Рисунки задачи целиком (потерянный OCR кусок со своими чертежами).
        task.images = list(fix["images"])
    if fix.get("replace"):
        setattr(target, attr, fix["after"])
        return
    count = value.count(fix["before"])
    if count != 1:
        raise ValueError(
            f"{fix['id']} {fix['field']}{fix.get('label', '')}: "
            f"фрагмент {fix['before']!r} встречается {count} раз")
    setattr(target, attr, value.replace(fix["before"], fix["after"], 1))


def prune_images(task: TaskDraft) -> None:
    """После правки: рисунки без ссылки ``\\taskpic{N}`` выпадают, номера
    сдвигаются по порядку списка."""
    blobs = [getattr(task, attr) for attr in FIELDS.values()]
    for item in task.subitems:
        blobs.extend(getattr(item, attr) for attr in FIELDS.values())
    used = {int(n) for blob in blobs for n in re.findall(r"\\taskpic\{(\d+)\}", blob)}
    keep = [index for index in range(1, len(task.images) + 1) if index in used]
    if len(keep) == len(task.images):
        return
    renumber = {old: new for new, old in enumerate(keep, 1)}

    def rewrite(value: str) -> str:
        return re.sub(r"\\taskpic\{(\d+)\}",
                      lambda m: rf"\taskpic{{{renumber[int(m.group(1))]}}}", value)
    for target in [task] + list(task.subitems):
        for attr in FIELDS.values():
            setattr(target, attr, rewrite(getattr(target, attr)))
    task.images = [task.images[index - 1] for index in keep]


def locator(variant: int, number: int) -> str:
    return f"В{variant}/{number}"


def strip_footnotes(text: str) -> str:
    """``\\footnotetext{© 2027…}`` — колонтитул издательства посреди текста."""
    out = []
    pos = 0
    for match in re.finditer(r"\\footnotetext\{", text):
        if match.start() < pos:
            continue
        out.append(text[pos:match.start()])
        _body, pos = read_group(text, match.end() - 1)
    out.append(text[pos:])
    return "".join(out)


def variant_spans(text: str) -> dict[int, str]:
    """Тексты вариантов 1–36 до раздела ответов."""
    end = ANSWERS_RE.search(text)
    if not end:
        raise ValueError("Не найден раздел «ОТВЕТЫ»")
    body = text[:end.start()]
    heads = [m for m in VARIANT_RE.finditer(body)]
    spans: dict[int, str] = {}
    for index, head in enumerate(heads):
        stop = heads[index + 1].start() if index + 1 < len(heads) else len(body)
        number = int(head.group(1))
        if number in spans:
            raise ValueError(f"Вариант {number} встречается дважды")
        spans[number] = body[head.end():stop]
    return spans


def task_markers(body: str) -> tuple[list[tuple[int, int, int]], list[int]]:
    """``(номер, начало, конец маркера)`` в порядке 1…20.

    Маркер — ``\\item[N]`` или голое «N » в начале строки (OCR потерял
    список), в том числе после пустого ``\\item[]``. Номер ищется строго
    после предыдущего — «16 &» в таблицах и числа в тексте не путаются.
    """
    markers = []
    missing = []
    pos = 0
    for number in range(1, TASKS_PER_VARIANT + 1):
        pattern = re.compile(
            rf"\\item\[{number}\]\s*"
            rf"|^[ \t]*(?:\\item\[\][ \t]*)?{number}[ \t]+(?=[А-ЯЁA-Z\\])", re.M)
        match = pattern.search(body, pos)
        if not match:
            missing.append(number)
            continue
        markers.append((number, match.start(), match.end()))
        pos = match.end()
    return markers, missing


def _clean_raw(body: str) -> str:
    for pattern in BOILERPLATE:
        body = pattern.sub("", body)
    body = LIST_RE.sub("", body)
    return body


def _join_broken_sentence(before: str, after: str) -> str:
    """Склейка текста вокруг вынутого рисунка.

    Mathpix ставит боковой рисунок посреди фразы и иногда повторяет после
    него начало этой фразы: «Два угла … равны 48°\\\\ [рис] Два угла …
    равны 48° и 74°.» — повтор отбрасывается.
    """
    head = re.sub(r"(?:\s|\\\\)+$", "", before)
    tail = re.sub(r"^(?:\s|\\\\)+", "", after)
    if not head:
        return tail
    if not tail:
        return head
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    # Повтор начала фразы: хвост начинается с последнего абзаца головы.
    last_par = re.split(r"\n\s*\n|\\\\\s*\n", head)[-1]
    if len(norm(last_par)) >= 12 and norm(tail).startswith(norm(last_par)):
        return head[:len(head) - len(last_par)].rstrip() + ("\n" if head[:len(head) - len(last_par)].strip() else "") + tail
    if re.search(r"[.:?!]\s*$", head):
        return head + "\n" + tail
    return head + " " + tail


def pull_images(text: str) -> tuple[str, list[str], list[str]]:
    """Вынимает рисунки: ``(текст, рисунки посреди фразы, рисунки на месте)``.

    Рисунок между фразами (график к №9, №12) остаётся на месте;
    рисунок, разорвавший фразу (боковой, №1, №3), уходит в конец условия.
    """
    moved: list[str] = []
    kept: list[str] = []
    while True:
        match = IMAGE_RE.search(text)
        if not match:
            break
        name = match.group(1)
        before, after = text[:match.start()], text[match.end():]
        head = re.sub(r"(?:\s|\\\\)+$", "", before)
        tail = re.sub(r"^(?:\s|\\\\)+", "", after)
        broken = bool(head) and not re.search(r"[.:?!]\s*$", head) and bool(tail) \
            and not re.match(r"\\taskpic|@@PIC", tail)
        if broken or not head:
            moved.append(name)
            text = _join_broken_sentence(before, after)
        else:
            kept.append(name)
            text = head + f"\n@@PIC{len(kept) - 1}@@\n" + tail
    for index, name in enumerate(kept):
        text = text.replace(f"@@PIC{index}@@", rf"\includegraphics{{{name}}}")
    return text, moved, kept


def split_letter_subitems(text: str) -> tuple[str, list[SubitemDraft]]:
    """«а) … б) … в) …» в начале строк → подпункты (метки по-кириллице)."""
    text = re.sub(r"\\item\[([аaб6вB])\)\]", r"\n\1) ", text)
    matches = list(SUB_LABEL_RE.finditer(text))
    labels = [SUB_LABELS[m.group("label")] for m in matches]
    expected = ["а", "б", "в"][:len(matches)]
    if len(matches) < 2 or labels != expected:
        return text, []
    stem = text[:matches[0].start()]
    items = []
    for index, match in enumerate(matches):
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        items.append(SubitemDraft(labels[index], tidy(text[match.end():stop])))
    return tidy(stem), items


def tidy(text: str) -> str:
    text = re.sub(r"\\item\[\]\s*", "", text)
    text = re.sub(r"\\item\[(\d+\))\]\s*", r"\n\1 ", text)
    text = re.sub(r"\\item\[-\]\s*", "\n— ", text)
    text = re.sub(r"(?m)^[ \t]*\\\\[ \t]*$", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return normalize_imported_text(text.strip())


# --------------------------------------------------------------------------
# Ответы
# --------------------------------------------------------------------------

def parse_answer_tables(text: str) -> dict[int, dict[int, str]]:
    start = ANSWERS_RE.search(text)
    stop = SOLUTIONS_RE.search(text)
    zone = text[start.end():stop.start() if stop else len(text)]
    tables: dict[int, dict[int, str]] = {}
    caps = list(re.finditer(r"\\caption\{Вариант (\d{1,2})\}", zone))
    for index, cap in enumerate(caps):
        end = caps[index + 1].start() if index + 1 < len(caps) else len(zone)
        table = zone[cap.end():end]
        table = table[:table.find(r"\end{table}")] if r"\end{table}" in table else table
        rows: dict[int, str] = {}
        cells = list(re.finditer(r"(?m)^(\d{1,2})\s*&\s*", table))
        for row_index, cell in enumerate(cells):
            row_end = cells[row_index + 1].start() if row_index + 1 < len(cells) else len(table)
            value = table[cell.end():row_end]
            value = re.sub(r"\\\\\s*\\hline\s*$", "", value.strip())
            value = re.sub(r"\\hline", "", value)
            value = re.sub(r"\\end\{tabular\}\s*\\end\{center\}.*$", "", value, flags=re.S)
            rows[int(cell.group(1))] = answer_cell(value)
        tables[int(cap.group(1))] = rows
    return tables


def answer_cell(value: str) -> str:
    """Ячейка таблицы ответов → строка ответа (вложенная tabular — строки)."""
    inner = re.search(r"\\begin\{tabular\}\[t\]\{l\}(.*?)\\end\{tabular\}", value, re.S)
    if inner:
        value = inner.group(1)
    value = re.sub(r"\\begin\{gathered\}|\\end\{gathered\}", "", value)
    # Ячейка-список «\\begin{itemize}… \\item[a)] …» и обёртка tabular.
    value = re.sub(r"\\item\[([^\]]*)\]", r" \1 ", value)
    value = re.sub(r"\\(?:begin|end)\{(?:itemize|tabular|center)\}(?:\[[^\]]*\])?(?:\{L\{[^{}]*\}\}|\{[^{}]*\})?", " ", value)
    value = value.replace("\\\\", " ").replace("\n", " ")
    value = re.sub(r"\\\(\s*\\\)", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.rstrip(";").strip()


def split_answer(value: str, labels: list[str]) -> dict[str, str]:
    """«а) X; б) Y» → по меткам; без меток — общий ответ под ключом ''."""
    matches = [m for m in ANSWER_LABEL_RE.finditer(value)]
    found = [SUB_LABELS[m.group("label")] for m in matches]
    if not matches or any(label not in labels for label in found) \
            or found != sorted(found, key=labels.index) or len(set(found)) != len(found):
        return {"": value}
    parts = {}
    lead = value[:matches[0].start()].strip(" ;,.")
    if lead:
        parts[""] = lead
    for index, match in enumerate(matches):
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        chunk = value[match.end():stop].strip()
        chunk = re.sub(r"\s*[;,.]\s*$", "", chunk).strip()
        parts[found[index]] = chunk
    return parts


# --------------------------------------------------------------------------
# Решения части 2
# --------------------------------------------------------------------------

def parse_solutions(text: str) -> tuple[dict[tuple[int, int], dict], list[str]]:
    """``(вариант, номер) → {'solution', 'condition'}`` и предупреждения."""
    start = SOLUTIONS_RE.search(text)
    if not start:
        return {}, ["Не найден раздел решений"]
    end = SOLUTIONS_END_RE.search(text, start.end())
    zone = text[start.end():end.start() if end else len(text)]
    heads = list(SOLUTION_VARIANT_RE.finditer(zone))
    result: dict[tuple[int, int], dict] = {}
    warnings = []
    for index, head in enumerate(heads):
        variant = int(head.group(1))
        stop = heads[index + 1].start() if index + 1 < len(heads) else len(zone)
        block = zone[head.end():stop]
        pieces = []
        pos = 0
        for cut_start, cut_end in criteria_spans(block):
            pieces.append(block[pos:cut_start])
            pos = cut_end
        pieces.append(block[pos:])
        pieces = [piece for piece in pieces
                  if re.sub(r"\\(?:begin|end)\{itemize\}|\s", "", piece)]
        number = 13
        for piece in pieces:
            # Номер — из пересказа условия («\\item[16]», «16 Решите…»),
            # иначе следующий по порядку.
            head = re.match(r"(?:\s|\\(?:begin|end)\{itemize\})*(?:\\item\[)?(1[4-9]|20)(?:\])?\s", piece)
            number = int(head.group(1)) if head else number + 1
            if (variant, number) in result or number > 20:
                warnings.append(f"Вариант {variant}: лишний кусок решений после №{number - 1}")
                continue
            solved = SOLUTION_WORD_RE.search(piece)
            if not solved:
                warnings.append(f"{locator(variant, number)}: нет слова «Решение»")
                condition, solution = "", piece
            else:
                condition, solution = piece[:solved.start()], piece[solved.end():]
            if re.search(r"(?m)^\s*[РP][еe]ш[еe]ни[еe]\.", solution):
                warnings.append(f"{locator(variant, number)}: в разборе ещё одно «Решение»")
            # Рисунок между пересказом условия и «Решением» — к разбору.
            pictures = "".join(f"\\includegraphics{{{name}}}\n" for name in IMAGE_RE.findall(condition))
            result[(variant, number)] = {
                "condition": tidy(_clean_raw(IMAGE_RE.sub("", condition))),
                "solution": tidy(pictures + _clean_raw(solution)),
            }
    return result, warnings


# --------------------------------------------------------------------------
# Разбор целиком
# --------------------------------------------------------------------------

def build_task(variant: int, number: int, raw: str, images: list[str]) -> TaskDraft:
    text = _clean_raw(raw)
    text = BLANK_RE.sub("", text)
    text, moved, _kept = pull_images(text)
    stem, subitems = split_letter_subitems(text)
    stem = tidy(stem) if not subitems else stem
    pics = list(dict.fromkeys(images + moved))
    if pics:
        stem = (stem.rstrip() + "\n" + "\n".join(
            rf"\includegraphics{{{name}}}" for name in pics)).strip()
    title = LINE_TITLES[number]
    return TaskDraft(
        external_id=locator(variant, number),
        source_number=str(number),
        source_path=[f"Вариант {variant}"],
        collection_key=f"variant-{variant:02d}",
        collection_title=f"Вариант {variant}",
        topic_original=f"Задание {number}. {title}",
        text_latex=stem,
        subitems=subitems,
        exam_item_codes=[f"EGE_PROFILE_2027_{number:02d}"],
        grade_band_codes=["GRADE_10_11"],
        topic_code=SECTION_TOPICS.get(number, ""),
    )


def attach_answer(task: TaskDraft, value: str) -> None:
    if not value:
        task.warnings.append("Нет ответа в таблице ответов")
        return
    labels = [item.label for item in task.subitems]
    if not labels:
        task.author_answer_latex = value
        return
    parts = split_answer(value, labels)
    if set(parts) == {""}:
        # №15/№18: «б) …» без а); иначе — общий ответ задачи.
        target = [item for item in task.subitems
                  if not re.match(r"\s*Докажите", item.text_latex)]
        if len(target) == 1:
            target[0].author_answer_latex = parts[""]
        else:
            task.author_answer_latex = parts[""]
            task.warnings.append("Ответ не разделён по подпунктам")
        return
    for item in task.subitems:
        if item.label in parts:
            item.author_answer_latex = parts[item.label]
    if "" in parts:
        task.author_answer_latex = parts[""]


MATH_RE = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]|\$[^$]*\$", re.S)
NUM = r"-?\d+(?:,\d+)?"
# «отрезку [-2; 6]», «интервале (-6; 8)» — промежуток целиком в формулу.
PROSE_INTERVAL_RE = re.compile(rf"[\[(]\s*{NUM}\s*;\s*{NUM}\s*[\])]")
PROSE_PERCENT_RE = re.compile(rf"(?<![\w{{]){NUM}\s*\\%")


def _outside_math(value: str, fix) -> str:
    out, pos = [], 0
    for match in MATH_RE.finditer(value):
        out.append(fix(value[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(fix(value[pos:]))
    return "".join(out)


def _pre_canon(value: str) -> str:
    if not value:
        return value
    value = _outside_math(value, lambda chunk: PROSE_INTERVAL_RE.sub(
        lambda m: "\\(" + re.sub(r"\s+", "", m.group(0)).replace(";", "; ") + "\\)", chunk))
    value = _outside_math(value, lambda chunk: PROSE_PERCENT_RE.sub(
        lambda m: "\\(" + re.sub(r"\s+", "", m.group(0)) + "\\)", chunk))
    # «\\(К\\).» — кириллическая буква (инициал) не формула.
    value = re.sub(r"\\\(\s*([А-ЯЁ])\s*\\\)", r"\1", value)
    # Секунды латиницей: «T=14,4 \\mathrm{c}».
    value = re.sub(r"\\mathrm\{\s*c\s*\}", r"\\text{ с}", value)
    return value


def _post_canon(value: str) -> str:
    if not value:
        return value
    # Хвостовые «\\\\» и разрыв строки перед пустой строкой.
    value = re.sub(r"(?:\s*\\\\)+\s*$", "", value)
    value = re.sub(r"\\\\[ \t]*\n[ \t]*\n", "\n\n", value)
    # «$100$ p .» — рубли латинской «p».
    value = re.sub(r"(?<=\$) p \.", " р.", value)
    # «$20$ , равна», «\\(x\\) .» — пробел OCR перед знаком препинания.
    return re.sub(r"(?<=[$)])[ \t]+(?=[,.;:](?:\s|$))", "", value)


def merge_answer_math(value: str) -> str:
    """«\\(πn\\), \\(n∈Z\\); \\( π/2+2πl, l∈Z ; \\)» → одна формула."""
    if not value:
        return value
    # Жирный OCR таблицы ответов: «\\mathbf{1 6 1}», «\\boldsymbol{\\sqrt { 3 }}».
    for _ in range(3):
        value = re.sub(r"\\(?:mathbf|boldsymbol)\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", r"\1", value)
    # Цифры через пробел: «3 , 1 0 5» → «3,105».
    value = re.sub(r"(?<=\d) (?=\d)", "", value)
    value = re.sub(r"(?<=\d) , (?=\d)", ",", value)
    value = re.sub(r"(?<=\d) (?=\d)", "", value)
    # Ответ, перенесённый в книге на две строки: aligned с «\\cup & \\cup».
    value = re.sub(r"\\begin\{aligned\}|\\end\{aligned\}", "", value)
    value = re.sub(r"\\cup\s*&\s*\\cup", r"\\cup", value)
    value = re.sub(r"(?<!\\)&", " ", value)
    previous = None
    while previous != value:
        previous = value
        value = re.sub(r"\\\)\s*([,;])\s*\\\(\s*", r"\1 ", value)
    value = re.sub(r"\s*[;,]\s*\\\)", r"\\)", value)
    value = re.sub(r"\\\(\s+", r"\\(", value)
    return value.strip()


def polish(task: TaskDraft) -> None:
    """Канон оформления (как у Волчкевича) плюс поправки этой книги."""
    fields = [task] + list(task.subitems)
    for item in fields:
        item.text_latex = _pre_canon(item.text_latex)
        item.author_solution_latex = _pre_canon(item.author_solution_latex)
        item.author_answer_latex = merge_answer_math(item.author_answer_latex)
    canon_fields(task)
    for item in fields:
        item.text_latex = _post_canon(item.text_latex)
        item.author_solution_latex = _post_canon(item.author_solution_latex)
        item.author_answer_latex = _post_canon(item.author_answer_latex)


LATIN_WORDS = (
    (re.compile(r"(?<![\w\\])[OО]t?[тmt][вbB][еe][тt](?=\s*:)"), "Ответ"),
    (re.compile(r"(?<![\w\\])[PР][еe]ш[еe]ни[еe](?=\.)"), "Решение"),
)


def _cleanup(value: str) -> str:
    """Общие остатки OCR после сверенных правок (их фрагменты — до чистки)."""
    if not value:
        return value
    # Метки пунктов и перечисления решений без окружения списка.
    value = re.sub(r"\\item\[([аaб6вB])\)\]\s*",
                   lambda m: SUB_LABELS[m.group(1)] + ") ", value)
    value = re.sub(r"\\item\[\]\s*", "", value)
    value = re.sub(r"(?m)^([ \t]*)\\item\s+", r"\1— ", value)
    # Жирные цифры водяного знака: «\\mathbf{1 6 1}».
    value = re.sub(r"\\(?:mathbf|boldsymbol)\{\s*(\d[\d\s]*)\}",
                   lambda m: re.sub(r"\s+", "", m.group(1)), value)
    value = value.replace("。", ".")
    for pattern, word in LATIN_WORDS:
        value = pattern.sub(word, value)
    return value


TEXT_GROUP_RE = re.compile(r"\\(?:text|textbf|textit|operatorname)\s*\{[^{}]*\}")
CYRILLIC_RUN_RE = re.compile(r"[А-Яа-яЁё]+(?:[ \t]+[А-Яа-яЁё]+)*")


def _cyrillic_in_math(value: str) -> str:
    """Кириллица в формуле — в ``\\text{}``: в PDF математический шрифт её
    теряет («\\frac{Дж}{К}», «T_{п}», «\\mathrm{ч}»)."""
    def fix(match: re.Match) -> str:
        span = match.group(0)
        if not re.search("[А-Яа-яЁё]", span):
            return span
        span = re.sub(r"\\mathrm\s*\{([^{}]*[А-Яа-яЁё][^{}]*)\}",
                      lambda m: r"\text{" + m.group(1).strip("~ ") + "}", span)
        # Единица по буквам: «к г», «Д ж».
        span = re.sub(r"(?<![А-Яа-яЁё])([А-Яа-яЁё]) ([а-яё])(?![А-Яа-яЁё])", r"\1\2", span)
        out, pos = [], 0
        for group in TEXT_GROUP_RE.finditer(span):
            out.append(CYRILLIC_RUN_RE.sub(lambda m: r"\text{" + m.group(0) + "}",
                                           span[pos:group.start()]))
            out.append(group.group(0))
            pos = group.end()
        out.append(CYRILLIC_RUN_RE.sub(lambda m: r"\text{" + m.group(0) + "}", span[pos:]))
        return "".join(out)
    return MATH_RE.sub(fix, value or "")


INLINE_SPAN_RE = re.compile(r"(?<![$\\])\$(?!\$)([^$]+)\$|\\\((.*?)\\\)", re.S)
YEAR_RE = re.compile(
    r"\$((?:1[89]|20)\d\d)\$(?=(?:\s*(?:,|и|–|-)\s*\$?(?:1[89]|20)\d\d\$?)*\s+г(?:од|г\.))")
DEGREE_RE = re.compile(r"(?:\$([^$]*\d)\$|(?<![\w{])(\d+(?:\{,\}\d+|,\d+)?))[ \t]*°(?:[ \t]*([CС])(?![а-яё]))?")
SENTENCE_VERB_RE = re.compile(
    r"(\\\)|\$|[а-яё0-9])([ \t]+)(?=(?:Найдите|Определите|Вычислите|Укажите|Решите|Запишите|Докажите)\b)")


def _years_as_text(value: str) -> str:
    """«В июле $2030$ года», «в июле $2031$, $2032$ и $2033$ годов» — год
    не формула, пишется текстом."""
    previous = None
    while previous != value:
        previous = value
        value = YEAR_RE.sub(r"\1", value)
    return value


def _degrees_in_math(value: str) -> str:
    """«равен 30°», «$21{,}5$ °C» → «$30^{\\circ}$», «$21{,}5^{\\circ}\\mathrm{C}$»."""
    def fix(match: re.Match) -> str:
        number = match.group(1) or match.group(2).replace(",", "{,}")
        if match.group(3):
            return f"${number}^{{\\circ}}\\mathrm{{C}}$"
        return f"${number}^{{\\circ}}$"
    out, pos = [], 0
    for span in re.finditer(r"\\\(.*?\\\)|\\\[.*?\\\]|\$\$.*?\$\$", value, re.S):
        out.append(DEGREE_RE.sub(fix, value[pos:span.start()]))
        out.append(span.group(0))
        pos = span.end()
    out.append(DEGREE_RE.sub(fix, value[pos:]))
    return "".join(out)


def _display_style(value: str, *, exponents: bool) -> str:
    """Строчная формула с дробью или вложенной степенью — ``\\displaystyle``;
    дробь в показателе — ``^{\\textstyle …}`` (иначе мелко). Ответы без
    ``\\textstyle``: его не знает разбор маски."""
    def fix(match: re.Match) -> str:
        span = match.group(0)
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        if "\\begin{" in inner:
            return span
        heavy = "\\frac" in inner or re.search(r"\^\{[^{}]*\^", inner)
        if exponents:
            inner = re.sub(r"\^\{(?!\\textstyle)(?=[^{}]*\\frac)", r"^{\\textstyle ", inner)
        if heavy and "\\displaystyle" not in inner:
            inner = "\\displaystyle " + inner.lstrip()
        return f"${inner}$" if match.group(1) is not None else f"\\({inner}\\)"
    return INLINE_SPAN_RE.sub(fix, value or "")


def _layout(value: str) -> str:
    """Условия книги — сплошной текст: без пустых строк и отступов строк."""
    value = re.sub(r"(?m)^[ \t]+", "", value)
    return re.sub(r"\n(?:[ \t]*\n)+", "\n", value).strip()


def _sentence_ends(value: str, *, close: bool) -> str:
    """Точка, потерянная OCR перед «Найдите…» (рисунок разорвал строку), и
    в конце условия; «?» внутри формулы — после неё."""
    value = SENTENCE_VERB_RE.sub(r"\1.\2", value)
    value = re.sub(r"\s*\?\s*\\\)", r"\\)?", value)
    if close:
        tail = re.sub(r"(?:\s|\\taskpic\{\d+\}|\\\\)+$", "", value)
        if tail and tail[-1] not in ".?!:;" and not re.search(r"(?:\\\]|\$\$|\\end\{\w+\})$", tail):
            value = tail + "." + value[len(tail):]
    return value


def typography(task: TaskDraft) -> None:
    """Канон оформления партии (замечания владельца 15.11.2026)."""
    for item in [task] + list(task.subitems):
        is_sub = item is not task
        for attr in FIELDS.values():
            value = getattr(item, attr)
            if not value:
                continue
            value = _degrees_in_math(_years_as_text(value))
            value = _display_style(value, exponents=attr != "author_answer_latex")
            if attr != "author_answer_latex":
                value = _layout(value)
            if attr == "text_latex":
                value = _sentence_ends(value, close=bool(value.strip()) and (is_sub or not task.subitems))
            setattr(item, attr, value)


def final_cleanup(task: TaskDraft) -> None:
    for item in [task] + list(task.subitems):
        for attr in FIELDS.values():
            setattr(item, attr, _cyrillic_in_math(_cleanup(getattr(item, attr))))
    typography(task)


def apply_masks(task: TaskDraft, masks: dict) -> None:
    """Явная маска из файла правок: «В9/17» или «В30/15б»; остальные строит
    загрузка в каталог по формату линии ЕГЭ."""
    if task.external_id in masks:
        task.answer_mask = masks[task.external_id]
    for item in task.subitems:
        key = task.external_id + item.label
        if key in masks:
            item.answer_mask = masks[key]


# Задания, которым в этой книге нужен рисунок: №1 и №3 — всегда (боковой
# чертёж), остальные — по словам условия.
FIGURE_WORDS_RE = re.compile(r"рисун|изображ|график|диаграмм|схем", re.I)


def wants_figure(number: int, raw: str) -> bool:
    return number in {1, 3} or bool(FIGURE_WORDS_RE.search(raw))


def split_gap(raw: str, *, last: bool) -> tuple[str, list[str]]:
    """Текст задания и рисунки после него (после поля ответа или в пустом
    ``\\item[]`` в конце куска) — их владельца решает ``gap_owner``."""
    if last:
        return raw, []
    blank = list(BLANK_RE.finditer(raw))
    if blank:
        tail = raw[blank[-1].end():]
        return raw[:blank[-1].end()] + IMAGE_RE.sub("", tail), IMAGE_RE.findall(tail)
    tail = re.search(
        r"(?:\\item\[\]|\\\\)\s*(?:\\begin\{center\}\s*)?((?:\\includegraphics[^\n]*\s*)+)"
        r"(?:\\end\{center\}\s*)?(?:\\end\{itemize\}\s*)?$", raw)
    if tail:
        return raw[:tail.start()], IMAGE_RE.findall(tail.group(1))
    return raw, []


def gap_owner(chunks: list, index: int) -> int:
    """Рисунок между заданиями ``index`` и ``index+1``.

    Боковой рисунок Mathpix ставит по его верхней границе: выше первой
    строки следующего задания — после поля ответа предыдущего. Поэтому
    по умолчанию — следующему, но если ему рисунок не нужен или уже есть,
    а предыдущему нужен и нет — предыдущему.
    """
    def has(i):
        return bool(IMAGE_RE.search(chunks[i][1]))

    def wants(i):
        return wants_figure(chunks[i][0], chunks[i][1])

    nxt = index + 1
    if nxt < len(chunks) and wants(nxt) and not has(nxt):
        return nxt
    if wants(index) and not has(index):
        return index
    return nxt if nxt < len(chunks) else index


def parse_yashchenko(text: str) -> tuple[list[TaskDraft], dict]:
    text = text.replace("\r\n", "\n")
    edition = load_edition(text)
    owners = edition.get("figure_owners", {})
    derived = edition.get("derived_figures", [])
    relocated: list[str] = []
    guessed: list[str] = []
    repairs = load_repairs(text)
    fixes: dict[str, list[dict]] = {}
    for fix in repairs.get("text_fixes", []):
        fixes.setdefault(fix["id"], []).append(fix)
    masks = repairs.get("answer_masks", {})
    fixed = 0
    text, source_repairs = apply_source_repairs(text, REPAIRS_PATH)
    text = strip_footnotes(text)
    for figure in derived:
        if figure.get("replaces"):
            text = text.replace("{" + figure["replaces"] + "}", "{" + figure["name"] + "}")
    spans = variant_spans(text)
    answers = parse_answer_tables(text)
    solutions, solution_warnings = parse_solutions(text)
    tasks: list[TaskDraft] = []
    missing: list[str] = []
    images_between = 0
    for variant in range(1, VARIANTS + 1):
        body = spans.get(variant)
        if body is None:
            missing.extend(locator(variant, n) for n in range(1, TASKS_PER_VARIANT + 1))
            continue
        markers, lost = task_markers(body)
        missing.extend(locator(variant, n) for n in lost)
        chunks = []  # [номер, сырой текст, рисунки после текста]
        for index, (number, _start, end) in enumerate(markers):
            stop = markers[index + 1][1] if index + 1 < len(markers) else len(body)
            own, gap = split_gap(body[end:stop], last=index + 1 == len(markers))
            chunks.append([number, own, gap])
        position = {number: index for index, (number, _own, _gap) in enumerate(chunks)}
        extra: dict[int, list[str]] = {}
        # Рисунок перед первым заданием (под заголовком варианта) — к №1.
        lead = IMAGE_RE.findall(body[:markers[0][1]]) if markers else []
        if lead:
            chunks[0][2] = lead + chunks[0][2]
            gap_from = {name: -1 for name in lead}
        else:
            gap_from = {}
        for index, chunk in enumerate(chunks):
            number, own = chunk[0], chunk[1]
            # Рисунок посреди чужого текста: владелец по геометрии скана.
            for name in IMAGE_RE.findall(own):
                key = owners.get(name)
                if key and key != locator(variant, number):
                    target = position[int(key.split("/")[1])]
                    own = re.sub(r"(?:\\item\[\]\s*)?\\includegraphics(?:\[[^\]]*\])?\{"
                                 + re.escape(name) + r"\}", "", own)
                    extra.setdefault(target, []).append(name)
                    relocated.append(name)
            chunk[1] = own
        for index, (number, own, gap) in enumerate(chunks):
            for name in gap:
                key = owners.get(name)
                if key:
                    target = position[int(key.split("/")[1])]
                else:
                    target = 0 if gap_from.get(name) == -1 else gap_owner(chunks, index)
                    guessed.append(f"{locator(variant, chunks[target][0])}: {name}")
                extra.setdefault(target, []).append(name)
                if target != index:
                    images_between += 1
        for figure in derived:
            if figure.get("replaces") or not figure.get("task"):
                continue
            v, n = figure["task"][1:].split("/")
            if int(v) == variant and int(n) in position:
                extra.setdefault(position[int(n)], []).append(figure["name"])
        for index, (number, own, _gap) in enumerate(chunks):
            task = build_task(variant, number, own, extra.get(index, []))
            attach_answer(task, answers.get(variant, {}).get(number, ""))
            solved = solutions.get((variant, number))
            if solved:
                task.author_solution_latex = solved["solution"]
            polish(task)
            finalize_draft_images(task)
            # Правки сверены по готовым полям (с \\taskpic{N}) — после нумерации.
            task_fixes = fixes.pop(task.external_id, [])
            for fix in task_fixes:
                apply_text_fix(task, fix)
                fixed += 1
            if task_fixes:
                prune_images(task)
                if (not task.author_answer_latex
                        and any(item.author_answer_latex for item in task.subitems)):
                    task.warnings = [w for w in task.warnings
                                     if w != "Ответ не разделён по подпунктам"]
            final_cleanup(task)
            apply_masks(task, masks)
            tasks.append(task)
    by_number = Counter(int(task.source_number) for task in tasks)
    diagnostics = {
        "source_repairs_applied": source_repairs,
        "variants": len(spans),
        "unique_tasks": len(tasks),
        "missing_task_ids": missing,
        "tasks_by_exam": {str(k): v for k, v in sorted(by_number.items())},
        "answer_tables": len(answers),
        "solutions": len(solutions),
        "solution_warnings": solution_warnings + [
            f"{task.external_id}: нет решения" for task in tasks
            if int(task.external_id[1:].split("/")[0]) in SOLVED_VARIANTS
            and int(task.source_number) >= 14 and not task.author_solution_latex],
        "edition": edition.get("title", ""),
        "text_fixes_applied": fixed,
        "text_fixes_unused": sorted(fixes),
        "images_between_tasks": images_between,
        "images_relocated_by_geometry": relocated,
        "images_guessed": guessed,
        "derived_figures": [f["name"] for f in derived],
        "solution_conditions": {
            locator(v, n): item["condition"] for (v, n), item in solutions.items()},
    }
    return tasks, diagnostics

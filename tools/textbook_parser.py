#!/usr/bin/env python3
"""Черновой ETL для OCR-LaTeX математических задач.

Команда ничего не пишет в Django DB. Она выделяет задачи и авторские
ответы/решения в проверяемый JSON, а также формирует TSV и Markdown-отчёт.
Профили отражают структуру конкретных семейств книг; сомнительные случаи
остаются в warnings и требуют ручной проверки.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence


SCHEMA_VERSION = 1
ANSWER_HEADING_RE = re.compile(
    r"\\section\*?\{\s*ОТВЕТЫ\s*,?\s*(?:УКАЗАН\s*ИЯ|УКАЗАНИЯ)?\s*,?\s*"
    r"(?:РЕШЕНИЯ)?\s*\}",
    re.IGNORECASE,
)
SECTION_COMMAND_RE = re.compile(r"\\(?P<level>section|subsection|subsubsection)\*?\{")
ALPHA_ITEM_RE = re.compile(r"\\item\[\s*(?P<label>[a-zа-яё0-9]+)\s*\)\s*\]", re.I)
PLAIN_ALPHA_ITEM_RE = re.compile(
    r"(?im)(?:^|(?<=\\\\)|(?<=\n))[ \t]*"
    r"(?P<label>[a-zа-яё0-9]+)\)\s*")
BLOCK_WRAPPER_RE = re.compile(
    r"\\(?:begin|end)\{(?:itemize|enumerate|document)\}")
LIST_ENV_RE = re.compile(
    r"\\(?P<action>begin|end)\{(?:itemize|enumerate)\}")
EMPTY_ITEM_RE = re.compile(r"\\item\[\s*\]")
ANY_ITEM_RE = re.compile(
    r"\\item(?:\[\s*(?P<label>[^]]+?)\s*\])?[ \t]*")
RAW_IMAGE_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^]]*\])?\s*\{(?P<path>[^{}]+)\}")
TASK_IMAGE_RE = re.compile(
    r"\\(?:includegraphics|taskpic)\s*(?:\[[^]]*\])?\s*"
    r"\{(?P<path>[^{}]+)\}")
FLOAT_WRAPPER_RE = re.compile(
    r"\\(?:begin|end)\{(?:figure|center)\}(?:\[[^]]*\])?")
FLOAT_META_COMMAND_RE = re.compile(
    r"\\(?:captionsetup|caption)\s*\{")
STRUCTURAL_HEADING_RE = re.compile(
    r"\\(?:sub)*section\*?\{[^{}]*\}")
OCR_FIGURE_WRAPPER_RE = re.compile(
    r"\\textbackslash\s+(?:begin|end)\\?\{figure\\?\}(?:\\\\)?")


@dataclass
class SubitemDraft:
    label: str
    text_latex: str
    author_answer_latex: str = ""
    author_solution_latex: str = ""


@dataclass
class TaskDraft:
    external_id: str
    source_number: str
    source_path: list[str]
    collection_key: str
    collection_title: str
    topic_original: str
    text_latex: str
    stars: int = 0
    subitems: list[SubitemDraft] = field(default_factory=list)
    author_answer_latex: str = ""
    author_solution_latex: str = ""
    images: list[str] = field(default_factory=list)
    confidence: float = 1.0
    review_status: str = "needs_review"
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportBundle:
    schema_version: int
    profile: str
    source: dict
    tasks: list[TaskDraft]
    diagnostics: dict


@dataclass(frozen=True)
class Marker:
    start: int
    end: int
    external_id: str
    kind: str = ""


@dataclass(frozen=True)
class Section:
    start: int
    end: int
    level: str
    title: str


def read_group(text: str, open_pos: int) -> tuple[str, int]:
    """Читает сбалансированную {...}; команды и escaped braces учитываются."""
    if open_pos >= len(text) or text[open_pos] != "{":
        raise ValueError("Ожидалась открывающая фигурная скобка")
    depth = 1
    i = open_pos + 1
    start = i
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    raise ValueError(f"Незакрытая группа в позиции {open_pos}")


def remove_group_commands(text: str, pattern: re.Pattern) -> str:
    """Удаляет команды со сбалансированным {...} целиком."""
    spans = []
    for match in pattern.finditer(text):
        try:
            _, end = read_group(text, match.end() - 1)
        except ValueError:
            continue
        spans.append((match.start(), end))
    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    return text


def sections(text: str) -> list[Section]:
    result = []
    for match in SECTION_COMMAND_RE.finditer(text):
        try:
            title, end = read_group(text, match.end() - 1)
        except ValueError:
            continue
        result.append(Section(match.start(), end, match.group("level"), clean(title)))
    return result


def clean(value: str) -> str:
    value = re.sub(r"%\s*\n", "\n", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    # \\task пакета egor имеет не-long опциональные
    # аргументы: пустая строка в подпункте обрывает сборку PDF.
    value = re.sub(r"\n\s*\n+", "\n", value)
    return value.strip()


def strip_outer_lists(value: str, *, flatten_items: bool = True) -> str:
    value = BLOCK_WRAPPER_RE.sub("", value)
    value = EMPTY_ITEM_RE.sub("", value)
    if flatten_items:
        value = ANY_ITEM_RE.sub(
            lambda match: (
                " " + clean(match.group("label") or "") + "~"
                if match.group("label") else " "),
            value,
        )
    return clean(value)


def path_at(all_sections: Sequence[Section], pos: int) -> list[str]:
    """Возвращает стек смысловых заголовков по уровням LaTeX."""
    ignored = {
        "УПРАЖНЕНИЯ", "УРОВЕНЬ А", "УРОВЕНЬ В", "УРОВЕНЬ B",
        "УРОВЕНЬ С", "УРОВЕНЬ C", "УРОВЕНЬ D", "ГЛАВА",
    }
    level_index = {"section": 0, "subsection": 1, "subsubsection": 2}
    stack: list[str | None] = [None, None, None]
    for item in all_sections:
        if item.start >= pos:
            break
        normalized = re.sub(r"\s+", " ", item.title).strip().upper()
        if normalized in ignored or normalized.isdigit():
            continue
        if "ОГЛАВЛЕНИ" in normalized or "ПРЕДИСЛОВ" in normalized:
            continue
        index = level_index[item.level]
        stack[index] = item.title
        for deeper in range(index + 1, len(stack)):
            stack[deeper] = None
    return [title for title in stack if title]


def _subitem_marker_data(body: str) -> list[tuple[int, int, str, int]]:
    markers = [
        (match.start(), match.end(), match.group("label"))
        for match in ALPHA_ITEM_RE.finditer(body)
    ]
    for match in PLAIN_ALPHA_ITEM_RE.finditer(body):
        start = match.start()
        if body[max(0, start - 2):start] == r"\\":
            start -= 2
        markers.append((start, match.end(), match.group("label")))
    markers.sort(key=lambda item: item[0])
    events = list(LIST_ENV_RE.finditer(body))
    event_index = 0
    depth = 0
    markers_with_depth = []
    for marker in markers:
        while (event_index < len(events)
               and events[event_index].start() < marker[0]):
            if events[event_index].group("action") == "begin":
                depth += 1
            else:
                # Блок задачи может начинаться внутри внешнего itemize,
                # открытого до её маркера: не уходим в отрицательную глубину.
                depth = max(0, depth - 1)
            event_index += 1
        markers_with_depth.append((*marker, depth))
    return markers_with_depth


def split_subitems(body: str) -> tuple[str, list[SubitemDraft]]:
    marker_data = _subitem_marker_data(body)
    markers = []
    if marker_data:
        min_depth = min(marker[3] for marker in marker_data)
        markers = [marker[:3] for marker in marker_data
                   if marker[3] == min_depth]
        letter_markers = [
            marker for marker in marker_data
            if marker[2].isalpha() or marker[2] == "6"
        ]
        if letter_markers:
            letter_depth = min(marker[3] for marker in letter_markers)
            shallow_letters = [
                marker for marker in letter_markers
                if marker[3] == letter_depth
            ]
            # OCR иногда ошибочно вкладывает б) в список
            # числовых пунктов а); поднимаем один уровень, только
            # если на минимальной глубине нет пары буквенных меток.
            deeper_letters = [
                marker for marker in letter_markers
                if marker[3] == letter_depth + 1
            ]
            can_promote_pair = (
                len(shallow_letters) == 1
                and len(deeper_letters) == 1
                and shallow_letters[0][2].lower() in {"a", "а"}
                and deeper_letters[0][2].lower() in {"b", "б", "6"}
            )
            chosen_letters = (
                shallow_letters if len(shallow_letters) >= 2
                else shallow_letters + deeper_letters
                if can_promote_pair else []
            )
            if letter_depth == min_depth and len(chosen_letters) >= 2:
                markers = [marker[:3] for marker in chosen_letters]
    # Один item часто является оболочкой OCR, а не настоящим подпунктом.
    if len(markers) < 2:
        return strip_outer_lists(body), []
    parent = strip_outer_lists(body[:markers[0][0]])
    items = []
    for i, (start, marker_end, label) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(body)
        text = strip_outer_lists(body[marker_end:end])
        if text:
            items.append(SubitemDraft(label, text))
    return parent, items


def detach_column_tail(body: str) -> tuple[str, str]:
    """Отделяет вложенный хвост соседней колонки после пары а/б."""
    marker_data = _subitem_marker_data(body)
    if not marker_data:
        return body, ""
    min_depth = min(marker[3] for marker in marker_data)
    top = [marker for marker in marker_data if marker[3] == min_depth]
    if len(top) < 2:
        return body, ""
    detachable_labels = {"a", "b", "а", "б", "6"}
    top_labels = {
        marker[2].lower() for marker in top
        if marker[2].lower() in detachable_labels
    }
    for start, marker_end, label, depth in marker_data:
        if (start > top[-1][0] and depth > min_depth
                and label.lower() in top_labels):
            container_start = body.rfind(
                r"\begin{itemize}", top[-1][1], start)
            if container_start < 0:
                container_start = start
            detached = strip_outer_lists(body[container_start:])
            detached = ALPHA_ITEM_RE.sub(
                lambda match: r"\\ " + match.group("label") + ") ",
                detached)
            return body[:container_start], detached
    return body, ""


def extract_images(body: str) -> list[str]:
    return list(dict.fromkeys(re.findall(
        r"\\(?:includegraphics|taskpic)\s*(?:\[[^]]*\])?\s*\{([^{}]+)\}", body
    )))


def normalize_task_images(body: str) -> tuple[str, list[str]]:
    """Заменяет OCR-float на штатные \\taskpic{N}."""
    images = list(dict.fromkeys(
        match.group("path") for match in TASK_IMAGE_RE.finditer(body)))
    positions = {path: index + 1 for index, path in enumerate(images)}
    body = TASK_IMAGE_RE.sub(
        lambda match: rf"\taskpic{{{positions[match.group('path')]}}}",
        body,
    )
    body = FLOAT_WRAPPER_RE.sub("", body)
    body = remove_group_commands(body, FLOAT_META_COMMAND_RE)
    return body, images


def task_from_block(marker: Marker, body: str, source_path: list[str]) -> TaskDraft:
    body, images = normalize_task_images(body)
    text, subitems = split_subitems(body)
    topic = source_path[-1] if source_path else ""
    warnings = []
    confidence = 1.0
    if len(re.sub(r"\\\w+|\s+", "", text)) < 8 and not subitems:
        warnings.append("Слишком короткое условие")
        confidence -= 0.35
    # В OCR Шестакова внешний itemize часто обозначает физическую колонку и
    # закономерно начинается в одном блоке задачи, а заканчивается в другом.
    # Проверяем только содержательные окружения нормализованного блока.
    structural_body = BLOCK_WRAPPER_RE.sub("", body)
    begin_envs = Counter(re.findall(r"\\begin\{([^{}]+)\}", structural_body))
    end_envs = Counter(re.findall(r"\\end\{([^{}]+)\}", structural_body))
    if begin_envs != end_envs:
        warnings.append("Несбалансированные LaTeX-окружения внутри блока")
        confidence -= 0.20
    return TaskDraft(
        external_id=marker.external_id,
        source_number=marker.external_id,
        source_path=source_path,
        collection_key="/".join(source_path),
        collection_title=topic,
        topic_original=topic,
        text_latex=text,
        subitems=subitems,
        images=images,
        confidence=max(0.0, confidence),
        warnings=warnings,
    )


def blocks(text: str, markers: Sequence[Marker]) -> Iterator[tuple[Marker, str]]:
    for i, marker in enumerate(markers):
        end = markers[i + 1].start if i + 1 < len(markers) else len(text)
        yield marker, text[marker.end:end]


SH_CODE_RE = re.compile(
    r"(?<![\w.])(?P<chapter>\d{1,2})\.(?P<section>\d{1,2})\.?(?:\\?\]|\})?\s*"
    r"(?P<level>[A-DАВСД])\s*(?P<number>\d{2})(?!\d)", re.I
)
LEVEL_TRANSLATION = str.maketrans({"А": "A", "В": "B", "С": "C", "Д": "D"})
SH_APPENDIX_RE = re.compile(
    r"(?im)^\s*(?:"
    r"\\section\*?\{\s*Приложение\s*3\.\s*"
    r"Примерные варианты экзаменационных работ\s*\}"
    r"|Экзаменационные работы по алгебре "
    r"для общеобразовательных классов)\s*$"
)


def trim_shestakov_appendix(text: str) -> tuple[str, bool]:
    """Отсекает экзаменационные варианты после основного задачника."""
    boundary = SH_APPENDIX_RE.search(text)
    if not boundary:
        return text, False
    return text[:boundary.start()], True


def _shestakov_marker(text: str, match: re.Match) -> Marker:
    level = match.group("level").upper().translate(LEVEL_TRANSLATION)
    code = (
        f'{int(match.group("chapter"))}.{int(match.group("section"))}.'
        f'{level}{match.group("number")}'
    )
    line_start = text.rfind("\n", 0, match.start()) + 1
    prefix = text[line_start:match.start()].strip()
    if re.fullmatch(r"\\(?:sub)*section\*?\{\s*", prefix):
        marker_end = match.end()
        closing = re.match(r"\s*\}", text[marker_end:])
        if closing:
            marker_end += closing.end()
        return Marker(line_start, marker_end, code, "heading")
    if re.fullmatch(r"\\caption\{\s*", prefix):
        figure_start = text.rfind(r"\begin{figure}", 0, line_start)
        prior_figure_end = text.rfind(r"\end{figure}", 0, line_start)
        if figure_start > prior_figure_end:
            # OCR иногда заменяет номер задачи подписью к первому рисунку.
            # Начинаем блок с figure, чтобы изображение осталось у задачи.
            return Marker(figure_start, figure_start, code, "caption")
        itemize_start = text.rfind(r"\begin{itemize}", 0, line_start)
        prior_itemize_end = text.rfind(r"\end{itemize}", 0, line_start)
        marker_end = match.end()
        closing = re.match(r"\s*\}", text[marker_end:])
        if closing:
            marker_end += closing.end()
        if itemize_start > prior_itemize_end:
            # В решебнике caption иногда заменяет заголовок задачи.
            return Marker(itemize_start, marker_end, code, "caption")
    if re.fullmatch(r"\\item\[\s*", prefix):
        return Marker(line_start, match.end(), code, "item")
    return Marker(match.start(), match.end(), code, "direct")


def shestakov_markers(text: str) -> list[Marker]:
    """Маркеры условий: начало строки, task-item или код в caption."""
    result = []
    for match in SH_CODE_RE.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start:match.start()].strip()
        if prefix and not (
                re.fullmatch(r"\\item\[\s*", prefix)
                or re.fullmatch(r"\\caption\{\s*", prefix)):
            continue
        result.append(_shestakov_marker(text, match))
    return result


def shestakov_solution_markers(text: str) -> list[Marker]:
    """В решебнике следующий код может стоять в конце предыдущей строки."""
    result = []
    for match in SH_CODE_RE.finditer(text):
        marker = _shestakov_marker(text, match)
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = len(text)
        prefix = text[line_start:match.start()].strip()
        suffix = text[match.end():line_end].strip()
        is_caption = bool(re.fullmatch(r"\\caption\{\s*", prefix))
        is_direct = not prefix
        is_heading = bool(re.fullmatch(
            r"\\(?:sub)*section\*?\{\s*", prefix))
        is_item_label = bool(re.fullmatch(r"\\item\[\s*", prefix))
        looks_like_reference = bool(re.search(
            r"(?i)\b(?:задач\w*|номер\w*)\s*$", prefix))
        is_inline_transition = (
            (not suffix or bool(re.fullmatch(r"\\\\", suffix)))
            and not looks_like_reference
            and (
                bool(re.match(r"\\item\[", prefix))
                or bool(re.match(
                    r"[a-zа-яё0-9]+\)\s*", prefix, re.I))
                or bool(re.search(r"(?i)\bОтвет\s*:", prefix))
            )
        )
        if not (is_direct or is_heading or is_item_label
                or is_caption or is_inline_transition):
            # Внутритекстовая ссылка на другую задачу не граница.
            continue
        if (is_caption and result
                and not text[result[-1].end:marker.start].strip()):
            # Подпись сразу после номера — рисунок текущего решения, а OCR-код
            # в caption часто ошибочно указывает номер следующей задачи.
            continue
        result.append(marker)
    return result


def shestakov_sort_key(code: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.([A-D])(\d+)", code)
    if not match:
        raise ValueError(f"Неканонический код Шестакова: {code}")
    return (
        int(match.group(1)), int(match.group(2)),
        ord(match.group(3)), int(match.group(4)),
    )


def expected_shestakov_ids() -> set[str]:
    """Полная каноническая сетка номеров, заявленная в структуре книги."""
    result = set()
    for chapter in range(1, 9):
        for section in range(1, 4):
            for level in "ABCD":
                for number in range(1, 11):
                    result.add(f"{chapter}.{section}.{level}{number:02d}")
    for level in "ABCD":
        for number in range(1, 11):
            result.add(f"9.1.{level}{number:02d}")
            result.add(f"11.1.{level}{number:02d}")
    for section in range(1, 4):
        for level in "ABCD":
            for number in range(1, 16):
                result.add(f"10.{section}.{level}{number:02d}")
    return result


def numeric_markers(text: str, allowed: set[str] | None = None) -> list[Marker]:
    """Номера вида 1.23 в начале строки или label элемента списка."""
    pattern = re.compile(
        r"(?m)(?:^\s*|\\item\[\s*)(?P<number>\d{1,2}\.\d{1,3})\."
        r"(?:\s*\]|\s+)"
    )
    result = []
    for match in pattern.finditer(text):
        number = match.group("number")
        if allowed is None or number in allowed:
            result.append(Marker(match.start(), match.end(), number))
    return result


def inline_numeric_markers(text: str, allowed: set[str]) -> list[Marker]:
    """Маркеры плотного раздела ответов: ``1.1. 2. 1.2. 69.``."""
    if not allowed:
        return []
    alternatives = "|".join(
        re.escape(value) for value in sorted(allowed, key=len, reverse=True)
    )
    pattern = re.compile(rf"(?<![\w.])(?P<number>{alternatives})\.(?=\s)")
    return [
        Marker(match.start(), match.end(), match.group("number"))
        for match in pattern.finditer(text)
    ]


def item_markers(text: str) -> list[Marker]:
    pattern = re.compile(r"\\item\[\s*(?P<number>\d{1,2})\.\s*\]")
    return [Marker(m.start(), m.end(), m.group("number")) for m in pattern.finditer(text)]


def unique_markers(markers: Iterable[Marker]) -> tuple[list[Marker], set[str]]:
    counts = Counter(item.external_id for item in markers)
    duplicates = {key for key, count in counts.items() if count > 1}
    seen = set()
    result = []
    for item in markers:
        if item.external_id in seen:
            continue
        seen.add(item.external_id)
        result.append(item)
    return result, duplicates


def split_answer_solution(body: str) -> tuple[str, str]:
    """Делит компактный ответ и решение без потери исходного LaTeX.

    Редкие авторские указания считаются частью решения: отдельного поля для
    них нет, а порядок «Указание … Решение …» сохраняется как в источнике.
    """
    body = strip_outer_lists(body)
    solution_match = re.search(r"(?i)(?:Решени[ея]|Доказательство)\s*[:.]", body)
    hint_match = re.search(r"(?i)У\s*к\s*а\s*з\s*а\s*н\s*и\s*[ея]\s*[:.]", body)
    cut_points = [m.start() for m in (solution_match, hint_match) if m]
    answer_end = min(cut_points) if cut_points else len(body)
    answer = clean(body[:answer_end])
    solution = clean(body[min(cut_points) :]) if cut_points else ""
    explicit = re.search(r"(?is)\bОтвет\s*:\s*(.+?)(?:\n\s*\n|$)", body)
    if explicit:
        answer = clean(explicit.group(1))
    return answer, solution


def split_full_solution(body: str) -> tuple[str, str]:
    """Для отдельного решебника сохраняет весь блок как авторское решение."""
    solution = strip_outer_lists(body, flatten_items=False)
    solution = STRUCTURAL_HEADING_RE.sub("", solution)
    solution = FLOAT_WRAPPER_RE.sub("", solution)
    solution = OCR_FIGURE_WRAPPER_RE.sub("", solution)
    solution = remove_group_commands(solution, FLOAT_META_COMMAND_RE)
    solution = RAW_IMAGE_RE.sub(
        lambda match: rf"\taskpic{{{match.group('path')}}}", solution)
    solution = solution.lstrip("} \t\n")
    item_number = 0

    def replace_item(match: re.Match) -> str:
        nonlocal item_number
        item_number += 1
        label = clean(match.group("label") or "")
        prefix = "" if item_number == 1 else r" \mbox{}\\ "
        return prefix + (label + "~" if label else "")

    # \\item вне itemize ломает PDF; метки оставляем как
    # обычный текст с явным переносом между пунктами.
    solution = clean(ANY_ITEM_RE.sub(replace_item, solution))
    # Голые \\ по краям minipage дают `no line here to end`.
    solution = re.sub(r"^(?:\\\\\s*)+", "", solution)
    solution = re.sub(r"(?:\s*\\\\)+$", "", solution)
    answers = [
        clean(match.group(1))
        for match in re.finditer(
            r"(?im)\bОтвет\s*:\s*(.+?)(?:\\\\)?\s*$", solution)
        if clean(match.group(1))
    ]
    return "\n".join(answers), solution


def merge_solutions(
        tasks: list[TaskDraft], solution_text: str, marker_factory,
        *, full_solutions: bool = False) -> dict:
    raw_solution_markers = marker_factory(solution_text)
    task_ids = {task.external_id for task in tasks}
    ignored_solution_code_refs = sorted({
        marker.external_id for marker in raw_solution_markers
        if marker.external_id not in task_ids
    })
    allowed_markers = [marker for marker in raw_solution_markers
                       if marker.external_id in task_ids]
    counts = Counter(marker.external_id for marker in allowed_markers)
    duplicate_solutions = {
        key for key, count in counts.items() if count > 1
    }
    all_solution_markers = []
    for marker in raw_solution_markers:
        if (all_solution_markers
                and all_solution_markers[-1].external_id == marker.external_id
                and all_solution_markers[-1].kind == "caption"
                and marker.kind == "caption"):
            # Повтор caption с тем же кодом — продолжение того же решения.
            continue
        all_solution_markers.append(marker)
    solution_map = {}
    # Повторный маркер всё равно участвует в границах блока: иначе его текст
    # будет ошибочно приклеен к предыдущему решению. Для самого ключа
    # консервативно сохраняем первое вхождение и отправляем дубль на проверку.
    splitter = split_full_solution if full_solutions else split_answer_solution
    for marker, body in blocks(solution_text, all_solution_markers):
        if marker.external_id not in task_ids:
            continue
        images = extract_images(body) if full_solutions else []
        answer, solution = splitter(body)
        solution_map.setdefault(
            marker.external_id, (answer, solution, images))
    matched = 0
    for task in tasks:
        found = solution_map.get(task.external_id)
        if not found:
            task.warnings.append("Не найден авторский ответ/решение")
            task.confidence = max(0.0, task.confidence - 0.15)
            continue
        (task.author_answer_latex, task.author_solution_latex,
         solution_images) = found
        task.images.extend(
            image for image in solution_images if image not in task.images)
        for image in solution_images:
            task.author_solution_latex = task.author_solution_latex.replace(
                rf"\taskpic{{{image}}}",
                rf"\taskpic{{{task.images.index(image) + 1}}}",
            )
        matched += 1
    return {
        "solution_marker_occurrences": len(allowed_markers),
        "solution_boundaries": len(all_solution_markers),
        "solution_markers": len(solution_map),
        "duplicate_solution_ids": sorted(duplicate_solutions),
        "matched_solutions": matched,
        "unmatched_solution_ids": sorted(set(solution_map) - task_ids),
        "ignored_solution_code_refs": ignored_solution_code_refs,
        "tasks_without_solution_ids": sorted(task_ids - set(solution_map)),
    }


def parse_shestakov(tasks_text: str, solutions_text: str) -> tuple[list[TaskDraft], dict]:
    tasks_text, tasks_truncated = trim_shestakov_appendix(tasks_text)
    solutions_text, solutions_truncated = trim_shestakov_appendix(
        solutions_text)
    all_markers = shestakov_markers(tasks_text)
    marker_counts = Counter(marker.external_id for marker in all_markers)
    duplicate_tasks = {
        key for key, count in marker_counts.items() if count > 1
    }
    headings = sections(tasks_text)
    raw_blocks = [[marker, body]
                  for marker, body in blocks(tasks_text, all_markers)]
    detached_column_fragments = []
    for index in range(1, len(raw_blocks)):
        previous_marker, previous_body = raw_blocks[index - 1]
        marker, body = raw_blocks[index]
        if (shestakov_sort_key(marker.external_id)
                >= shestakov_sort_key(previous_marker.external_id)):
            continue
        main, detached = detach_column_tail(body)
        if not detached:
            continue
        previous_body = re.sub(
            r"\\begin\{itemize\}\s*$", "", previous_body)
        raw_blocks[index - 1][1] = previous_body + "\n" + detached
        raw_blocks[index][1] = main
        detached_column_fragments.append({
            "from": marker.external_id,
            "to": previous_marker.external_id,
        })
    tasks = []
    seen = set()
    for marker, body in raw_blocks:
        if marker.external_id in seen:
            continue
        seen.add(marker.external_id)
        tasks.append(task_from_block(
            marker, body, path_at(headings, marker.start)))
    # Падение номера в линейном потоке часто означает склейку двух колонок OCR.
    previous = None
    previous_task = None
    physical_order_break_ids = []
    physical_order_affected_ids = set()
    for task in tasks:
        key = shestakov_sort_key(task.external_id)
        if previous is not None and key < previous:
            physical_order_break_ids.append(task.external_id)
            physical_order_affected_ids.update(
                [previous_task.external_id, task.external_id])
        previous = key
        previous_task = task
    boundary_warning = (
        "Нарушен порядок номеров рядом с задачей: проверить границу колонок OCR")
    for task in tasks:
        if task.external_id in physical_order_affected_ids:
            task.warnings.append(boundary_warning)
            task.confidence = max(0.0, task.confidence - 0.25)
    tasks.sort(key=lambda task: shestakov_sort_key(task.external_id))
    parsed_ids = {task.external_id for task in tasks}
    expected_ids = expected_shestakov_ids()
    diagnostics = {
        "task_marker_occurrences": len(all_markers),
        "unique_tasks": len(tasks),
        "duplicate_task_ids": sorted(duplicate_tasks),
        "physical_order_break_ids": physical_order_break_ids,
        "physical_order_affected_ids": sorted(
            physical_order_affected_ids, key=shestakov_sort_key),
        "detached_column_fragments": detached_column_fragments,
        "missing_task_ids": sorted(
            expected_ids - parsed_ids, key=shestakov_sort_key),
        "unexpected_task_ids": sorted(
            parsed_ids - expected_ids, key=shestakov_sort_key),
        "tasks_truncated_before_exam_variants": tasks_truncated,
        "solutions_truncated_before_exam_variants": solutions_truncated,
    }
    solution_diagnostics = merge_solutions(
        tasks, solutions_text, shestakov_solution_markers,
        full_solutions=True)
    diagnostics.update(solution_diagnostics)
    raw_solution_ids = {
        marker.external_id for marker in shestakov_solution_markers(
            solutions_text)
    }
    unbounded_next_ids = set(solution_diagnostics[
        "tasks_without_solution_ids"])
    unbounded_next_ids.update(
        (expected_ids - parsed_ids) - raw_solution_ids)
    by_key = sorted(
        ((shestakov_sort_key(task.external_id), task) for task in tasks),
        key=lambda item: item[0],
    )
    suspicious_predecessors: dict[str, list[str]] = {}
    for missing_id in sorted(unbounded_next_ids, key=shestakov_sort_key):
        missing_key = shestakov_sort_key(missing_id)
        prior = [task for key, task in by_key if key < missing_key]
        if not prior or not prior[-1].author_solution_latex:
            continue
        suspicious_predecessors.setdefault(
            prior[-1].external_id, []).append(missing_id)
    task_by_id = {task.external_id: task for task in tasks}
    for prior_id, next_ids in suspicious_predecessors.items():
        task = task_by_id[prior_id]
        task.warnings.append(
            "У следующего номера нет границы решения ("
            + ", ".join(next_ids)
            + "): проверить окончание авторского решения")
        task.confidence = max(0.0, task.confidence - 0.20)
    diagnostics["solution_boundary_review_predecessors"] = {
        key: value for key, value in sorted(
            suspicious_predecessors.items(),
            key=lambda item: shestakov_sort_key(item[0]))
    }
    return tasks, diagnostics


def parse_galitsky(text: str) -> tuple[list[TaskDraft], dict]:
    answer_heading = ANSWER_HEADING_RE.search(text)
    if not answer_heading:
        raise ValueError("Не найден раздел ответов Галицкого")
    task_text = text[: answer_heading.start()]
    answer_text = text[answer_heading.end() :]
    all_markers = numeric_markers(task_text)
    markers, duplicate_tasks = unique_markers(all_markers)
    headings = sections(task_text)
    tasks = [
        task_from_block(marker, body, path_at(headings, marker.start))
        for marker, body in blocks(task_text, markers)
    ]
    allowed = {task.external_id for task in tasks}
    diagnostics = {
        "task_marker_occurrences": len(all_markers),
        "unique_tasks": len(tasks),
        "duplicate_task_ids": sorted(duplicate_tasks),
    }
    diagnostics.update(merge_solutions(
        tasks, answer_text, lambda value: inline_numeric_markers(value, allowed)
    ))
    return tasks, diagnostics


def parse_ziv(text: str) -> tuple[list[TaskDraft], dict]:
    """Базовый профиль Зива.

    У Зива номер локален для пары тема/вариант, поэтому внешний ключ строится
    из последних заголовков и варианта. Профиль намеренно консервативен:
    повторные/неоднозначные ключи остаются в отчёте.
    """
    answer_heading = ANSWER_HEADING_RE.search(text)
    if not answer_heading:
        raise ValueError("Не найден раздел ответов Зива")
    task_text = text[: answer_heading.start()]
    heading_list = sections(task_text)
    variants = list(re.finditer(r"(?im)^\s*Вариант\s+(\d+)\s*$", task_text))
    raw_items = item_markers(task_text)

    def state_at(pos: int) -> tuple[list[str], str]:
        path = path_at(heading_list, pos)
        prior_variants = [m for m in variants if m.start() < pos]
        variant = prior_variants[-1].group(1) if prior_variants else "0"
        return path, variant

    synthetic = []
    for marker in raw_items:
        path, variant = state_at(marker.start)
        topic = path[-1] if path else "без-темы"
        slug = re.sub(r"[^а-яёa-z0-9]+", "-", topic.lower()).strip("-")
        synthetic.append(Marker(marker.start, marker.end, f"{slug}/v{variant}/{marker.external_id}"))
    markers, duplicates = unique_markers(synthetic)
    tasks = [
        task_from_block(marker, body, path_at(heading_list, marker.start))
        for marker, body in blocks(task_text, markers)
    ]
    for task in tasks:
        if task.external_id in duplicates:
            task.warnings.append("Неоднозначный локальный номер Зива")
            task.confidence = max(0.0, task.confidence - 0.35)
    return tasks, {
        "task_marker_occurrences": len(raw_items),
        "unique_tasks": len(tasks),
        "duplicate_task_ids": sorted(duplicates),
        "matched_solutions": 0,
        "note": "Сопоставление ответов Зива требует второго прохода по иерархии работа/тема/вариант.",
    }


def bundle_for(profile: str, tasks_path: Path, solutions_path: Path | None) -> ImportBundle:
    tasks_text = tasks_path.read_text(encoding="utf-8")
    if profile == "shestakov":
        if solutions_path is None:
            raise ValueError("Для профиля shestakov обязателен --solutions")
        tasks, diagnostics = parse_shestakov(
            tasks_text, solutions_path.read_text(encoding="utf-8")
        )
    elif profile == "galitsky":
        tasks, diagnostics = parse_galitsky(tasks_text)
    elif profile == "ziv":
        tasks, diagnostics = parse_ziv(tasks_text)
    else:
        raise ValueError(f"Неизвестный профиль: {profile}")
    review_counts = Counter(
        "clean" if not task.warnings else "warning" for task in tasks
    )
    diagnostics["review_counts"] = dict(review_counts)
    diagnostics["tasks_with_subitems"] = sum(bool(task.subitems) for task in tasks)
    diagnostics["tasks_with_images"] = sum(bool(task.images) for task in tasks)
    diagnostics["tasks_with_author_answer"] = sum(bool(task.author_answer_latex) for task in tasks)
    diagnostics["tasks_with_author_solution"] = sum(bool(task.author_solution_latex) for task in tasks)
    return ImportBundle(
        schema_version=SCHEMA_VERSION,
        profile=profile,
        source={
            "tasks_file": str(tasks_path.resolve()),
            "solutions_file": str(solutions_path.resolve()) if solutions_path else "",
        },
        tasks=tasks,
        diagnostics=diagnostics,
    )


def write_bundle(bundle: ImportBundle, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = asdict(bundle)
    (output / "import.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "review.tsv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow([
            "external_id", "source_number", "collection", "topic_original",
            "text_latex", "subitems", "stars", "author_answer_latex",
            "author_solution_latex", "confidence", "warnings", "review_status",
        ])
        for task in bundle.tasks:
            writer.writerow([
                task.external_id,
                task.source_number,
                task.collection_title,
                task.topic_original,
                task.text_latex,
                json.dumps([asdict(item) for item in task.subitems], ensure_ascii=False),
                task.stars,
                task.author_answer_latex,
                task.author_solution_latex,
                f"{task.confidence:.2f}",
                "; ".join(task.warnings),
                task.review_status,
            ])
    lines = [
        f"# Отчёт разбора: {bundle.profile}",
        "",
        f"- Найдено задач: {len(bundle.tasks)}",
        f"- С подпунктами: {bundle.diagnostics['tasks_with_subitems']}",
        f"- С авторским ответом: {bundle.diagnostics['tasks_with_author_answer']}",
        f"- С авторским решением: {bundle.diagnostics['tasks_with_author_solution']}",
        f"- С предупреждениями: {bundle.diagnostics['review_counts'].get('warning', 0)}",
    ]
    if "missing_task_ids" in bundle.diagnostics:
        lines.extend([
            f"- Пропущено ожидаемых номеров: "
            f"{len(bundle.diagnostics['missing_task_ids'])}",
            f"- Однозначно сопоставлено решений: "
            f"{bundle.diagnostics['matched_solutions']}",
            f"- Затронуто нарушениями порядка колонок: "
            f"{len(bundle.diagnostics['physical_order_affected_ids'])}",
        ])
    lines.extend([
        "", "## Диагностика", "", "```json",
        json.dumps(bundle.diagnostics, ensure_ascii=False, indent=2), "```",
    ])
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=("galitsky", "ziv", "shestakov"))
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--solutions", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bundle = bundle_for(args.profile, args.tasks, args.solutions)
    write_bundle(bundle, args.output)
    print(json.dumps(bundle.diagnostics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

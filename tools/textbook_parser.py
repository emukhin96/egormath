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
BEGIN_END_LIST_RE = re.compile(r"\\(?:begin|end)\{(?:itemize|enumerate)\}")


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
    return value.strip()


def strip_outer_lists(value: str) -> str:
    return clean(BEGIN_END_LIST_RE.sub("", value))


def path_at(all_sections: Sequence[Section], pos: int) -> list[str]:
    """Возвращает ближайшие смысловые заголовки до позиции задачи."""
    ignored = {
        "УПРАЖНЕНИЯ", "УРОВЕНЬ А", "УРОВЕНЬ В", "УРОВЕНЬ B",
        "УРОВЕНЬ С", "УРОВЕНЬ C", "УРОВЕНЬ D", "ГЛАВА",
    }
    preceding = [item for item in all_sections if item.start < pos]
    chosen: list[str] = []
    for item in preceding[-12:]:
        normalized = re.sub(r"\s+", " ", item.title).strip().upper()
        if normalized in ignored or normalized.isdigit():
            continue
        if "ОГЛАВЛЕНИ" in normalized or "ПРЕДИСЛОВ" in normalized:
            continue
        if item.title not in chosen:
            chosen.append(item.title)
    return chosen[-3:]


def split_subitems(body: str) -> tuple[str, list[SubitemDraft]]:
    markers = list(ALPHA_ITEM_RE.finditer(body))
    # Один item часто является оболочкой OCR, а не настоящим подпунктом.
    if len(markers) < 2:
        return strip_outer_lists(body), []
    parent = strip_outer_lists(body[: markers[0].start()])
    items = []
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(body)
        text = strip_outer_lists(body[marker.end() : end])
        if text:
            items.append(SubitemDraft(marker.group("label"), text))
    return parent, items


def extract_images(body: str) -> list[str]:
    return list(dict.fromkeys(re.findall(
        r"\\(?:includegraphics|taskpic)\s*(?:\[[^]]*\])?\s*\{([^{}]+)\}", body
    )))


def task_from_block(marker: Marker, body: str, source_path: list[str]) -> TaskDraft:
    text, subitems = split_subitems(body)
    topic = source_path[-1] if source_path else ""
    warnings = []
    confidence = 1.0
    if len(re.sub(r"\\\w+|\s+", "", text)) < 8 and not subitems:
        warnings.append("Слишком короткое условие")
        confidence -= 0.35
    if body.count(r"\begin{") != body.count(r"\end{"):
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
        images=extract_images(body),
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


def shestakov_markers(text: str) -> list[Marker]:
    result = []
    for match in SH_CODE_RE.finditer(text):
        level = match.group("level").upper().translate(LEVEL_TRANSLATION)
        code = f'{int(match.group("chapter"))}.{int(match.group("section"))}.{level}{match.group("number")}'
        result.append(Marker(match.start(), match.end(), code))
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


def merge_solutions(tasks: list[TaskDraft], solution_text: str, marker_factory) -> dict:
    solution_markers = marker_factory(solution_text)
    solution_markers, duplicate_solutions = unique_markers(solution_markers)
    solution_map = {}
    for marker, body in blocks(solution_text, solution_markers):
        solution_map[marker.external_id] = split_answer_solution(body)
    matched = 0
    for task in tasks:
        found = solution_map.get(task.external_id)
        if not found:
            task.warnings.append("Не найден авторский ответ/решение")
            task.confidence = max(0.0, task.confidence - 0.15)
            continue
        task.author_answer_latex, task.author_solution_latex = found
        matched += 1
    return {
        "solution_markers": len(solution_markers),
        "duplicate_solution_ids": sorted(duplicate_solutions),
        "matched_solutions": matched,
        "unmatched_solution_ids": sorted(set(solution_map) - {task.external_id for task in tasks}),
    }


def parse_shestakov(tasks_text: str, solutions_text: str) -> tuple[list[TaskDraft], dict]:
    all_markers = shestakov_markers(tasks_text)
    markers, duplicate_tasks = unique_markers(all_markers)
    headings = sections(tasks_text)
    tasks = [
        task_from_block(marker, body, path_at(headings, marker.start))
        for marker, body in blocks(tasks_text, markers)
    ]
    # Падение номера в линейном потоке часто означает склейку двух колонок OCR.
    previous = None
    for task in tasks:
        parts = re.match(r"(\d+)\.(\d+)\.([A-D])(\d+)", task.external_id)
        key = tuple(map(int, parts.group(1, 2))) + (ord(parts.group(3)), int(parts.group(4)))
        if previous is not None and key < previous:
            task.warnings.append("Нарушен порядок номеров: возможна склейка колонок OCR")
            task.confidence = max(0.0, task.confidence - 0.25)
        previous = key
    diagnostics = {
        "task_marker_occurrences": len(all_markers),
        "unique_tasks": len(tasks),
        "duplicate_task_ids": sorted(duplicate_tasks),
    }
    diagnostics.update(merge_solutions(tasks, solutions_text, shestakov_markers))
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
        "",
        "## Диагностика",
        "",
        "```json",
        json.dumps(bundle.diagnostics, ensure_ascii=False, indent=2),
        "```",
    ]
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

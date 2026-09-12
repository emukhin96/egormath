"""Извлечение авторских ответов ЕГЭ из OCR-TeX ключа.

PDF-слой хорошо устанавливает состав задач, но при линейном извлечении может
потерять структуру дроби или частей «а)», «б)», «в)». Здесь TeX используется
только для явно подписанных ячеек ключа: ответы без номера намеренно не
сопоставляются по порядку.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping


LOCATOR_RE = re.compile(r'^\d+\.\d+(?:\.\d+)?$')
MARKER_RE = re.compile(r'№\s*(\d+\.\d+(?:\.\d+)?)(?![.\d])')
TABULAR_RE = re.compile(
    r'\\begin\{tabular\}(?:\[[^]]*\])?\{[^}]*\}(.*?)\\end\{tabular\}',
    re.DOTALL)
FREE_MARKER_RE = re.compile(
    r'(?m)^\s*№\s*(?P<id>\d+\.\d+(?:\.\d+)?)(?![.\d])\s*'
    r'(?:\\\\)?\s*$')
MULTICOLUMN_RE = re.compile(
    r'^\\multicolumn\{\d+\}\{[^}]*\}\{(?P<value>.*)\}$', re.DOTALL)
ITEM_RE = re.compile(r'\\item\s*\[([^]]+)\]\s*')


def _canonical_id(value: object) -> str | None:
    candidate = str(value or '').strip().removeprefix('№').strip().rstrip('.')
    return candidate if LOCATOR_RE.fullmatch(candidate) else None


def _expected_ids(pdf_answers: Mapping, index: object) -> set[str]:
    """Возвращает подтверждённые индексом номера либо ключи PDF."""
    if isinstance(index, Mapping):
        tasks = index.get('tasks', index)
        if isinstance(tasks, Mapping):
            result = {_canonical_id(key) for key in tasks}
            return {key for key in result if key}
    result = {_canonical_id(key) for key in pdf_answers}
    return {key for key in result if key}


def _clean_value(value: str) -> str:
    """Удаляет только обёртку таблицы и типографскую точку вне формулы."""
    value = value.strip().replace('\n', ' ')
    # После нетабличного списка OCR часто оставляет навигационный центр.
    value = value.split(r'\end{itemize}', 1)[0]
    value = value.split(r'\begin{center}', 1)[0]
    value = re.sub(r'\\hline\s*$', '', value).strip()
    multicolumn = MULTICOLUMN_RE.fullmatch(value)
    if multicolumn:
        value = multicolumn.group('value').strip()
    value = re.sub(r'\\(?:quad|qquad|hspace\{[^}]*\})\s*$', '', value).strip()
    if value.endswith('.') and not value.endswith(r'$.'):
        value = value[:-1].rstrip()
    return value


def _is_complete(value: str) -> bool:
    if not value or 'Оглавление' in value or 'Ответы' in value:
        return False
    if r'\begin{' in value or r'\multicolumn{' in value:
        return False
    # Незакрытая математическая оболочка — признак обрезанной OCR-ячейки.
    if value.count(r'\(') != value.count(r'\)') or value.count('$') % 2:
        return False
    # Несколько «а)» означают потерю границ соседних OCR-ячеек.
    return len(re.findall(r'(?i)(?:^|\s)[аa]\)', value)) <= 1


def _table_candidates(tex: str) -> dict[str, list[str]]:
    """Читает пары «№id & ответ» из всех таблиц ключа."""
    found: dict[str, list[str]] = defaultdict(list)
    for table in TABULAR_RE.findall(tex):
        for row in table.split(r'\\'):
            if '№' not in row or '&' not in row or 'Оглавление' in row:
                continue
            markers = list(MARKER_RE.finditer(row))
            for position, marker in enumerate(markers):
                locator = marker.group(1)
                end = markers[position + 1].start() if position + 1 < len(markers) else len(row)
                tail = row[marker.end():end]
                cells = [cell.strip() for cell in tail.split('&')]
                value = next((cell for cell in cells if cell), '')
                value = _clean_value(value)
                if value:
                    found[locator].append(value)
    return found


def _free_candidates(tex: str) -> dict[str, list[str]]:
    """Читает подписанные нетабличные ответы с частями «а)», «б)», «в)»."""
    found: dict[str, list[str]] = defaultdict(list)
    markers = list(FREE_MARKER_RE.finditer(tex))
    for position, marker in enumerate(markers):
        end = markers[position + 1].start() if position + 1 < len(markers) else len(tex)
        # OCR не всегда завершает следующий номер тем же количеством '\\'.
        # Любой последующий «№id» всё равно закрывает текущую ячейку.
        next_labeled = MARKER_RE.search(tex, marker.end())
        if next_labeled:
            end = min(end, next_labeled.start())
        table_start = tex.find(r'\begin{tabular}', marker.end(), end)
        if table_start != -1:
            end = table_start
        value = tex[marker.end():end].strip()
        if value.startswith(r'\begin{itemize}'):
            value = re.sub(r'^\\begin\{itemize\}\s*', '', value)
            value = re.sub(r'\\end\{itemize\}\s*$', '', value).strip()
            value = ITEM_RE.sub(lambda item: item.group(1) + ' ', value)
        if not re.match(r'^(?:[а-яa-z]\)|\\item\s*\[[^]]+\])', value, re.I):
            continue
        value = _clean_value(value.rstrip(r'\\').strip())
        if value:
            found[marker.group('id')].append(value)
    return found


def _tex_candidates(tex: str) -> dict[str, list[str]]:
    """Объединяет варианты из ячеек таблиц и подписанных строк ключа."""
    candidates: dict[str, list[str]] = defaultdict(list)
    for source in (_table_candidates(tex), _free_candidates(tex)):
        for locator, values in source.items():
            candidates[locator].extend(values)
    return candidates


def _format_equivalent(tex_value: str, pdf_value: str) -> bool:
    """Сравнивает оболочки, пробелы и типографские варианты без алгебры."""
    def normalize(value: str) -> str:
        value = value.strip().replace('−', '-').replace('–', '-')
        value = value.replace('𝜋', r'\pi').replace('√', r'\sqrt')
        value = value.replace(r'\(', '').replace(r'\)', '').replace('$', '')
        value = re.sub(r'\s+', '', value).rstrip('.')
        return value

    return normalize(tex_value) == normalize(pdf_value)


def _pdf_answer_is_complex(value: str) -> bool:
    """Отмечает PDF-ответы, где плоский текст способен потерять математику."""
    plain = value.strip().strip('$').strip().rstrip('.')
    if re.fullmatch(r'[+-]?\d+(?:[,.]\d+)?', plain):
        return False
    if re.fullmatch(r'[+-]?\d+\s*:\s*[+-]?\d+', plain):
        return False
    return True


def _raster_answer_cells(tex: str) -> dict[str, list[str]]:
    """Возвращает OCR-имена изображений из явно подписанных ячеек ключа."""
    found: dict[str, list[str]] = defaultdict(list)
    for table in TABULAR_RE.findall(tex):
        for row in table.split(r'\\'):
            if '№' not in row or r'\includegraphics' not in row:
                continue
            for marker in MARKER_RE.finditer(row):
                paths = re.findall(r'\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}', row)
                found[marker.group(1)].extend(paths)
    return {locator: list(dict.fromkeys(paths))
            for locator, paths in found.items()}


def extract_ege_answers(tex: str, pdf_answers: Mapping[str, str], index=None):
    """Возвращает ``(answers, diagnostics)`` для связки ЕГЭ.

    При совпадающих вариантах берётся полный TeX-ответ. Разные полные варианты
    считаются конфликтом: TeX не угадывается, а при наличии используется PDF.
    ``index`` — словарь ``build_pdf_index``; он ограничивает ответы известными
    заданиями и делает список пропусков независимым от неполного PDF-ключа.
    """
    pdf = {
        locator: str(value).strip()
        for key, value in pdf_answers.items()
        if (locator := _canonical_id(key)) and str(value).strip()
    }
    raw_candidates = _tex_candidates(tex)
    candidates = {
        locator: [value for value in values if _is_complete(value)]
        for locator, values in raw_candidates.items()
    }
    candidates = {locator: values for locator, values in candidates.items()
                  if values}
    expected = _expected_ids(pdf, index)
    if not expected:
        # Индекс опционален: в автономном режиме не отбрасываем TeX-ключ.
        expected = set(pdf) | set(raw_candidates)
    answers: dict[str, str] = {}
    conflicts: dict[str, list[str]] = {}

    for locator in sorted(expected):
        values = list(dict.fromkeys(candidates.get(locator, [])))
        if len(values) == 1:
            answers[locator] = values[0]
        elif len(values) > 1:
            conflicts[locator] = values
            if locator in pdf:
                answers[locator] = pdf[locator]
        elif locator in pdf:
            answers[locator] = pdf[locator]

    changed_ids = {
        locator for locator, value in answers.items()
        if locator in candidates and locator in pdf and value != pdf[locator]
    }
    incomplete_ids = {
        locator for locator, values in raw_candidates.items()
        if any(not _is_complete(value) for value in values)
    }
    uncertain_ids = set(conflicts) | incomplete_ids
    raw_diagnostic_ids = changed_ids | uncertain_ids
    formatting_only_ids = {
        locator for locator in changed_ids
        if _format_equivalent(answers[locator], pdf[locator])
    }
    substantive_tex_change_ids = changed_ids - formatting_only_ids
    fallback_ids = {
        locator for locator in answers
        if locator not in candidates or locator in conflicts
    }
    uncertain_fallback_ids = {
        locator for locator in fallback_ids
        if _pdf_answer_is_complex(answers[locator])
    }
    raster_cells = _raster_answer_cells(tex)
    visual_transcription_ids = uncertain_fallback_ids.intersection(raster_cells)

    def by_exam(ids: set[str]) -> dict[str, int]:
        result: dict[str, int] = {}
        for locator in ids:
            number = locator.split('.', 1)[0]
            result[number] = result.get(number, 0) + 1
        return dict(sorted(result.items(), key=lambda item: int(item[0])))

    diagnostics = {
        'expected_ids': sorted(expected, key=lambda value: tuple(map(int, value.split('.')))),
        'tex_answer_ids': sorted(set(raw_candidates), key=lambda value: tuple(map(int, value.split('.')))),
        'tex_preferred_ids': sorted(
            set(answers).intersection(candidates).difference(conflicts),
            key=lambda value: tuple(map(int, value.split('.')))),
        'conflicts': conflicts,
        'incomplete_tex_ids': sorted(incomplete_ids,
                                     key=lambda value: tuple(map(int, value.split('.')))),
        'tex_uncertain_ids': sorted(uncertain_ids,
                                    key=lambda value: tuple(map(int, value.split('.')))),
        'tex_changed_ids': sorted(changed_ids,
                                  key=lambda value: tuple(map(int, value.split('.')))),
        'formatting_only_ids': sorted(formatting_only_ids,
                                      key=lambda value: tuple(map(int, value.split('.')))),
        'substantive_tex_change_ids': sorted(
            substantive_tex_change_ids,
            key=lambda value: tuple(map(int, value.split('.')))),
        # Не дублируем весь TeX-ключ: сохраняем только замены PDF и сомнения.
        'tex_raw_by_id': {
            locator: raw_candidates[locator]
            for locator in sorted(raw_diagnostic_ids,
                                  key=lambda value: tuple(map(int, value.split('.'))))
        },
        'missing_ids': sorted(expected - set(answers),
                              key=lambda value: tuple(map(int, value.split('.')))),
        'pdf_fallback_ids': sorted(fallback_ids,
                                   key=lambda value: tuple(map(int, value.split('.')))),
        'pdf_fallback_uncertain_ids': sorted(
            uncertain_fallback_ids,
            key=lambda value: tuple(map(int, value.split('.')))),
        'pdf_fallback_simple_ids': sorted(
            fallback_ids - uncertain_fallback_ids,
            key=lambda value: tuple(map(int, value.split('.')))),
        'raster_answer_cells': raster_cells,
        'visual_transcription_required_ids': sorted(
            visual_transcription_ids,
            key=lambda value: tuple(map(int, value.split('.')))),
        'residual_counts_by_exam': {
            'pdf_fallback': by_exam(fallback_ids),
            'uncertain_pdf_fallback': by_exam(uncertain_fallback_ids),
            'visual_transcription_required': by_exam(visual_transcription_ids),
        },
        'tex_answers_without_index': sorted(set(candidates) - expected,
                                              key=lambda value: tuple(map(int, value.split('.')))),
    }
    return answers, diagnostics

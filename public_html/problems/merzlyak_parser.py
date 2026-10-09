"""Профиль учебников Мерзляка (OCR Mathpix, ответы в конце книги).

Особенности семейства (проверено на «Геометрия. 9 класс, углублённый
уровень»):

- задачи нумеруются «§.N» (``1.12``, ``26.145``), между упражнениями лежит
  теория следующего параграфа, контрольные вопросы и итоги главы;
- пункты задач и ответов нумеруются цифрами ``1) 2) 3)``, а не буквами;
- почти каждый рисунок подписан «Рис. §.N», а в тексте задачи есть ссылка
  «(рис. §.N)»; рисунки к ответам подписаны «Рисунок к задаче §.N».
  OCR кладёт float-окружения куда придётся, поэтому картинки привязываются
  по подписям, а не по положению;
- раздел «Ответы и указания к упражнениям» — плотный поток
  ``§.N. ответ. Указание. …`` с OCR-склейками и ссылками вида
  «ключевой задачей 5.30.», которые нельзя принимать за границу ответа.

Модуль только выделяет задачи и авторские материалы в общий контракт
``TaskDraft``; заливка в базу и картинки из ZIP — общий конвейер.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Sequence

from .textbook_parser import (
    Marker, TaskDraft, _open_paren_depth, blocks, clean, finalize_draft_images,
    inline_numeric_markers, merge_solutions, numeric_subitem_labels,
    read_group, task_from_block)


# Оглавление учебника: глава → (название, {§: название}). Заголовки в OCR
# ненадёжны («\section*{§ з Теорема синусов}», «\section*{§}»), поэтому
# путь подборки строится по номеру параграфа из номера задачи.
MERZLYAK_GEOM9_STRUCTURE = {
    1: ("Глава 1. Решение треугольников", {
        1: "§ 1. Синус, косинус, тангенс и котангенс угла от 0° до 180°",
        2: "§ 2. Теорема косинусов",
        3: "§ 3. Теорема синусов",
        4: "§ 4. Решение треугольников",
        5: "§ 5. Формулы для нахождения площади треугольника",
    }),
    2: ("Глава 2. Правильные многоугольники", {
        6: "§ 6. Правильные многоугольники и их свойства",
        7: "§ 7. Длина окружности. Площадь круга",
    }),
    3: ("Глава 3. Декартовы координаты на плоскости", {
        8: "§ 8. Расстояние между двумя точками с данными координатами. "
           "Деление отрезка в данном отношении",
        9: "§ 9. Уравнение фигуры",
        10: "§ 10. Общее уравнение прямой",
        11: "§ 11. Уравнение прямой с угловым коэффициентом. Уравнение "
            "прямой, проходящей через две данные точки",
        12: "§ 12. Метод координат",
    }),
    4: ("Глава 4. Векторы", {
        13: "§ 13. Понятие вектора",
        14: "§ 14. Координаты вектора",
        15: "§ 15. Сложение и вычитание векторов",
        16: "§ 16. Умножение вектора на число. Применение векторов "
            "к решению задач",
        17: "§ 17. Скалярное произведение векторов",
    }),
    5: ("Глава 5. Преобразования фигур", {
        18: "§ 18. Преобразование (отображение) фигур",
        19: "§ 19. Движение. Параллельный перенос",
        20: "§ 20. Осевая симметрия",
        21: "§ 21. Центральная симметрия",
        22: "§ 22. Поворот",
        23: "§ 23. Гомотетия. Подобие фигур",
    }),
    6: ("Глава 6. Начальные сведения по стереометрии", {
        24: "§ 24. Прямая призма. Пирамида",
        25: "§ 25. Цилиндр. Конус. Шар",
    }),
    7: ("§ 26. Упражнения для повторения курса планиметрии", {
        26: "§ 26. Упражнения для повторения курса планиметрии",
    }),
}

ANSWERS_HEADING_RE = re.compile(
    r"\\section\*?\{\s*Ответы(?:\s+и\s+указания)?[^{}]*\}", re.I)
SECTION_RE = re.compile(r"\\(?:sub)*section\*?\{(?P<title>[^{}]*)\}")
FIGURE_RE = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.S)
CAPTION_RE = re.compile(r"\\caption\{(?P<caption>[^{}]*)\}")
GRAPHICS_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{(?P<path>[^{}\s\\]+)\}")
FIG_NUMBER_RE = re.compile(r"(?i)^\s*Рис\.?\s*(?P<num>\d{1,2}\.\d{1,3})\s*$")
ANSWER_FIG_RE = re.compile(
    r"(?i)^\s*Рисунок\s+к\s+задаче\s+(?P<num>\d{1,2}\.\d{1,3})\s*$")
# Часть составного рисунка: «б», «в» (OCR: «B», «e», «\(a\)») после «Рис. §.N».
FIG_PART_RE = re.compile(r"^\\?\(?\s*[абвгдеabcdeBE]\s*\\?\)?$")
TASK_NUMBER_RE = re.compile(r"^\d{1,2}\.\d{1,3}$")
# Номер задачи в начале строки: «2.1. Найдите…». OCR иногда теряет точку
# перед скобкой («\item[2.60] (Теорема Стюарта)») — её восстанавливает
# ``prepare_merzlyak_text``.
TASK_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?P<number>\d{1,2}\.\d{1,3})\.(?=\s)")
# Ссылка на рисунок в условии: «(рис. 13.12)», «на рисунке 3.6»,
# «рисунках 3.4 и 3.5». Номер уходит в \taskpic, слово остаётся.
FIG_REF_RE = re.compile(
    r"(?i)(?P<word>рис(?:ун[а-яё]*|[её])?\.?)\s*(?P<num>\d{1,2}\.\d{1,3})"
    r"(?P<more>(?:\s*(?:,|и)\s*\d{1,2}\.\d{1,3})*)")
FIG_REF_MORE_RE = re.compile(r"\d{1,2}\.\d{1,3}")
# Слова, после которых «5.30.» — ссылка на другую задачу, а не граница
# ответа.
REFERENCE_WORD_RE = re.compile(
    r"(?i)(?:задач\w*|теорем\w*|упражнен\w*|пример\w*|результат\w*|"
    r"решени[ея]|рис\w*\.?|§)\s*$")
CHAPTER_LABEL_RE = re.compile(r"(?im)^\s*[ПГ]?лава\s+\d+\.\s*")
# Строки-разделители уровней сложности и OCR-мусор.
JUNK_LINE_RE = re.compile(r"(?m)^[ \t]*[◇○●■□•\\\s]+$")
HEADING_STOP_WORDS = (
    "итоги главы", "определение", "теорема", "доказательство",
    "задача ", "пример ", "решение.", "когда сделаны уроки",
    "упражнения", "практические задания", "контрольные вопросы",
)
DEGREE_TEXT_RE = re.compile(r"(?<![\w{])(\d+(?:[.,]\d+)?)°")
MATH_SPAN_RE = re.compile(
    r"\$\$.*?\$\$|\\\[.*?\\\]|\$.*?\$|\\\(.*?\\\)", re.S)
UNIT_WORDS = {
    "cm": "см", "см": "см", "cм": "см", "сm": "см",
    "m": "м", "м": "м", "km": "км", "км": "км",
    "dm": "дм", "дм": "дм", "mm": "мм", "мм": "мм",
}
MATHRM_UNIT_RE = re.compile(
    r"\s*(?:\\mathrm\{~?(?P<unit>cm|см|cм|сm|m|м|km|км|dm|дм|mm|мм)\}"
    r"|(?<![\\\w])(?P<bare>см|км|дм|мм)(?![а-яё\w]))"
    r"(?P<power>\^\{[23]\})?"
    r"(?P<per>\s*/\s*\\mathrm\{~?(?:c|с|ч|мин|s)\})?")
PER_UNIT_WORDS = {"c": "с", "с": "с", "s": "с", "ч": "ч", "мин": "мин"}


def _unit_word(match: re.Match) -> str:
    unit = UNIT_WORDS[match.group("unit") or match.group("bare")]
    per = match.group("per")
    if per:
        unit += "/" + PER_UNIT_WORDS[re.search(r"\{~?([^}]+)\}", per).group(1)]
    return unit


def _known_titles(structure=None) -> set[str]:
    titles = set()
    if structure is None:
        structure = MERZLYAK_GEOM9_STRUCTURE
    for chapter_title, paragraphs in structure.values():
        titles.add(_normalize_title(chapter_title))
        for title in paragraphs.values():
            titles.add(_normalize_title(re.sub(r"^§\s*\d+\.\s*", "", title)))
    return titles


def _normalize_title(value: str) -> str:
    value = re.sub(r"\\\\|\\[a-zA-Z]+|[{}]", " ", str(value or ""))
    value = value.replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"[\s.]+", " ", value).strip().lower()


def _without_toc_page(title: str) -> str:
    """Убирает отточие и страницу, включая OCR без отточия."""
    return re.sub(r'(?:\s*\.{2,}\s*|\s+)\d+\s*$', '', title).strip()


def _book_structure(text: str) -> dict:
    """Сначала оглавление книги, затем узнаваемый справочник геометрии."""
    toc = re.search(r"\\section\*?\{\s*Оглавление\s*\}", text, re.I)
    if toc:
        tail = text[toc.end():]
        # Mathpix может оформить очередную главу оглавления как section.
        # Продолжаем её читать, но не захватываем справочник после оглавления.
        for following in SECTION_RE.finditer(tail):
            if not re.match(r'^[Гг]?лава\s+\d+\.', following.group('title').strip()):
                tail = tail[:following.start()]
                break
        tail = SECTION_RE.sub(lambda match: match.group('title'), tail)
        structure = {}
        chapter = None
        pending = None
        chapter_closed = False

        def finish():
            nonlocal pending, chapter
            if pending is not None and chapter is not None:
                number, parts = pending
                title = _without_toc_page(' '.join(parts))
                title = re.sub(r'\s+', ' ', clean(title)).strip()
                if title:
                    if chapter_closed:
                        chapter = max(structure, default=0) + 1
                        structure[chapter] = (f'§ {number}. {title}', {})
                    structure[chapter][1][number] = f'§ {number}. {title}'
            pending = None

        # Границы параграфов и глав непроницаемы даже при потере отточия.
        for raw in tail.replace(r'\\', '\n').splitlines():
            line = raw.strip()
            chapter_match = re.match(r'^[Гг]?лава\s+(\d+)\.?\s+(.+)$', line)
            paragraph_match = re.match(r'^§\s*(\d+)\.?\s+(.+)$', line)
            if chapter_match:
                finish()
                chapter_closed = False
                chapter = int(chapter_match[1])
                title = clean(_without_toc_page(chapter_match[2]))
                structure[chapter] = (f'Глава {chapter}. {title}', {})
            elif line.startswith('Итоги главы'):
                finish()
                chapter_closed = True
            elif paragraph_match:
                finish()
                pending = (int(paragraph_match[1]), [paragraph_match[2]])
            elif pending is not None and line:
                if line.startswith(('Итоги', r'\end', r'\begin')):
                    finish()
                else:
                    pending[1].append(line)
            if pending is not None and re.search(r'(?:\s|\.{2,})\d+\s*$', line):
                finish()
        finish()
        return structure

    # Служебные разделы после ответов не идентифицируют учебник.
    answers = ANSWERS_HEADING_RE.search(text)
    body = text[:answers.start()] if answers else text
    known = _known_titles()
    numbered = {
        number: _normalize_title(re.sub(r'^§\s*\d+\.\s*', '', title))
        for _, paragraphs in MERZLYAK_GEOM9_STRUCTURE.values()
        for number, title in paragraphs.items()
    }
    matches = set()
    for match in SECTION_RE.finditer(body):
        title = match.group('title').strip()
        paragraph = re.match(r'^§\s*(\d+)\.?\s+(.+)$', title)
        if paragraph:
            if numbered.get(int(paragraph[1])) == _normalize_title(paragraph[2]):
                return MERZLYAK_GEOM9_STRUCTURE
            title = paragraph[2]
        title = _normalize_title(title)
        if title in known:
            matches.add(title)
    return MERZLYAK_GEOM9_STRUCTURE if len(matches) >= 2 else {}


# --------------------------------------------------------------------------
# Сверенные правки конкретного OCR-издания
# --------------------------------------------------------------------------

REPAIRS_PATH = Path(__file__).with_name("data") / "merzlyak_repairs.json"


def apply_source_repairs(text: str, path: Path = REPAIRS_PATH) -> tuple[str, list[str]]:
    """Точечные правки OCR, сверенные с бумажной книгой.

    Файл правок привязан к sha256 исходного TEX: для другого скана они не
    применяются. Каждый фрагмент ``before`` обязан встречаться ровно один
    раз — иначе правка неоднозначна и это ошибка, а не тихий пропуск.
    """
    if not path.exists():
        return text, []
    spec = json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    editions = [spec] if "patches" in spec else spec.get("editions", [])
    applied = []
    for edition in editions:
        if edition.get("source_sha256") != digest:
            continue
        for patch in edition.get("patches", []):
            count = text.count(patch["before"])
            if count != 1:
                raise ValueError(
                    f"Сверенный фрагмент {patch['id']} встречается {count} раз")
            text = text.replace(patch["before"], patch["after"], 1)
            applied.append(patch["id"])
    return text, applied


# --------------------------------------------------------------------------
# Подготовка текста
# --------------------------------------------------------------------------

def _renumber_enumerate(text: str) -> str:
    """``\\item`` без метки внутри enumerate → ``\\item[k)]``."""
    out = []
    counters: list[int] = []
    pos = 0
    token_re = re.compile(
        r"\\begin\{enumerate\}|\\end\{enumerate\}|\\item(?!\[)(?![a-zA-Z])")
    for match in token_re.finditer(text):
        out.append(text[pos:match.start()])
        token = match.group(0)
        if token == r"\begin{enumerate}":
            counters.append(0)
            out.append(token)
        elif token == r"\end{enumerate}":
            if counters:
                counters.pop()
            out.append(token)
        elif counters:
            counters[-1] += 1
            out.append(rf"\item[{counters[-1]})]")
        else:
            out.append(token)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def _unwrap_footnotes(text: str) -> str:
    """``\\footnotetext{…}`` → абзац «(Сноска) …» без фигурных скобок."""
    out = []
    pos = 0
    for match in re.finditer(r"\\footnotetext\s*\{", text):
        if match.start() < pos:
            continue
        try:
            content, end = read_group(text, match.end() - 1)
        except ValueError:
            continue
        out.append(text[pos:match.start()])
        out.append("\n\n(Сноска) " + content.strip() + "\n\n")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _unwrap_task_sections(text: str) -> str:
    """``\\section*{18.1. Отметим …}`` → строка «18.1. Отметим …»."""
    pattern = re.compile(r"\\(?:sub)*section\*?\{(?=\s*\d{1,2}\.\d{1,3}\.?\s)")
    out = []
    pos = 0
    for match in pattern.finditer(text):
        try:
            title, end = read_group(text, match.end() - 1)
        except ValueError:
            continue
        if match.start() < pos:
            continue
        out.append(text[pos:match.start()])
        out.append("\n" + title.strip() + "\n")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _flatten_lists(text: str) -> str:
    """Разворачивает списки в строки «метка текст»: глубина OCR не значима."""
    text = re.sub(r"\\(?:begin|end)\{(?:itemize|enumerate)\}", "\n", text)
    text = re.sub(r"\\item\[\s*\]", "\n", text)
    text = re.sub(r"\\item\[\s*[-–—]\s*\]", "\n— ", text)
    text = re.sub(r"\\item\[\s*[□■◇○●•]\s*\]", "\n", text)
    text = re.sub(r"\\item\[\s*(?P<label>[^\[\]]*?)\s*\][ \t]*",
                  lambda m: "\n" + m.group("label") + " ", text)
    text = re.sub(r"\\item(?![a-zA-Z])[ \t]*", "\n", text)
    return text


def _tabular_cell(cell: str) -> str:
    """Ячейка таблицы для ``array``: формулы без скобок, слова в ``\\text``."""
    cell = cell.strip()
    if not cell:
        return ""
    multicolumn = re.match(
        r"^\\multicolumn\{(\d+)\}\{[^{}]*\}\{(?P<body>.*)\}$", cell, re.S)
    if multicolumn:
        span = int(multicolumn.group(1))
        return _tabular_cell(multicolumn.group("body")) + " &" * (span - 1)
    cell = re.sub(r"^\\\((.*)\\\)$", r"\1", cell, flags=re.S)
    if re.search(r"[А-Яа-яЁё]", cell):
        parts = []
        pos = 0
        for match in MATH_SPAN_RE.finditer(cell):
            if cell[pos:match.start()].strip():
                parts.append(r"\text{" + cell[pos:match.start()].strip() + "}")
            inner = match.group(0)
            parts.append(re.sub(r"^\\\((.*)\\\)$|^\$(.*)\$$", lambda m: m.group(1) or m.group(2) or "", inner, flags=re.S))
            pos = match.end()
        if cell[pos:].strip():
            parts.append(r"\text{" + cell[pos:].strip() + "}")
        return " ".join(parts)
    return cell


def _tabular_to_array(text: str) -> str:
    """``tabular`` OCR → выносная ``array``: её понимают и KaTeX, и LaTeX."""
    pattern = re.compile(
        r"\\begin\{tabular\}(?:\[[^\]]*\])?\{(?P<spec>[^{}]*)\}(?P<body>.*?)"
        r"\\end\{tabular\}", re.S)

    def convert(match: re.Match) -> str:
        body = match.group("body").replace("\\hline", " \\hline ")
        rows = []
        for row in re.split(r"\\\\", body):
            hline = ""
            while re.match(r"\s*\\hline", row):
                hline += r"\hline "
                row = re.sub(r"^\s*\\hline", "", row, count=1)
            cells = [_tabular_cell(cell) for cell in row.split("&")]
            if not any(cells) and not hline:
                continue
            rows.append(hline + " & ".join(cells))
        joined = " \\\\\n".join(row for row in rows if row.strip())
        joined = re.sub(r"\\hline\s*$", "", joined).rstrip()
        return (r"\[\begin{array}{" + match.group("spec") + "}\n"
                + joined + "\n\\hline\\end{array}\\]")

    return pattern.sub(convert, text)


def _join_hyphenation(text: str) -> str:
    """«Указа- ние» / «Точ- ки»: перенос строки OCR внутри слова."""
    return re.sub(r"(?<=[а-яё])-\s+(?=[а-яё])", "", text)


def _split_unit_math(text: str) -> str:
    """``\\(A B=5 \\mathrm{~cm}, B C=8 \\mathrm{~cm}\\)`` → «$AB=5$ см, …».

    Единица измерения — текст, число — математика (канон QA § 4.6).
    """
    def split_inline(inner: str) -> str:
        """Внутренность формулы → «\\(…\\) см \\(…\\)» без пустых формул."""
        def unit_text(m: re.Match) -> str:
            unit = _unit_word(m)
            power = m.group("power") or ""
            suffix = rf"\({power}\)" if power else ""
            return rf"\) {unit}{suffix} \("

        value = r"\(" + MATHRM_UNIT_RE.sub(unit_text, inner) + r"\)"
        value = re.sub(r"\\\(\s*\\\)", "", value)
        value = re.sub(r"\\\(\s*([,;.])\s*", r"\1 \\(", value)
        value = re.sub(r"\\\(\s*\\\)", "", value)
        value = re.sub(r"[ \t]+([,;.])", r"\1", value)
        return re.sub(r"[ \t]{2,}", " ", value).strip()

    def fix_span(match: re.Match) -> str:
        raw = match.group(0)
        if not MATHRM_UNIT_RE.search(raw):
            return raw
        if raw.startswith(r"\(") and raw.endswith(r"\)"):
            return split_inline(raw[2:-2])
        if raw.startswith("$") and raw.endswith("$") and not raw.startswith("$$"):
            return split_inline(raw[1:-1]).replace(r"\(", "$").replace(r"\)", "$")
        return MATHRM_UNIT_RE.sub(
            lambda m: r"\ \text{" + _unit_word(m) + "}"
            + (m.group("power") or ""), raw)

    return MATH_SPAN_RE.sub(fix_span, text)


def normalize_units(text: str) -> str:
    """Единицы измерения текстом, степень у единицы — в математике."""
    if not text:
        return text
    text = re.sub(r"\bс\s+м(?![а-яё])", "см", text)
    text = _split_unit_math(text)
    text = re.sub(r"(?<=\d)\s*cm(?![a-zа-яё])", " см", text)
    text = re.sub(r"(?<=\\\))\s*cm(?![a-zа-яё])", " см", text)
    text = re.sub(r"(?<=\$)\s*cm(?![a-zа-яё])", " см", text)
    text = re.sub(r"(?<=[а-яё])\s*\\\(\{\s*\}\^\{([23])\}\\\)", r"$^{\1}$", text)
    text = re.sub(r"(?<=[а-яё])\s*\$\{\s*\}\^\{([23])\}\$", r"$^{\1}$", text)
    text = re.sub(r"(?<=[\d$)])\s*H(?![\w])", " Н", text)
    # Знак сноски «\({ }^{1}\)» после слова — не степень и не формула.
    text = re.sub(r"(?<=[а-яё])\s*\\\(\{\s*\}\^\{1\}\\\)", "", text)
    text = text.replace("см²", "см$^{2}$").replace("см³", "см$^{3}$")
    return text


def normalize_degrees(text: str) -> str:
    """«120°» вне формулы → ``$120^{\\circ}$``, внутри формулы → ``^{\\circ}``."""
    if not text or "°" not in text:
        return text
    spans = [(m.start(), m.end()) for m in MATH_SPAN_RE.finditer(text)]
    out = []
    pos = 0
    for start, end in spans:
        out.append(DEGREE_TEXT_RE.sub(r"$\1^{\\circ}$", text[pos:start]))
        out.append(text[start:end].replace("°", r"^{\circ}"))
        pos = end
    out.append(DEGREE_TEXT_RE.sub(r"$\1^{\\circ}$", text[pos:]))
    return "".join(out)


def prepare_merzlyak_text(text: str) -> str:
    """Чистит типовой OCR-мусор Mathpix до разбора на задачи."""
    text = text.replace("\r\n", "\n")
    # Экранированные OCR команды: «\textbackslash item[5.36.]».
    text = re.sub(r"\\textbackslash\s+item", r"\\item", text)
    text = re.sub(r"\\textbackslash\s+(begin|end)\\\{(\w+)\\\}",
                  r"\\\1{\2}", text)
    # Задача, ставшая заголовком: «\section*{18.1. Отметим …}».
    text = _unwrap_task_sections(text)
    # Метка без точки: «\item[2.60] (Теорема Стюарта)».
    text = re.sub(r"\\item\[\s*(\d{1,2}\.\d{1,3})\s*\]", r"\\item[\1.]", text)
    # Сноски — обычный текст: их содержимое важно для задач («В задачах
    # 5.26–5.30 используется…»), а команда ломает разбор.
    text = _unwrap_footnotes(text)
    text = _renumber_enumerate(text)
    text = _flatten_lists(text)
    text = re.sub(r"\\\\\[0pt\]", "", text)
    text = JUNK_LINE_RE.sub("", text)
    text = re.sub(r"(?m)^[ \t]*[◇○●■□•]+(?:\s*[◇○●■□•]+)*\s*(?:\\\\)?\s*$", "", text)
    # «в точках A, B, C, D, M, N: 1\) ) равные» — метка «1)» вклеена
    # в формулу перед двоеточием.
    text = re.sub(r"([:;])\s*(\d{1,2})\\\)\s*\)", r"\)\1 \2)", text)
    # «\left.+(y-2)^{2}=25 ; 2\right)(x+1)…» — метка «2)» стала скобкой.
    text = re.sub(r"\\left\.(?P<body>[^\n]*?);\s*(?P<label>\d{1,2})\\right\)",
                  r"\g<body>\); \g<label>) \(", text)
    # «относительно: 1\()\) оси абсцисс» / «относительно: 1 ) начала» —
    # скобка метки ушла в пустую формулу или оторвалась пробелом.
    text = _heal_numeric_item_labels(text)
    text = _tabular_to_array(text)
    text = _join_hyphenation(text)
    text = re.sub(r"\bс\s+м(?![а-яё])", "см", text)
    # «точка ( \(0 ;-8\) )» — скобки координат вынесены из формулы.
    text = re.sub(r"\(\s*\\\(([^()]*?)\\\)\s*\)", r"\\((\1)\\)", text)
    # Mathpix не сохранил файл: заглушка не должна стать «картинкой».
    text = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{image-not-found\}", "", text)
    text = _heal_ocr_words(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# Метка пункта после «:», «;», точки или в начале строки, у которой OCR
# сломал скобку: «1\()\)», «1 )». Число без такого контекста («\(x=1\) )»)
# не трогаем.
_BROKEN_ITEM_LABEL_RE = re.compile(
    r"(?m)(?:^|(?<=[:;.?!]))(?P<lead>[ \t]*)(?P<label>\d{1,2})"
    r"(?:[ \t]*\\\([ \t]*\)[ \t]*\\\)|[ \t]+\))(?=\s)")


def _heal_numeric_item_labels(text: str) -> str:
    return _BROKEN_ITEM_LABEL_RE.sub(r"\g<lead>\g<label>)", text)


_LATIN_LOOKALIKES = str.maketrans({
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х",
})


def _heal_ocr_words(text: str) -> str:
    """Латинские буквы-двойники внутри русских слов и типовые OCR-ошибки."""
    for _ in range(2):
        text = re.sub(
            r"(?<=[а-яё])[acepoxy]+(?=[а-яё])",
            lambda m: m.group(0).translate(_LATIN_LOOKALIKES), text)
        text = re.sub(
            r"(?<=[а-яё])[acepoxy]+\b",
            lambda m: m.group(0).translate(_LATIN_LOOKALIKES), text)
    text = text.replace("Наидите", "Найдите").replace("наидите", "найдите")
    # «\(\triangle ABC\) \~{} \(\triangle CMB\)» — знак подобия между формулами.
    text = re.sub(r"\\\)\s*\\~\{\}\s*\\\(", r" \\sim ", text)
    # Поворот «R_{B}^{90 r}» / «^{90 \mathrm{r}}» — это 90°.
    text = re.sub(r"\^\{(\d+)\s*(?:\\mathrm\{r\}|r)\}", r"^{\1^{\\circ}}", text)
    # «\(O . \mathrm{B}\) произвольной» — заглавная буква предложения ушла в формулу.
    text = re.sub(
        r"\s*\.\s*\\mathrm\{([А-ЯЁABCEHKMOPTX])\}\\\)",
        lambda m: r"\). " + m.group(1).translate(_LATIN_LOOKALIKES), text)
    text = re.sub(r"\\boldsymbol\{([A-Za-z])\}", r"\1", text)
    # «\sin 18 \Upsilon» — OCR знака градуса; «{ }^{*}» — звёздочка-пропуск.
    text = re.sub(r"(?<=\d)\s*\\Upsilon", r"^{\\circ}", text)
    text = re.sub(r"\{\s*\}\^\{\*\}", "*", text)
    return text


# --------------------------------------------------------------------------
# Рисунки
# --------------------------------------------------------------------------

class FigureIndex:
    """Рисунки книги: по подписи «Рис. §.N» и «Рисунок к задаче §.N»."""

    def __init__(self):
        self.numbered: dict[str, list[str]] = {}
        self.answer: dict[str, list[str]] = {}
        self.positions: list[tuple[int, str, str]] = []
        self.referenced: set[str] = set()

    def add(self, kind: str, number: str, path: str, position: int) -> None:
        target = self.numbered if kind == "numbered" else self.answer
        target.setdefault(number, []).append(path)
        self.positions.append((position, kind, number))


def extract_figures(text: str) -> tuple[str, FigureIndex]:
    """Убирает подписанные float-окружения из потока и индексирует их.

    Рисунки без номерной подписи остаются в тексте как
    ``\\includegraphics{...}`` — их привязывает общий позиционный механизм
    ``task_from_block``. Позиции в индексе считаются по очищенному тексту.
    """
    index = FigureIndex()
    out: list[str] = []
    out_len = 0
    pos = 0
    last_numbered: tuple[str, int] | None = None
    # Части «а», «б», … без общей подписи: OCR иногда печатает «Рис. §.N»
    # отдельной строкой уже после float-окружений.
    unnamed_group: list[tuple[int, list[str]]] = []
    trailing_caption = re.compile(r"^\s*Рис\.?\s*(?P<num>\d{1,2}\.\d{1,3})\s*(?:\\\\)?[ \t]*\n")
    for match in FIGURE_RE.finditer(text):
        if match.start() < pos:
            continue
        block = match.group(0)
        captions = [clean(m.group("caption")) for m in CAPTION_RE.finditer(block)]
        paths = [m.group("path") for m in GRAPHICS_RE.finditer(block)]
        kind = None
        number = None
        for caption in captions:
            numbered = FIG_NUMBER_RE.match(caption)
            answer = ANSWER_FIG_RE.match(caption)
            if numbered:
                kind, number = "numbered", numbered.group("num")
                last_numbered = (number, match.end())
            elif answer:
                kind, number = "answer", answer.group("num")
            elif FIG_PART_RE.match(caption):
                if re.search(r"[аa]", caption):
                    # Части с «а» — новый составной рисунок, чья подпись
                    # «Рис. §.N» потеряна OCR: остаётся позиционным.
                    last_numbered = None
                    unnamed_group = []
                elif last_numbered and match.start() - last_numbered[1] < 1500:
                    # «Рис. 9.8» + части «б», «в», «г» — один составной рисунок.
                    kind, number = "numbered", last_numbered[0]
                    last_numbered = (number, match.end())
        chunk = text[pos:match.start()]
        out.append(chunk)
        out_len += len(chunk)
        pos = match.end()
        if kind and paths:
            for path in paths:
                index.add(kind, number, path, out_len)
            continue
        trailing = trailing_caption.match(text[pos:pos + 200])
        if trailing and paths:
            unnamed_group.append((out_len, paths, len(out)))
            number = trailing.group("num")
            for position, group_paths, out_index in unnamed_group:
                for path in group_paths:
                    index.add("numbered", number, path, position)
                if out_index < len(out):
                    # Ранее выпущенные части убираем из потока; длину
                    # сохраняем, чтобы не сдвинуть позиции индекса.
                    out[out_index] = "\n" * len(out[out_index])
            unnamed_group = []
            last_numbered = (number, pos + trailing.end())
            pos += trailing.end()
            continue
        chunk = "\n" + "\n".join(
            rf"\includegraphics{{{path}}}" for path in paths) + "\n"
        if paths and any(FIG_PART_RE.match(caption) for caption in captions):
            unnamed_group.append((out_len, paths, len(out)))
        out.append(chunk)
        out_len += len(chunk)
    out.append(text[pos:])
    return "".join(out), index


def _attach_figure_refs(task: TaskDraft, index: FigureIndex,
                        fallback: Sequence[str] = ()) -> list[str]:
    """Ссылки «рис. §.N» в условии → ``\\taskpic{файл}``; вернуть ненайденные.

    Если подписи нет, но в блоке задачи лежал рисунок без подписи
    (``fallback``), ссылка получает его: OCR часто теряет подпись.
    """
    missing: list[str] = []
    fallback_used = False

    def rewrite(value: str) -> str:
        nonlocal fallback_used
        if not value:
            return value

        def replace(match: re.Match) -> str:
            nonlocal fallback_used
            numbers = [match.group("num")] + FIG_REF_MORE_RE.findall(
                match.group("more") or "")
            tokens = []
            for number in numbers:
                paths = index.numbered.get(number)
                if not paths:
                    missing.append(number)
                    if fallback and not fallback_used:
                        fallback_used = True
                        tokens.append(", ".join(
                            rf"\taskpic{{{path}}}" for path in fallback))
                    else:
                        tokens.append(number)
                    continue
                index.referenced.add(number)
                tokens.append(", ".join(rf"\taskpic{{{path}}}" for path in paths))
            word = match.group("word")
            return word + " " + ", ".join(tokens)

        return FIG_REF_RE.sub(replace, value)

    task.text_latex = rewrite(task.text_latex)
    for item in task.subitems:
        item.text_latex = rewrite(item.text_latex)
    if fallback_used:
        # Позиционные \taskpic{N} в конце условия дублируют ссылку.
        task.text_latex = re.sub(
            r"(?:\s*\\\\)?\s*\\taskpic\{\d+\}", "", task.text_latex).rstrip()
    return missing


def _attach_answer_figure(task: TaskDraft, paths: Sequence[str]) -> None:
    tokens = " ".join(rf"\taskpic{{{path}}}" for path in paths)
    see_re = re.compile(r"(?i)\(см\.\s*рисунок\)")
    for attr in ("author_solution_latex", "author_answer_latex"):
        value = getattr(task, attr, "") or ""
        if see_re.search(value):
            setattr(task, attr, see_re.sub(
                lambda m: f"(см. рисунок {tokens})", value, count=1))
            return
    for item in task.subitems:
        for attr in ("author_solution_latex", "author_answer_latex"):
            value = getattr(item, attr, "") or ""
            if see_re.search(value):
                setattr(item, attr, see_re.sub(
                    lambda m: f"(см. рисунок {tokens})", value, count=1))
                return
    if task.author_solution_latex:
        task.author_solution_latex = task.author_solution_latex.rstrip() + "\n" + tokens
    elif task.author_answer_latex:
        task.author_answer_latex = task.author_answer_latex.rstrip() + "\n" + tokens
    else:
        task.author_solution_latex = tokens


# --------------------------------------------------------------------------
# Задачи
# --------------------------------------------------------------------------

def _task_key(number: str) -> tuple[int, int]:
    paragraph, task = number.split(".")
    return int(paragraph), int(task)


def task_markers(text: str) -> list[Marker]:
    """Номера задач в начале строки, монотонно возрастающие."""
    result = []
    previous = (0, 0)
    for match in TASK_MARKER_RE.finditer(text):
        number = match.group("number")
        key = _task_key(number)
        if key <= previous:
            continue
        result.append(Marker(match.start(), match.end(), number))
        previous = key
    return result


def _is_heading_line(line: str, known_titles: set[str]) -> bool:
    raw = re.sub(r"\s*\\\\\s*$", "", line).strip()
    if not raw:
        return False
    if raw.startswith("\\section") or raw.startswith("— "):
        return True
    lowered = raw.lower()
    if any(lowered.startswith(word) for word in HEADING_STOP_WORDS):
        return True
    # В OCR знак § и section иногда пропадают, но номер и название остаются.
    unnumbered = re.sub(r"^(?:§\s*)?\d+\.?\s+", "", raw)
    if _normalize_title(raw) in known_titles or _normalize_title(unnumbered) in known_titles:
        return True
    if raw[0].isupper() and raw[0].isalpha() and not re.search(r"[\d\\$(){}\[\]:;.,?!]", raw):
        words = raw.split()
        if 1 <= len(words) <= 6 and len(raw) <= 60:
            return True
    return False


THEORY_MARKERS_RE = re.compile(
    r"(?i)\b(?:называют|говорят, что|рассмотрим|докажем|например|"
    r"очевидно|вообще|таким образом|следовательно|итак|заметим|"
    r"нетрудно|можно записать|отсюда|получаем)\b")


def _leaked_theory_paragraph(paragraph: str, paragraph_number: int) -> bool:
    """Абзац теории следующего параграфа, приклеенный к последней задаче.

    Условие задачи у Мерзляка — один-два абзаца. Длинный абзац прозы с
    оборотами учебника («называют», «рассмотрим») или ссылкой на рисунок
    более позднего параграфа — уже теория.
    """
    raw = paragraph.strip()
    if not raw or not raw[0].isupper() or not raw[0].isalpha():
        return False
    for match in FIG_REF_RE.finditer(raw):
        if _task_key(match.group("num"))[0] > paragraph_number:
            return True
    if len(raw) >= 160 and THEORY_MARKERS_RE.search(raw):
        return True
    return False


def cut_task_body(body: str, known_titles: set[str],
                  paragraph_number: int = 0) -> tuple[str, str]:
    """Отрезает от блока задачи теорию, итоги главы и следующий раздел."""
    lines = body.split("\n")
    kept: list[str] = []
    paragraph_start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        section = SECTION_RE.search(line)
        if section:
            title = clean(section.group("title"))
            if title.isdigit() or not title:
                kept.append(line[:section.start()] + line[section.end():])
                continue
            kept.append(line[:section.start()])
            return "\n".join(kept), "\n".join(
                [line[section.start():]] + lines[index + 1:])
        if index > 0 and stripped and _is_heading_line(stripped, known_titles):
            return "\n".join(kept), "\n".join(lines[index:])
        if not stripped:
            paragraph_start = index + 1
        elif (paragraph_start == index and index > 0
              and _leaked_theory_paragraph(stripped, paragraph_number)):
            return "\n".join(kept), "\n".join(lines[index:])
        kept.append(line)
    return "\n".join(kept), ""


def _source_path(number: str, subsections: dict[str, str] | None = None,
                 structure=None) -> list[str]:
    paragraph = _task_key(number)[0]
    if structure is None:
        structure = MERZLYAK_GEOM9_STRUCTURE
    for chapter_title, paragraphs in structure.values():
        if paragraph in paragraphs:
            path = [chapter_title]
            if paragraphs[paragraph] != chapter_title:
                path.append(paragraphs[paragraph])
            if subsections and number in subsections:
                path.append(subsections[number])
            return path
    return [f"§ {paragraph}"]


def _repetition_subsections(text: str, markers: Sequence[Marker]) -> dict[str, str]:
    """Подразделы § 26 («1. Треугольники») по заголовкам перед задачами."""
    headings = []
    for match in SECTION_RE.finditer(text):
        title = clean(match.group("title"))
        if re.match(r"^\d\.\s+[А-ЯЁ]", title):
            headings.append((match.start(), title))
    result = {}
    for marker in markers:
        if _task_key(marker.external_id)[0] != 26:
            continue
        current = None
        for position, title in headings:
            if position < marker.start:
                current = title
        if current:
            result[marker.external_id] = current
    return result


def _clean_task_body(body: str) -> str:
    body = re.sub(r"(?m)^\s*\}\s*$", "", body)
    return body.strip()


# --------------------------------------------------------------------------
# Ответы
# --------------------------------------------------------------------------

def answer_markers(text: str, allowed: set[str]) -> list[Marker]:
    """Границы ответов: номера задач, но не ссылки «задачей 5.30.»."""
    result = []
    previous = (0, 0)
    for marker in inline_numeric_markers(text, allowed):
        prefix = text[max(0, marker.start - 40):marker.start]
        if REFERENCE_WORD_RE.search(prefix):
            continue
        key = _task_key(marker.external_id)
        if key < previous:
            continue
        result.append(marker)
        previous = key
    return result


def _split_markers_in_math(text: str, allowed: set[str]) -> str:
    """«…=37.11 .40 . x+y=\\)»: номер задачи внутри формулы закрывает её.

    Кандидат принимается, только если он лежит между соседними надёжными
    номерами вне формул: так «3.11» внутри «+3.11 .41 .5» не режет ответ.
    """
    exact = [
        marker for marker in inline_numeric_markers(text, allowed)
        if not any(span.start() < marker.start < span.end()
                   for span in MATH_SPAN_RE.finditer(text))]
    exact_keys = [(marker.start, _task_key(marker.external_id))
                  for marker in exact]
    candidate = re.compile(
        r"(?=(?<!\w)(?P<a>\d{1,2})\s?\.\s?(?P<b>\d{1,3})\s?\.)")

    def window(position: int) -> tuple[tuple[int, int], tuple[int, int]]:
        low, high = (0, 0), (99, 999)
        for start, key in exact_keys:
            if start < position:
                low = key
            elif start > position:
                high = key
                break
        return low, high

    def fix_span(match: re.Match) -> str:
        raw = match.group(0)
        if not (raw.startswith(r"\(") and raw.endswith(r"\)")):
            return raw
        low, high = window(match.start())
        inner = raw[2:-2]
        out = []
        pos = 0
        for found in candidate.finditer(inner):
            if found.start() < pos:
                continue
            number = f"{found.group('a')}.{found.group('b')}"
            if number not in allowed or not (low < _task_key(number) < high):
                continue
            end = found.start() + len(re.match(
                r"\d{1,2}\s?\.\s?\d{1,3}\s?\.", inner[found.start():]).group(0))
            out.append(inner[pos:found.start()])
            out.append(rf"\) {number}. \(")
            pos = end
            low = _task_key(number)
        out.append(inner[pos:])
        value = r"\(" + "".join(out) + r"\)"
        return re.sub(r"\\\(\s*\\\)", "", value)

    return MATH_SPAN_RE.sub(fix_span, text)


def _split_labels_in_math(text: str) -> str:
    """«\\(=2x+2 ; 2) y=…\\)»: метка пункта внутри формулы закрывает её."""
    label = re.compile(r";\s*(?P<label>\d{1,2})\)\s")

    def fix_span(match: re.Match) -> str:
        raw = match.group(0)
        if not (raw.startswith(r"\(") and raw.endswith(r"\)")):
            return raw
        inner = raw[2:-2]
        out = []
        pos = 0
        for found in label.finditer(inner):
            if _open_paren_depth(inner[:found.start()]) > 0:
                continue
            out.append(inner[pos:found.start()])
            out.append(rf"\); {found.group('label')}) \(")
            pos = found.end()
        out.append(inner[pos:])
        value = r"\(" + "".join(out) + r"\)"
        return re.sub(r"\\\(\s*\\\)", "", value)

    return MATH_SPAN_RE.sub(fix_span, text)


def prepare_answers(text: str, allowed: set[str]) -> str:
    text = CHAPTER_LABEL_RE.sub("", text)
    text = _split_markers_in_math(text, allowed)
    text = _split_labels_in_math(text)
    text = re.sub(r"(?<=[.;])\s*[ПГ]?лава\s+\d+\.\s*", " ", text)
    text = _join_hyphenation(text)
    return text


_PAIR_RE = re.compile(
    r"\(\s*-?\d+(?:[.,]\d+)?\s*;\s*-?\d+(?:[.,]\d+)?\s*\)")
_BARE_NUMBER_RE = re.compile(
    r"(?<![\w\\{^_.,°-])(-?\d+(?:[.,]\d+)?(?:\s*:\s*\d+(?:[.,]\d+)?)*)"
    r"(?![\w}°]|[.,]\d|\s*\)|\s*\^)")


def wrap_answer_numbers(value: str) -> str:
    """Голые числа ответа — в ``$…$``: «13 см» → «$13$ см», «(1; 2)» → «$(1; 2)$»."""
    if not value:
        return value
    spans = [(m.start(), m.end()) for m in MATH_SPAN_RE.finditer(value)]
    out = []
    pos = 0

    def wrap_text(chunk: str) -> str:
        chunk = _PAIR_RE.sub(lambda m: "$" + m.group(0) + "$", chunk)
        inner_spans = [(m.start(), m.end()) for m in MATH_SPAN_RE.finditer(chunk)]
        parts = []
        cursor = 0
        for start, end in inner_spans:
            parts.append(_BARE_NUMBER_RE.sub(r"$\1$", chunk[cursor:start]))
            parts.append(chunk[start:end])
            cursor = end
        parts.append(_BARE_NUMBER_RE.sub(r"$\1$", chunk[cursor:]))
        return "".join(parts)

    for start, end in spans:
        out.append(wrap_text(value[pos:start]))
        out.append(value[start:end])
        pos = end
    out.append(wrap_text(value[pos:]))
    return "".join(out)


LEFTOVER_LABEL_RE = re.compile(r"(?m)(?:^|;\s*|\\\\\s*)\d{1,2}\)\s")


def _heal_ocr_math(value: str) -> str:
    """Типовой OCR-брак формул: «\\sqrt{ } 13», «=37.» перед закрытием."""
    if not value:
        return value
    value = re.sub(r"\\sqrt\{\s*\}\s*(\d+)", r"\\sqrt{\1}", value)
    return value


def _finish_fields(task: TaskDraft) -> None:
    """Единицы, градусы и голые числа во всех полях черновика."""
    def text_field(value: str) -> str:
        return normalize_degrees(normalize_units(_heal_ocr_math(value)))

    def answer_field(value: str) -> str:
        value = wrap_answer_numbers(text_field(value))
        value = re.sub(r"(?<!\\right)\.\s*\$$", "$", value)
        value = re.sub(r"(?<=\S)[ \t]+\$(?=[\s;,.)]|$)", "$", value)
        return value

    task.text_latex = text_field(task.text_latex)
    task.author_solution_latex = text_field(task.author_solution_latex)
    task.author_answer_latex = answer_field(task.author_answer_latex)
    for item in task.subitems:
        item.text_latex = text_field(item.text_latex)
        item.author_solution_latex = text_field(item.author_solution_latex)
        item.author_answer_latex = answer_field(item.author_answer_latex)
    answers = [task.author_answer_latex] + [
        item.author_answer_latex for item in task.subitems]
    if any(LEFTOVER_LABEL_RE.search(value or "") for value in answers):
        task.warnings.append(
            "В ответе остались метки других пунктов: OCR перемешал "
            "колонки ответов, сверить с книгой")
        task.confidence = max(0.0, task.confidence - 0.3)


# --------------------------------------------------------------------------
# Разбор целиком
# --------------------------------------------------------------------------

def _expected_ids(markers: Sequence[Marker]) -> list[str]:
    """Пропуски нумерации внутри параграфа — задачи, потерянные OCR."""
    by_paragraph: dict[int, list[int]] = {}
    for marker in markers:
        paragraph, number = _task_key(marker.external_id)
        by_paragraph.setdefault(paragraph, []).append(number)
    missing = []
    for paragraph, numbers in sorted(by_paragraph.items()):
        present = set(numbers)
        for number in range(1, max(numbers) + 1):
            if number not in present:
                missing.append(f"{paragraph}.{number}")
    return missing


def parse_merzlyak(text: str) -> tuple[list[TaskDraft], dict]:
    heading = ANSWERS_HEADING_RE.search(text)
    if not heading:
        raise ValueError(
            "Не найден раздел «Ответы и указания к упражнениям» Мерзляка")
    text, source_repairs = apply_source_repairs(text)
    prepared = prepare_merzlyak_text(text)
    structure = _book_structure(prepared)
    structured_paragraphs = {
        number for _, paragraphs in structure.values() for number in paragraphs}
    heading = ANSWERS_HEADING_RE.search(prepared)
    task_text = prepared[:heading.start()]
    # В легенде тоже встречаются номера («5.6. Задания для устной работы»).
    # Иначе монотонный обход пропустит настоящие задачи первых параграфов.
    legend = re.search(r"\\section\*?\{\s*Условные обозначения\s*\}", task_text, re.I)
    if legend:
        following = SECTION_RE.search(task_text, legend.end())
        if following:
            task_text = task_text[following.start():]
    answer_text = prepared[heading.end():]
    next_section = SECTION_RE.search(answer_text)
    if next_section:
        answer_text = answer_text[:next_section.start()]

    task_text, figures = extract_figures(task_text)
    answer_text, answer_figures = extract_figures(answer_text)
    known_titles = _known_titles(structure)

    markers = task_markers(task_text)
    answer_text = prepare_answers(
        answer_text, {marker.external_id for marker in markers})
    subsections = (_repetition_subsections(task_text, markers)
                   if structure == MERZLYAK_GEOM9_STRUCTURE else {})
    tasks: list[TaskDraft] = []
    spans: list[tuple[int, int, str]] = []
    trimmed_tails = 0
    figure_missing: dict[str, list[str]] = {}
    with numeric_subitem_labels():
        for marker, raw_body in blocks(task_text, markers):
            body, tail = cut_task_body(
                raw_body, known_titles, _task_key(marker.external_id)[0])
            body_span = body
            if tail.strip():
                trimmed_tails += 1
            body = _clean_task_body(body)
            task = task_from_block(
                marker, body, _source_path(marker.external_id, subsections, structure))
            task.warnings = [
                warning for warning in task.warnings
                if "Несбалансированные" not in warning]
            if _task_key(marker.external_id)[0] not in structured_paragraphs:
                task.warnings.append('Параграф не найден в структуре книги: проверить подборку')
            if "(Сноска)" in body:
                task.warnings.append(
                    "В блок попала сноска со страницы: проверить, к какой "
                    "задаче она относится")
            positional_images = list(task.images)
            missing = _attach_figure_refs(task, figures, positional_images)
            if positional_images and not missing:
                task.warnings.append(
                    "Рисунок без подписи привязан по положению: "
                    "проверить, что он относится к этой задаче")
            if missing:
                figure_missing[task.external_id] = missing
                task.warnings.append(
                    "Не найден рисунок по подписи: " + ", ".join(missing)
                    + ("; вместо него подставлен рисунок без подписи из "
                       "блока задачи" if positional_images else ""))
                task.confidence = max(0.0, task.confidence - 0.2)
            tasks.append(task)
            # Рисунок считается «внутри задачи», только если он лежит до
            # отрезанного хвоста теории.
            spans.append((marker.start, marker.end + len(body_span),
                          marker.external_id))

        # Рисунки с номером, на которые никто не сослался: если OCR потерял
        # ссылку, рисунок лежит внутри блока задачи — привязываем по месту.
        task_by_id = {task.external_id: task for task in tasks}
        positional = []
        unreferenced = []
        for position, kind, number in figures.positions:
            if kind != "numbered" or number in figures.referenced:
                continue
            owner = None
            for start, end, external_id in spans:
                if start <= position < end:
                    owner = external_id
                    break
            if owner is None:
                unreferenced.append(number)
                continue
            task = task_by_id[owner]
            for path in figures.numbered[number]:
                if path not in task.images:
                    task.images.append(path)
                    task.text_latex = (task.text_latex.rstrip()
                                       + "\n" + rf"\taskpic{{{path}}}")
            task.warnings.append(
                f"Рисунок {number} привязан по положению: в условии нет "
                "ссылки на него")
            positional.append(number)
            figures.referenced.add(number)

        allowed = {task.external_id for task in tasks}
        solution_diagnostics = merge_solutions(
            tasks, answer_text,
            lambda value: answer_markers(value, allowed),
            missing_ok=True)
        for external_id, paths in answer_figures.answer.items():
            task = task_by_id.get(external_id)
            if task is None:
                continue
            _attach_answer_figure(task, paths)
        for task in tasks:
            _finish_fields(task)
            finalize_draft_images(task)

    counts = Counter(task.external_id.split(".")[0] for task in tasks)
    diagnostics = {
        "source_repairs_applied": source_repairs,
        "task_marker_occurrences": len(markers),
        "unique_tasks": len(tasks),
        "duplicate_task_ids": [],
        "missing_task_ids": _expected_ids(markers),
        "tasks_by_paragraph": {key: counts[key] for key in sorted(counts, key=int)},
        "paragraphs_without_structure": sorted(
            int(key) for key in counts if int(key) not in structured_paragraphs),
        "trimmed_theory_tails": trimmed_tails,
        "figures_numbered": len(figures.numbered),
        "figures_positional": positional,
        "figures_unreferenced": sorted(set(unreferenced), key=_task_key),
        "figures_missing_by_task": figure_missing,
        "answer_figures": sorted(answer_figures.answer, key=_task_key),
        "answer_figures_without_task": sorted(
            set(answer_figures.answer) - allowed, key=_task_key),
    }
    diagnostics.update(solution_diagnostics)
    return tasks, diagnostics

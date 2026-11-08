"""Профиль дидактических материалов Мерзляка, базовый уровень.

А. Г. Мерзляк, В. Б. Полонский, Е. М. Рабинович, М. С. Якир.
«Математика 5, 6», «Алгебра 7–9», «Геометрия 7–9»; «Алгебра и начала
математического анализа 10» — Мерзляк, Номировский, Полонский, Якир.
Дидактические материалы (серия «Алгоритм успеха», Вентана-Граф), OCR Mathpix.

Особенности книг (сверено по ДМ-6 с текстовым слоем):

- «Упражнения» — однотипные варианты с одинаковой нумерацией (4 у
  «Математики», 3 у алгебры): № 170 во всех вариантах — аналоги (одна
  семья, решение Егора 07.11.2026).
  Внутри варианта — заголовки тем; темы и их первые номера одинаковы во
  всех вариантах и сверены в ``data/merzlyak_dm_structure.json``;
- «Контрольные работы» — два варианта, в каждом «Контрольная работа № n»
  с подзаголовком «Тема. …» и задачами 1…m;
- колонтитулы «Вариант k», «Упражнения», «Контрольные работы» на каждой
  странице — вариант начинается с того «Вариант k», за которым идёт
  задача 1;
- пункты задач нумеруются цифрами «1) 2) 3)» и в книге стоят колонками:
  OCR читает их по строкам («1) …; 3) …⏎2) …; 4) …») — пункты
  раскладываются по номерам;
- рисунки пронумерованы сквозь книгу («Рис. 12»), ссылка в условии —
  «(рис. 12)», «на рисунке 12»; номер рисунка в задаче не остаётся:
  ссылка заменяется рисунком (как у Волчкевича);
- раздела ответов нет: авторских ответов и решений у задач нет.

Локаторы — договор с правилами аналогов (``independentworks.analogs``,
правило ``merzlyak_dm``): упражнения ``ДМ.В{k}/{N}``, контрольные
``КР{n}.В{k}/{m}``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from .merzlyak_parser import (
    MATH_SPAN_RE, _heal_numeric_item_labels, _heal_ocr_words, _join_hyphenation,
    _tabular_to_array, _unwrap_footnotes)
from .potoskuev_parser import _finish_fields, monotonic_numbers
from .textbook_parser import (
    Marker, TaskDraft, blocks, finalize_draft_images, numeric_subitem_labels,
    read_group, remove_group_commands, task_from_block)
from .volchkevich_parser import canon_fields
from .vysotsky_parser import apply_source_repairs


PROFILE = "merzlyak_dm"
STRUCTURE_PATH = Path(__file__).with_name("data") / "merzlyak_dm_structure.json"
REPAIRS_PATH = Path(__file__).with_name("data") / "merzlyak_dm_repairs.json"

EXERCISES_TITLE = "Упражнения"
TESTS_TITLE = "Контрольные работы"

_SECTION = r"\\(?:sub)*section\*?\{"
# Строка, в которой только «Вариант 2» (заголовок или колонтитул);
# строка оглавления «Вариант 2 . . . 34» сюда не попадает.
VARIANT_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:" + _SECTION + r")?\s*(?:\\textbf\{)?\s*Вариант\s*(?P<k>[1-4])\s*\}?\s*\}?"
    r"[ \t]*(?:\\\\)?[ \t]*$")
WORK_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:" + _SECTION + r")?\s*Контрольная\s+работа\s*(?:№|N[o°º]?)\s*"
    r"(?P<n>\d{1,2})\s*\}?[ \t]*(?:\\\\)?[ \t]*$")
RUNNING_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:" + _SECTION + r")?\s*(?:Упражнения|Контрольные\s+работы)\s*\}?"
    r"[ \t]*(?:\\\\)?[ \t]*$\n?")
# Номер страницы отдельной строкой.
PAGE_NUMBER_RE = re.compile(r"(?m)^[ \t]*\d{1,3}[ \t]*(?:\\\\)?[ \t]*$\n?")
TASK_RE = re.compile(r"(?m)^[ \t]*(?P<number>\d{1,3})[ \t]?\.(?=\s)")
# После контрольных: оглавление, справочный материал, ответы.
BOOK_END_RE = re.compile(
    r"(?m)^[ \t]*" + _SECTION + r"\s*(?:Содержание|Справочный\s+материал|Ответы)\b")
THEME_RE = re.compile(r"^\s*(?:" + _SECTION + r")?\s*Тема\s*\.\s*")
BOOK_RE = re.compile(
    r"(?P<subject>Математика|Алгебра|Геометрия)\s*[.:,]?\s*(?P<grade>\d{1,2})\s*(?:-?\s*й\s+)?класс",
    re.I)


# --------------------------------------------------------------------------
# Книга и подготовка текста
# --------------------------------------------------------------------------

def load_structure(path: Path = STRUCTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def detect_book(text: str, structure: dict | None = None) -> dict | None:
    """Книга по титулу: первое «Математика : 6 класс» до упражнений."""
    structure = structure or load_structure()
    head = text[:max(4000, text.find("Вариант 1") + 1)]
    # Книга без титула в TEX (Алгебра 10) — по фразе из «От авторов».
    for book in structure["books"]:
        if book.get("detect") and re.search(book["detect"], head):
            return book
    match = BOOK_RE.search(head)
    if not match:
        return None
    subject = match.group("subject").capitalize()
    grade = int(match.group("grade"))
    for book in structure["books"]:
        if book["subject"] == subject and book["grade"] == grade:
            return book
    return {"key": f"{subject}-{grade}", "subject": subject, "grade": grade,
            "title": f"{subject}. {grade} класс. Дидактические материалы",
            "unknown": True}


_LIST_TOKEN_RE = re.compile(
    r"\\begin\{(?P<begin>enumerate|itemize)\}(?:\[[^\]]*\])?|\\end\{(?:enumerate|itemize)\}"
    r"|\\setcounter\{enum(?P<depth>i+)\}\{(?P<value>\d+)\}"
    r"|\\item(?:\[(?P<label>[^\[\]]*)\])?[ \t]*")
_EXPLICIT_NUMBER_RE = re.compile(r"(?m)^[ \t]*(?P<number>\d{1,3})\s?\.(?=\s)")


def flatten_lists(text: str) -> str:
    """Списки Mathpix → строки «N. …» (задачи) и «k) …» (пункты).

    Задачи у Mathpix — ``\\item[12.]``; ``enumerate`` с пунктами без меток —
    либо номера задач (счётчик ``\\setcounter{enumi}{122}`` подходит к
    текущему номеру, текст пункта — слова), либо пункты задачи: продолжение
    после колонки («\\setcounter{enumi}{4}» при задаче 121 — пункты 5, 6, …)
    или пункты формулами сразу после условия «Решите уравнение:».
    Вложенный список — всегда пункты.
    """
    out = []
    pos = 0
    last = 0          # последний номер задачи
    stack: list[list] = []  # [режим "tasks"|"items", счётчик]

    def seen(chunk: str) -> None:
        nonlocal last
        for match in _EXPLICIT_NUMBER_RE.finditer(chunk):
            number = int(match.group("number"))
            # «1.» после «229.» — новый вариант или контрольная.
            if last < number <= last + 8 or number < min(last, 3):
                last = number

    def list_mode(after: int) -> list:
        """Режим верхнего ``enumerate`` по счётчику и первому пункту."""
        head = text[after:after + 400]
        counter = re.match(r"\s*\\setcounter\{enumi\}\{(\d+)\}", head)
        item = re.search(r"\\item(?:\[[^\]]*\])?\s*(?P<body>.{0,30})", head, re.S)
        wordy = bool(item and re.match(r"[А-ЯЁ][а-яё]", item.group("body")))
        if counter:
            value = int(counter.group(1))
            if wordy and last - 3 <= value and (value <= last + 8 or last == 0):
                return ["tasks", value]
            return ["items", value]
        return ["tasks", last] if wordy else ["items", 0]

    for match in _LIST_TOKEN_RE.finditer(text):
        chunk = text[pos:match.start()]
        out.append(chunk)
        if not stack or stack[0][0] == "tasks":
            seen(chunk)
        pos = match.end()
        token = match.group(0)
        if match.group("begin"):
            if match.group("begin") == "enumerate" and not stack:
                stack.append(list_mode(match.end()))
            else:
                stack.append(["items", 0] if stack else ["tasks", last])
            out.append("\n")
        elif token.startswith("\\end"):
            if stack:
                stack.pop()
            out.append("\n")
        elif match.group("depth"):
            if stack and len(match.group("depth")) == len(stack):
                stack[-1][1] = int(match.group("value"))
        elif match.group("label") is not None:
            label = match.group("label").strip()
            out.append("\n" + label + " " if label else "\n")
            if not stack or stack[0][0] == "tasks":
                seen(label + " ")
        elif stack:
            mode = stack[-1]
            if len(stack) == 1 and mode[0] == "tasks":
                number = max(mode[1], last) + 1
                mode[1] = last = number
                out.append(f"\n{number}. ")
            else:
                mode[1] += 1
                out.append(f"\n{mode[1]}) ")
        else:
            out.append("\n")
    out.append(text[pos:])
    return "".join(out)


_LATIN_TO_CYRILLIC = str.maketrans("acepoxyACEHKMOPTX", "асеролуАСЕНКМОРТХ")
# Опечатки OCR в словах книг (сверено по TEX Mathpix 08.11.2026).
OCR_WORDS = {
    "аначен": "значен", "Аначен": "Значен", "ураннен": "уравнен", "фуннц": "функц",
    "поназател": "показател", "Спожение": "Сложение",
    "Состввьте": "Составьте", "имяет": "имеет", "алreбр": "алгебр", "сонращ": "сокращ",
}
# Искажённые слова целиком (вычитка ДМ 7, 08.11.2026): только с границами слова.
OCR_WHOLE_WORDS = {
    "сранните": "сравните", "звачение": "значение", "равеиство": "равенство", "пропёл": "прошёл",
    "пагревания": "нагревания", "равпо": "равно", "пайдите": "найдите", "Пайдите": "Найдите",
    "знячение": "значение", "знячения": "значения", "произнедение": "произведение",
    "равпые": "равные", "значепия": "значения", "значепиях": "значениях", "Нвляется": "Является",
    "выряжение": "выражение", "кнадрата": "квадрата", "кнадрат": "квадрат", "уравиение": "уравнение",
    "Иавестно": "Известно", "Пользулсь": "Пользуясь", "польаулсь": "пользуясь", "черев": "через",
    "каждото": "каждого", "нядо": "надо", "сумми": "суммы", "степепи": "степени",
    "проивведения": "произведения", "оспованием": "основанием", "ныражение": "выражение",
    "зтих": "этих", "одночленями": "одночленами", "ныше": "выше", "повыщалась": "повышалась",
    "снорость": "скорость", "ранный": "равный", "коитейнера": "контейнера", "стецени": "степени",
    "принимеет": "принимает", "зпачение": "значение", "зпачения": "значения", "циф": "цифр",
}
# Контекстные: слово само по себе бывает правильным.
OCR_PHRASES = {
    "На авводе изготовили дна вида": "На заводе изготовили два вида",
    "не имеет решении": "не имеет решений",
    # «графин» — настоящее слово (графин воды): только в заголовке алгебры 7.
    "её графин и свойства": "её график и свойства",
}
_NAMED_FUNCTIONS = {"sin", "cos", "tg", "ctg", "arcsin", "arccos", "arctg", "arcctg", "log", "lg", "ln"}


def _operator_name(match: re.Match) -> str:
    """«\\operatorname { a r c s i n }» → «\\arcsin», «tg» → «\\operatorname{tg}»."""
    name = re.sub(r"\s+", "", match.group("name"))
    if name in {"sin", "cos", "arcsin", "arccos", "log", "lg", "ln"}:
        return "\\" + name + " "
    return "\\operatorname{" + name + "}" if name in _NAMED_FUNCTIONS else match.group(0)


def heal_bold_math(text: str) -> str:
    """Жирные цифры и буквы Mathpix: «\\mathbf{1 6}» → «16», «\\boldsymbol{\\pi}» → «\\pi»."""
    # «\\mathbf{1}, \\mathbf{2 1}» и «\\mathbf{0 , 2 5}» — десятичная дробь.
    text = re.sub(r"\\mathbf\{\s*(\d+)\s*\}\s*,\s*\\mathbf\{\s*(\d(?:\s*\d)*)\s*\}",
                  lambda m: m.group(1) + "{,}" + re.sub(r"\s+", "", m.group(2)), text)
    text = re.sub(r"\\mathbf\{\s*(\d(?:\s*\d)*)\s*,\s*(\d(?:\s*\d)*)\s*\}",
                  lambda m: re.sub(r"\s+", "", m.group(1)) + "{,}" + re.sub(r"\s+", "", m.group(2)), text)
    text = re.sub(r"\\mathbf\{\s*(\d(?:\s*\d)*)\s*\}", lambda m: re.sub(r"\s+", "", m.group(1)), text)
    # N, Z, Q, R — числовые множества (в книге одним шрифтом).
    text = re.sub(r"\\(?:mathbf|boldsymbol)\{\s*([A-Za-z]|\\pi)\s*\}",
                  lambda m: f"\\mathbb{{{m.group(1)}}}" if m.group(1) in "NZQR" else m.group(1), text)
    text = re.sub(r"\\boldsymbol\{\s*(\\operatorname\s*\{[^{}]*\})\s*\}", r"\1", text)
    return re.sub(r"\\operatorname\s*\{(?P<name>\s*[a-z](?:\s*[a-z])*\s*)\}", _operator_name, text)


# Позиция метки пункта: начало строки, после «\\», «;», «:» или «\item[».
_LABEL_LEAD = r"(?m)(?P<lead>(?:^|\\\\|[;:]|\\item\[\][ \t]*|\\item\[)[ \t]*)"


def heal_item_labels(text: str) -> str:
    """Метки пунктов, испорченные OCR.

    - «з)» вместо «3)»: буквенных меток дальше «е)» в книгах нет;
    - метка внутри формулы: «\\(5)-5,4 \\in N\\)», «\\(\\displaystyle 2)\\left(…\\)».
    """
    text = re.sub(_LABEL_LEAD + r"[зЗ]\)", r"\g<lead>3)", text)
    # «\\(\\left.[-1 ; 2] ; 2\\right)(-\\infty ; 0]\\)» — метка «2)» стала скобкой.
    text = re.sub(r"\\left\.(?P<body>[^\n]*?)[;,]\s*(?P<label>\d{1,2})\\right\)",
                  r"\g<body>\\); \g<label>) \\(", text)
    return re.sub(_LABEL_LEAD + r"\\\(\s*(?P<ds>\\displaystyle\s*)?(?P<label>\d{1,2})\)\s*",
                  lambda m: m.group("lead") + m.group("label") + ") \\(" + (m.group("ds") or ""), text)


_UNITS_ONLY_RE = re.compile(
    r"(?:\s|~|\d|[,;.]|\^\{[23]\}|(?<![а-яё])(?:мм|см|дм|км|кг|мин|га|м|а|г|т|ц|ч|с|л)(?![а-яё]))+")


_INF_RE = re.compile(r"\\\(\s*([+-]?)\s*\\infty\s*\\\)")
_INTERVAL_RE = re.compile(
    r"(?<![\w\\$])([\[(])\s*(-?\s?\d+(?:,\d+)?|\x00-\x00)\s*;\s*"
    r"(\+?\s*-?\d+(?:,\d+)?|\+?\s*\x00\+?\x00)\s*([\])])")


def wrap_prose_intervals(text: str) -> str:
    """«[-4; 2)», «(-4; + ∞)» вне формул → «\\([-4; 2)\\)»."""
    text = _INF_RE.sub(lambda m: "\x00" + m.group(1) + "\x00", text)

    def end(value: str) -> str:
        value = re.sub(r"\s", "", value)
        return re.sub(r"\x00([+-]?)\x00", lambda m: m.group(1) + "\\infty ", value).strip()

    def prose(chunk: str) -> str:
        return _INTERVAL_RE.sub(
            lambda m: "\\(" + m.group(1) + end(m.group(2)) + "; " + end(m.group(3)) + m.group(4) + "\\)", chunk)

    return re.sub(r"\x00([+-]?)\x00", r"\\(\1\\infty\\)", outside_math(text, prose))


def outside_math(text: str, fix) -> str:
    """Применить ``fix`` только к прозе между формулами, формулы не трогать."""
    out, pos = [], 0
    for span in MATH_SPAN_RE.finditer(text):
        out.append(fix(text[pos:span.start()]))
        out.append(span.group(0))
        pos = span.end()
    out.append(fix(text[pos:]))
    return "".join(out)


_DELIMITER_RE = re.compile(r"(?<!\\)\$\$|(?<!\\)\$|\\[()\[\]]")


def math_delimiters_broken(value: str) -> bool:
    """Вложенные или незакрытые \\( \\) \\[ \\] $ $$ — LaTeX такое не соберёт."""
    open_token = None
    pairs = {"\\(": "\\)", "\\[": "\\]", "$": "$", "$$": "$$"}
    for match in _DELIMITER_RE.finditer(value or ""):
        token = match.group(0)
        if open_token is None:
            if token in pairs:
                open_token = token
            else:
                return True
        elif token == pairs[open_token]:
            open_token = None
        else:
            return True
    return open_token is not None


_ESTIMATE_COMMA_RE = re.compile(
    r"(?<=\d),(?=-?\d+(?:\^\{?\\circ\}?)?\s*(?:<|>|\\leq|\\geq|\\leqslant|\\geqslant|\\le\b|\\ge\b)\s*\\?[A-Za-z])")
_ESTIMATE_LEFT_RE = re.compile(
    r"[A-Za-z}]\s*(?:<|>|=|\\leq|\\geq|\\leqslant|\\geqslant|\\le\b|\\ge\b)\s*-?\d+(?:,\d+)?(?:\^\{?\\circ\}?)?$")


def heal_math_details(text: str) -> str:
    """Мелочи формул OCR (сверено вычиткой ДМ 5 и 8, 08.11.2026)."""
    # Единицы, разорванные OCR: «к м^{2}», «4 м м», «\\mathrm{kM} / \\mathrm{u}».
    text = re.sub(r"(?<![а-яёА-ЯЁA-Za-z\\])([кcсдм]) м(?=[\s^;,.}\\)$]|$)",
                  lambda m: {"c": "с"}.get(m.group(1), m.group(1)) + "м", text)
    text = re.sub(r"\\mathrm\{kM\}\s*/\s*\\mathrm\{u\}", r"\\text{км/ч}", text)
    text = re.sub(r"\s*/\s*\\mathrm\{u\}", r"\\text{/ч}", text)
    text = text.replace("\\mathrm{мm}", "\\text{мм}")
    # «4 дм \\({ }^{3} 126\\) см³» — степень единицы ушла в формулу.
    text = re.sub(r"(?<=[а-яё])\s*\\\(\s*\{\s*\}\^\{([23])\}\s*([^\\]*?)\s*\\\)",
                  lambda m: "$^{" + m.group(1) + "}$" + (" " + m.group(2) if m.group(2) else ""), text)
    text = re.sub(r"(?<=[а-яё])²", "$^{2}$", text)
    text = re.sub(r"(?<=[а-яё])³", "$^{3}$", text)

    def in_math(span: re.Match) -> str:
        value = span.group(0)
        inner = re.sub(r"^\\\(|\\\)$", "", value)
        # «\\(340000 м^{2} ; 56 км^{2} ; 4 км^{2} 17\\)» — числа с единицами,
        # а не формула: единицы текстом, числа обернёт канон.
        if (value.startswith("\\(") and re.search(r"[а-яё]", inner) and re.search(r"\d", inner)
                and _UNITS_ONLY_RE.fullmatch(inner)):
            inner = re.sub(r"\^\{([23])\}", r"$^{\1}$", inner.replace("~", " "))
            return re.sub(r"\s*;\s*", "; ", re.sub(r"\s+", " ", inner)).strip()
        # «\\{8,12\\}» — перечисление элементов, не десятичная дробь.
        value = re.sub(r"\\\{([^{};]*?)\\\}",
                       lambda m: "\\{" + re.sub(r"(?<=\d),(?=-?\d)", ", ", m.group(1)) + "\\}", value)
        # Две оценки в одной формуле: «30<a<50,10<b<40», «tg β=1,5,0<α».
        # Слева от запятой — законченная оценка «a<50» / «β=1,5»; иначе это
        # десятичная дробь в начале неравенства «1,5<x<3».
        value = _ESTIMATE_COMMA_RE.sub(
            lambda m: ", " if _ESTIMATE_LEFT_RE.search(value, 0, m.start()) else ",", value)
        # Ряд чисел «1,9,25,49» — запятые-разделители (в десятичной дроби одна).
        value = re.sub(r"(?<![\d,.{])\d+(?:,\d+){2,}(?![\d,])",
                       lambda m: m.group(0).replace(",", ", "), value)
        # «4.5» — десятичная точка OCR; «\\simeq» — «=».
        value = re.sub(r"(?<=\d)\.(?=\d)", ",", value).replace("\\simeq", "=")
        # Периодическая дробь «5,(16)».
        value = re.sub(r"(?<=\d),(?=\(\d+\))", "{,}", value)
        # «8 \\in N» — числовые множества.
        value = re.sub(r"(\\(?:not)?in|\\subset)\s*([NZQ])(?![\w{])", r"\1 \\mathbb{\2}", value)
        return value

    text = MATH_SPAN_RE.sub(in_math, text)
    # Черта корня, прочитанная как черта над переменной: «\\sqrt{64 \\bar{a}}».
    out, pos = [], 0
    for match in re.finditer(r"\\sqrt(?:\[[^\]]*\])?\{", text):
        if match.start() < pos:
            continue
        try:
            body, end = read_group(text, match.end() - 1)
        except ValueError:
            continue
        fixed = re.sub(r"\\bar\{([a-z])\}", r"\1", body)
        fixed = re.sub(r"\\overline\{([^{}]*)\}", r"\1", fixed)
        out.append(text[pos:match.end()] + fixed + "}")
        pos = end
    out.append(text[pos:])
    text = "".join(out)
    # Перенос по знаку, хвост формулы голым текстом: «\\(x^{2}-4 x-\\) -10 = 0».
    text = re.sub(r"(?P<sign>[-+=])\s*\\\)\s*(?P=sign)\s*(?P<tail>[\dA-Za-z][\dA-Za-z \t=+\-^]*?)(?=\s*(?:[.;,]|$))",
                  r"\g<sign>\g<tail>\)", text, flags=re.M)
    # «(-2,8) \\({ }^{4}\\)» — показатель степени оторван от скобки.
    text = re.sub(r"(\([^()\n]{1,30}\))\s*\\\(\s*\{\s*\}\^\{([^{}]+)\}\s*\\\)", r"\\(\1^{\2}\\)", text)
    # Промежуток прозой: «[-4; 2)», «(-4; + \\(\\infty\\))» — только вне формул:
    # внутри \\(…\\) обёртка дала бы вложенную формулу (LaTeX падает).
    text = wrap_prose_intervals(text)
    # Латиница в единицах: «2 m» → «2 м» — только в прозе: в формуле
    # «\\(5 m n\\)» это переменная, кириллица там не наберётся.
    text = outside_math(text, lambda chunk: re.sub(r"(?<=\d) m(?=[\s.,;]|$)", " м", chunk))
    # Периодическая дробь прозой: «6,(23)» — тоже вне формул, иначе вложенная \\(.
    return outside_math(text, lambda chunk: re.sub(
        r"(?<![\w.,$\\])(-?\d+),\((\d+)\)", r"\\(\1{,}(\2)\\)", chunk))


# Арифметика прозой: «28 • 13-4 228: 14», «608 • 76» — «•» значит умножение.
_ARITH_RE = re.compile(r"(?<![\w,$\\{])\(*-?\d[\d \t,()\-−+•·⋅:]*[\d)]")


def _arith_inner(expr: str) -> str:
    inner = re.sub(r"\s*[•·⋅]\s*", r" \\cdot ", expr).replace("−", "-")
    inner = re.sub(r"(?<![\w,.])\d+(?: \d{3})+(?!\d)|(?<![\w,.])\d{5,}(?![\w]|[.,]\d)",
                   lambda m: thin_groups(m.group(0)), inner)
    return inner.strip()


# Пункт целиком из чисел и знаков: «7,3 - 5,8», «(12 078+1485)+(6922+3515)».
_PURE_ARITH_RE = re.compile(r"\(*-?\d[\d \t,()+\-−•·⋅:=<>]*")
_HAS_OPERATOR_RE = re.compile(r"[\d)]\s*[-−+•·⋅:=<>]\s*\(?-?\d")
# Метка пункта в начале куска прозы — граница кусков.
_PIECE_SPLIT_RE = re.compile(
    r"((?:^|(?<=\n)|(?<=;)|(?<=[^\d)\s]:)|(?<=\\\\))[ \t]*\d{1,2}\)[ \t]+|;|\\\\|\n)")
# «:» — граница метки только после слова («Вычислите: 1) …»): в «(84 : 12) • 5»
# двоеточие — деление, «12)» не метка.
# «;» забирает только сам символ: пробелы перед меткой «; 2) …» съедает первая
# ветка, иначе метка уходит в формулу «\(2) 4,2 + 1,1\)».
# Минус между величинами с единицами: «54 м 24 см - 18 м 19 см».
_QUANTITY_MINUS_RE = re.compile(
    r"(\d(?:[ \t](?:мм|см|дм|км|кг|мин|га|м|г|т|ц|ч|с|л))?)[ \t]+[-–][ \t]+(?=\d)")


_ITEM_LABEL_LEAD_RE = re.compile(r"\d{1,2}\)\s")


def _arith_piece(piece: str) -> str:
    body = piece.strip()
    core = body.rstrip(".,?! \t")
    if (core and _PURE_ARITH_RE.fullmatch(core) and _HAS_OPERATOR_RE.search(core)
            and not _ITEM_LABEL_LEAD_RE.match(core)):
        lead = piece[:len(piece) - len(piece.lstrip())]
        tail = piece[len(lead) + len(core):]
        return lead + "\\(" + _arith_inner(core) + "\\)" + tail
    piece = _ARITH_RE.sub(_inline_arith, piece)
    return _QUANTITY_MINUS_RE.sub(r"\1 $-$ ", piece)


def _inline_arith(match: re.Match) -> str:
    expr = match.group(0)
    if not re.search(r"[•·⋅]", expr) and not re.search(r"\d\s*:\s*\(?-?\d", expr):
        return expr
    tail = ""
    while expr.endswith(")") and expr.count(")") > expr.count("("):
        expr, tail = expr[:-1], ")" + tail
    stripped = expr.rstrip(" ,")
    tail = expr[len(stripped):] + tail
    return "\\(" + _arith_inner(stripped) + "\\)" + tail


def wrap_bare_arithmetic(value: str) -> str:
    """Арифметика вне формул — одной формулой, а не по числам.

    Пункт целиком из чисел и знаков («7,3 - 5,8») и выражение со знаком «•»
    (так OCR читает точку умножения) или делением «a : b» → «\\(…\\)».
    Многострочные выносные формулы не трогаются.
    """
    def prose(chunk: str) -> str:
        parts = _PIECE_SPLIT_RE.split(chunk)
        return "".join(part if index % 2 else _arith_piece(part)
                       for index, part in enumerate(parts))

    out, pos = [], 0
    for span in MATH_SPAN_RE.finditer(value):
        out.append(prose(value[pos:span.start()]))
        out.append(span.group(0))
        pos = span.end()
    out.append(prose(value[pos:]))
    return "".join(out)


def restore_stars(body: str) -> str:
    """Задачи со звёздочками вместо цифр: Mathpix читает пару «*…*» как
    курсив (``\\textit{…}``), иногда через границы пунктов. Звёздочки
    возвращаются, числа со звёздочками — в формулу: «63 ***» → «\\(63{*}{*}{*}\\)»."""
    if not re.search(r"звёздоч|звездоч", body):
        return body
    while "\\textit{" in body:  # бывает вложенный: «**\\textit{;\\\\ 3) * \\textit{1} и 99}»
        match = re.search(r"\\textit\{", body)
        try:
            content, end = read_group(body, match.end() - 1)
        except ValueError:
            break
        body = body[:match.start()] + "*" + content + "*" + body[end:]
    body = re.sub(r"\^\{\s*\*\s*\}", "*", body)

    def star(match: re.Match) -> str:
        token = re.sub(r"\s+", "", match.group(0))
        return "\\(" + token.replace(",", "{,}").replace("*", "{*}") + "\\)"

    def prose(chunk: str) -> str:
        return re.sub(r"(?<![\w{*,])(?=[\d*, ]*\*)[\d*][\d*,]*(?: [\d*][\d*,]*)*", star, chunk)

    parts, pos = [], 0
    for span in MATH_SPAN_RE.finditer(body):
        parts.append(prose(body[pos:span.start()]))
        math = re.sub(r"(?<![{^])\*", "{*}", span.group(0))
        parts.append(re.sub(r"(?<=\d),\s*(?=\{\*\})|(?<=\d),(?=\d)", "{,}", re.sub(r"\{\*\}\s+(?=\d)", "{*}", math)))
        pos = span.end()
    parts.append(prose(body[pos:]))
    # «\\(3454>3\\) \\(4{*}9\\)» — число разорвано между формулами.
    return re.sub(r"(\d)\\\)[ \t]+\\\((?=[\d{])", r"\1", "".join(parts))


def prepare_text(text: str, figures: "Figures | None" = None) -> str:
    text = text.replace("\r\n", "\n")
    begin = text.find("\\begin{document}")
    if begin >= 0:
        text = text[begin + len("\\begin{document}"):]
    text = text.replace("\\end{document}", "")
    text = re.sub(r"\\textbackslash\s+item", r"\\item", text)
    text = _unwrap_footnotes(text)
    text = heal_item_labels(text)
    text = flatten_lists(text)
    text = re.sub(r"\\\\\[0pt\]", r"\\\\", text)
    text = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{image-not-found\}", "", text)
    text = _heal_numeric_item_labels(text)
    # «На рисунке \(11 \angle A B C=54^{\circ}\)» — номер рисунка ушёл в формулу.
    text = re.sub(r"(?i)(рисун\w*|рис\.)\s*\\\(\s*(\d{1,3})\s+(?=\\|[A-Za-z])", r"\1 \2 \\(", text)
    if figures is not None:
        # До tabular → array: таблица «Рис. 2 & Рис. 3» над картинками.
        text = extract_figure_tables(text, figures)
    text = _tabular_to_array(text)
    text = _join_hyphenation(text)
    # До _heal_ocr_words: тот снимает \boldsymbol{R}, а это множество ℝ.
    text = heal_bold_math(text)
    text = _heal_ocr_words(text)
    text = heal_math_details(text)
    for wrong, right in OCR_WORDS.items():
        text = text.replace(wrong, right)
    for wrong, right in OCR_PHRASES.items():
        text = text.replace(wrong, right)
    text = re.sub(r"(?<![а-яёА-ЯЁ])(" + "|".join(OCR_WHOLE_WORDS) + r")(?![а-яёА-ЯЁ])",
                  lambda m: OCR_WHOLE_WORDS[m.group(1)], text)
    # Латинские двойники в начале русского слова: «apбуза», «cм»; «250 p.» — рубли.
    text = re.sub(r"(?<![\w\\{])([acepoxyACEHKMOPTX]{1,3})(?=[а-яё]{1,})",
                  lambda m: m.group(1).translate(_LATIN_TO_CYRILLIC), text)
    text = re.sub(r"(?<=\d) p\.", " р.", text)
    # Украинская «є» в русском слове («Разложитє»).
    text = re.sub(r"(?<=[а-яё])є|є(?=[а-яё])", "е", text)
    return re.sub(r"\n{3,}", "\n\n", text)


# --------------------------------------------------------------------------
# Рисунки
# --------------------------------------------------------------------------

_GRAPHICS = r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{(?P<path>[^{}\s\\]+)\}"
GRAPHICS_RE = re.compile(_GRAPHICS)
FIGURE_ENV_RE = re.compile(r"\\begin\{figure\}(?:\[[^\]]*\])?.*?\\end\{figure\}", re.S)
CAPTION_RE = re.compile(r"\\caption\{(?P<text>[^{}]*)\}")
CAPTION_NUMBERS_RE = re.compile(r"Рис\.?\s*(?P<num>\d{1,3})")
# Подпись строкой сразу после картинки: «\includegraphics{…}\\⏎Рис. 5».
# Без «^»: шаблон применяется через ``.match(text, pos)`` с позиции картинки.
TRAILING_CAPTION_RE = re.compile(
    r"[ \t]*(?:\\\\)?[ \t]*\n?[ \t]*(?P<caption>(?:Рис\.?\s*\d{1,3}[ \t]*)+)(?:\\\\)?[ \t]*(?=\n|$)")
# Подпись, оставшаяся в тексте без картинки рядом: «… хорду Рис. 1».
# Проверка после номера — только в той же строке: следующая строка может
# начинаться с номера задачи («2. …»).
STRAY_CAPTION_RE = re.compile(r"(?<![(\w])Рис\.\s*(?P<num>\d{1,3})(?![\d.,]|[ \t]*[)\w])")
FIGURE_TOKEN = "\\dmfig{{{}}}"
FIGURE_TOKEN_RE = re.compile(r"\\dmfig\{(?P<num>\d{1,3})\}")
# Ссылки в условии: «(рис. 12)», «(рис. 5, 6)», «на рисунке 10», «рисунок 49».
FIG_REF_RE = re.compile(
    r"(?P<paren>\(\s*)?(?P<word>рис(?:ун[а-яё]*|\.))\s*(?P<nums>\d{1,3}(?:\s*(?:,|и|–|-)\s*\d{1,3})*)"
    r"(?P<close>\s*\))?", re.I)


class Figures:
    def __init__(self):
        self.by_number: dict[str, list[str]] = {}
        self.stray_captions: list[str] = []
        self.merged: list[str] = []

    def add(self, number: str, path: str) -> None:
        paths = self.by_number.setdefault(number, [])
        if path not in paths:
            paths.append(path)


def register_figures(figures: Figures, numbers: list[str], paths: list[str]) -> str:
    """Рисунки с подписью → ``\\dmfig{N}``; без подписи — картинки как есть."""
    if not numbers or not paths:
        return "\n".join(f"\\includegraphics{{{path}}}" for path in paths)
    if len(paths) == len(numbers):
        pairs = list(zip(numbers, paths))
    else:
        # Mathpix склеил соседние рисунки в одну картинку (или наоборот).
        figures.merged.append(", ".join(numbers))
        pairs = [(number, path) for number in numbers for path in paths]
    for number, path in pairs:
        figures.add(number, path)
    return "\n" + "".join(FIGURE_TOKEN.format(n) for n in dict.fromkeys(numbers)) + "\n"


TABULAR_RE = re.compile(
    r"\\begin\{tabular\}(?:\[[^\]]*\])?\{[^{}]*\}(?P<body>.*?)\\end\{tabular\}", re.S)


def extract_figure_tables(text: str, figures: Figures) -> str:
    """Таблица рисунков Mathpix: строка «Рис. 2 & Рис. 3», под ней картинки.

    Подпись и картинка — в одной колонке, подпись в ближайшей строке выше
    (или ниже). Таблицы, где есть другой текст, остаются таблицами.
    """
    def fix(match: re.Match) -> str:
        body = match.group("body")
        if "\\includegraphics" not in body or "\\begin{tabular}" in body:
            return match.group(0)
        rows = [row.split("&") for row in re.split(r"\\\\", body.replace("\\hline", " "))]
        captions: dict[tuple[int, int], list[str]] = {}
        pictures: dict[tuple[int, int], list[str]] = {}
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                paths = [m.group("path") for m in GRAPHICS_RE.finditer(cell)]
                numbers = CAPTION_NUMBERS_RE.findall(cell)
                rest = GRAPHICS_RE.sub("", CAPTION_NUMBERS_RE.sub("", cell)).strip()
                if rest:
                    return match.group(0)
                if paths:
                    pictures[(r, c)] = paths
                elif numbers:
                    captions[(r, c)] = numbers
        if not captions:
            return match.group(0)
        out = []
        for (r, c), paths in sorted(pictures.items()):
            column = sorted(row for row, col in captions if col == c)
            above = [row for row in column if row < r]
            below = [row for row in column if row > r]
            row = above[-1] if above else (below[0] if below else None)
            numbers = captions.get((row, c), []) if row is not None else []
            out.append(register_figures(figures, numbers, paths))
        return "\n" + "\n".join(out) + "\n"

    return TABULAR_RE.sub(fix, text)


def extract_figures(text: str, figures: Figures) -> str:
    """Подписанные рисунки → ``\\dmfig{N}`` на их месте; без подписи — как есть."""
    def register(numbers: list[str], paths: list[str]) -> str:
        return register_figures(figures, numbers, paths)

    def env(match: re.Match) -> str:
        block = match.group(0)
        paths = [m.group("path") for m in GRAPHICS_RE.finditer(block)]
        captions = " ".join(m.group("text") for m in CAPTION_RE.finditer(block))
        numbers = [m.group("num") for m in CAPTION_NUMBERS_RE.finditer(captions)]
        if not numbers:
            tail = TRAILING_CAPTION_RE.match(text, match.end())
            if tail:
                numbers = CAPTION_NUMBERS_RE.findall(tail.group("caption"))
                env.consumed.append((match.end(), tail.end()))
        return register(numbers, paths)
    env.consumed = []

    # Подпись после figure-окружения вырезается отдельно: сначала отметки.
    out = []
    pos = 0
    for match in FIGURE_ENV_RE.finditer(text):
        if match.start() < pos:
            continue
        out.append(text[pos:match.start()])
        out.append(env(match))
        pos = match.end()
        if env.consumed and env.consumed[-1][0] == match.end():
            pos = env.consumed[-1][1]
    out.append(text[pos:])
    text = "".join(out)

    out = []
    pos = 0
    for match in GRAPHICS_RE.finditer(text):
        tail = TRAILING_CAPTION_RE.match(text, match.end())
        if not tail:
            continue
        out.append(text[pos:match.start()])
        numbers = CAPTION_NUMBERS_RE.findall(tail.group("caption"))
        out.append(register(numbers, [match.group("path")]))
        pos = tail.end()
    out.append(text[pos:])
    text = "".join(out)

    # «134. Укажите … хорду Рис. 1»: подпись в тексте, картинка без подписи
    # рядом — ближайшая (сначала ниже, потом выше) в пределах страницы.
    def stray(text: str) -> str:
        # Каждая подпись ищется заново в уже изменённом тексте: замена
        # картинки перед подписью сдвигает всё, что после неё.
        result = text
        pos = 0
        while True:
            match = STRAY_CAPTION_RE.search(result, pos)
            if match is None:
                return result
            start, end = match.span()
            number = match.group("num")
            if number in figures.by_number:
                result = result[:start] + result[end:]
                pos = start
                continue
            after = GRAPHICS_RE.search(result, end, end + 800)
            before = None
            for candidate in GRAPHICS_RE.finditer(result, max(0, start - 800), start):
                before = candidate
            pick = after or before
            if pick is None:
                figures.stray_captions.append(number)
                result = result[:start] + result[end:]
                pos = start
                continue
            figures.add(number, pick.group("path"))
            token = FIGURE_TOKEN.format(number)
            if pick is after:
                result = result[:start] + result[end:pick.start()] + token + result[pick.end():]
                pos = start
            else:
                result = result[:pick.start()] + token + result[pick.end():start] + result[end:]
                pos = pick.start() + len(token) + (start - pick.end())

    text = stray(text)
    # Обёртки float без картинок (рисунки уже вынесены) — не нужны условию.
    text = re.sub(r"\\(?:begin|end)\{(?:center|table|figure)\}(?:\[[^\]]*\])?", "", text)
    return remove_group_commands(text, re.compile(r"\\captionsetup\s*\{"))


def _figure_numbers(nums: str) -> list[str]:
    """«5, 6», «5 и 6», «5–7» → номера рисунков."""
    result: list[str] = []
    for part in re.split(r"\s*(?:,|и)\s*", nums):
        span = re.match(r"(\d+)\s*[–-]\s*(\d+)$", part)
        if span and int(span.group(2)) - int(span.group(1)) < 6:
            result.extend(str(n) for n in range(int(span.group(1)), int(span.group(2)) + 1))
        elif part.strip().isdigit():
            result.append(part.strip())
    return result


def referenced_figures(body: str, figures: Figures) -> list[str]:
    found = []
    for match in FIG_REF_RE.finditer(_without_math(body)):
        for number in _figure_numbers(match.group("nums")):
            if number in figures.by_number and number not in found:
                found.append(number)
    return found


def _without_math(value: str) -> str:
    return MATH_SPAN_RE.sub(lambda m: " " * len(m.group(0)), value)


def replace_figure_refs(body: str, figures: Figures) -> tuple[str, list[str]]:
    """Ссылка на рисунок книги → сам рисунок; вернуть ненайденные номера."""
    missing: list[str] = []

    def fix(match: re.Match) -> str:
        numbers = _figure_numbers(match.group("nums"))
        if not numbers:
            return match.group(0)
        pics = []
        for number in numbers:
            paths = figures.by_number.get(number)
            if not paths:
                missing.append(number)
                return match.group(0)
            pics.extend(rf"\taskpic{{{path}}}" for path in paths)
        joined = " ".join(dict.fromkeys(pics))
        if match.group("paren") and match.group("close"):
            return joined
        word = match.group("word")
        lead = match.group("paren") or ""
        close = match.group("close") or ""
        return f"{lead}{word} {joined}{close}"

    parts, pos = [], 0
    for span in MATH_SPAN_RE.finditer(body):
        parts.append(FIG_REF_RE.sub(fix, body[pos:span.start()]))
        parts.append(span.group(0))
        pos = span.end()
    parts.append(FIG_REF_RE.sub(fix, body[pos:]))
    text = "".join(parts)
    # «(\taskpic{a})» → без скобок; «изображены \taskpic{a}» — как есть.
    return re.sub(r"[ \t]+(?=\\taskpic)", " ", text), missing


# Разряды «4 325», «20 104 050»: книга отделяет тысячи пробелом, OCR даёт
# обычный или неразрывный пробел. Иначе канон обернёт части порознь:
# «$4$ $325$».
# Разряды: «4 325», «20 104 050», а также как попало у OCR — «3616 356»
# (книга: 3 616 356) и «3617009». Число от пяти цифр — с тонкими пробелами.
_THOUSANDS_RE = re.compile(
    r"(?<![\w.,{}\\])(?P<num>\d{1,4}(?:[ \u00a0\u2009\u202f]\d{3})+|\d{5,})(?![\w]|[.,]\d)")
# Имя файла картинки («…-8ef57041ca2e-…», «…-12345-…») разрядами не трогаем.
# \\taskpic{путь} — подписанный рисунок после replace_figure_refs.
_GRAPHIC_RE = re.compile(r"\\(?:includegraphics|taskpic)(?:\[[^\]]*\])?\{[^{}]*\}")
_MATH_NUMBER_RE = re.compile(
    r"^(?P<open>\\\(|\$)\s*(?P<num>\d{1,4}(?:\s*(?:\\,|\\ |~)?\s*\d{3})+)\s*(?P<close>\\\)|\$)$")


def thin_groups(digits: str) -> str:
    """«3616356» → «3\\,616\\,356»."""
    digits = re.sub(r"\\,|\\ |~|\s", "", digits)
    groups = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return r"\,".join(groups)


def group_thousands(value: str) -> str:
    """«4 325» → «$4\\,325$» в тексте и в формуле из одного числа."""
    def prose(chunk: str) -> str:
        out, pos = [], 0
        for graphic in _GRAPHIC_RE.finditer(chunk):
            out.append(_THOUSANDS_RE.sub(lambda m: "$" + thin_groups(m.group("num")) + "$", chunk[pos:graphic.start()]))
            out.append(graphic.group(0))
            pos = graphic.end()
        out.append(_THOUSANDS_RE.sub(lambda m: "$" + thin_groups(m.group("num")) + "$", chunk[pos:]))
        return "".join(out)

    def math(span: str) -> str:
        match = _MATH_NUMBER_RE.match(span)
        if not match:
            return span
        return match.group("open") + thin_groups(match.group("num")) + match.group("close")

    out, pos = [], 0
    for span in MATH_SPAN_RE.finditer(value):
        out.append(prose(value[pos:span.start()]))
        out.append(math(span.group(0)))
        pos = span.end()
    out.append(prose(value[pos:]))
    return "".join(out)


# --------------------------------------------------------------------------
# Пункты «1) 2) 3)» колонками
# --------------------------------------------------------------------------

_ITEM_LABEL_RE = re.compile(
    r"(?:(?<=^)|(?<=\n)|(?<=[;:.?!])|(?<=\\\))|(?<=\\\\))[ \t]*(?P<label>\d{1,2})\)(?=[ \t~]|$)",
    re.M)
_ABBREV_RE = re.compile(r"(?:\b(?:рис|см|стр|п|с|№)\.)\s*$", re.I)


def reorder_column_items(body: str) -> tuple[str, bool]:
    """«1) …; 3) …⏎2) …; 4) …» → пункты по порядку номеров.

    Метка пункта — «k)» в начале строки или после знака препинания, вне
    формул и не после «рис.». Берётся последовательность 1, 2, …, m (m ≥ 2)
    по первым вхождениям после пункта 1; остальное — текст пунктов.
    """
    plain = _without_math(body)
    plain = re.sub(r"\\begin\{array\}.*?\\end\{array\}", lambda m: " " * len(m.group(0)), plain, flags=re.S)
    tokens = [m for m in _ITEM_LABEL_RE.finditer(plain)
              if not _ABBREV_RE.search(plain[max(0, m.start() - 6):m.start()])]
    ones = [m for m in tokens if m.group("label") == "1"]
    if not ones:
        return body, False
    start = ones[0]
    chosen = {1: start}
    expected = 2
    while True:
        nxt = next((m for m in tokens if m.start() > start.start()
                    and int(m.group("label")) == expected
                    and m not in chosen.values()), None)
        if nxt is None:
            break
        chosen[expected] = nxt
        expected += 1
    if len(chosen) < 2:
        return body, False
    ordered = sorted(chosen.items(), key=lambda pair: pair[1].start())
    if [label for label, _m in ordered] == sorted(chosen):
        return body, False
    stem = body[:start.start()].rstrip()
    chunks = {}
    for index, (label, match) in enumerate(ordered):
        end = ordered[index + 1][1].start() if index + 1 < len(ordered) else len(body)
        chunk = body[match.end():end].strip()
        chunk = re.sub(r"(?:\s*\\\\)+$", "", chunk).strip()
        chunks[label] = chunk
    last = max(chunks)
    lines = [stem] if stem else []
    for label in sorted(chunks):
        text = chunks[label]
        if label != last:
            text = re.sub(r"[;.,]\s*$", "", text) + ";"
        lines.append(f"{label}) {text}")
    return "\n".join(lines), True


# --------------------------------------------------------------------------
# Разбор зон
# --------------------------------------------------------------------------

def _line_events(text: str) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    variants = [(m.start(), m.end(), int(m.group("k"))) for m in VARIANT_LINE_RE.finditer(text)]
    works = [(m.start(), m.end(), int(m.group("n"))) for m in WORK_LINE_RE.finditer(text)]
    return variants, works


def _task_candidates(text: str, start: int = 0, end: int | None = None) -> list[tuple[int, int, int]]:
    end = len(text) if end is None else end
    return [(m.start(), m.end(), int(m.group("number")))
            for m in TASK_RE.finditer(text, start, end)]


def exercise_variants(text: str, start: int, end: int, variants: list,
                      expected: int) -> list[tuple[int, int, int]]:
    """(вариант, начало, конец) упражнений: «Вариант k», за которым задача 1."""
    candidates = _task_candidates(text, start, end)
    zones = []
    want = 1
    for v_start, v_end, k in variants:
        if not start <= v_start < end or k != want:
            continue
        following = next((n for b, _e, n in candidates if b > v_end), None)
        if following is not None and following <= 2:
            zones.append([k, v_end])
            want += 1
        if want > expected:
            break
    if not zones:
        # Заголовков вариантов OCR не сохранил: варианты — по сбросу
        # нумерации, но только если их несколько (иначе это не ДМ).
        previous = 0
        for begin, _e, number in candidates:
            if number == 1 and (not zones or previous >= 5):
                zones.append([len(zones) + 1, begin])
            previous = number if number > previous or number == 1 else previous
        if len(zones) < 2:
            zones = []
    result = []
    for index, (k, begin) in enumerate(zones):
        stop = zones[index + 1][1] if index + 1 < len(zones) else end
        result.append((k, begin, stop))
    return result


def _clean_running(zone: str) -> str:
    zone = VARIANT_LINE_RE.sub("", zone)
    zone = RUNNING_LINE_RE.sub("", zone)
    return PAGE_NUMBER_RE.sub("", zone)


def _similar(a: str, b: str) -> float:
    def norm(value: str) -> str:
        return re.sub(r"[^а-яё]", "", value.lower().replace("ё", "е"))
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


_SECTION_START_RE = re.compile(r"(?m)^[ \t]*" + _SECTION)


def heading_text(title: str) -> str:
    """«Ряд натуральных чисел. \\\\ Десятичная…», «\\(\\frac{\\text { A }}{\\text { B }}\\)» → текст."""
    title = re.sub(r"\\text\s*\{([^{}]*)\}", r" \1 ", title)
    title = re.sub(r"\\\\|\\frac|\\[()\[\]]|[{}]", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def headings(text: str) -> list[tuple[int, int, str]]:
    """``\\section*{…}`` отдельной строкой: (начало, конец, текст заголовка)."""
    found = []
    for match in _SECTION_START_RE.finditer(text):
        try:
            title, end = read_group(text, match.end() - 1)
        except ValueError:
            continue
        line_end = text.find("\n", end)
        if text[end:line_end if line_end >= 0 else len(text)].strip():
            continue
        found.append((match.start(), end, heading_text(title)))
    return found


def replace_headings(text: str) -> str:
    """Заголовки посреди условия (подпись диаграммы, таблицы) — текстом."""
    for start, end, title in reversed(headings(text)):
        text = text[:start] + title + text[end:]
    return text


def split_trailing_headings(body: str) -> tuple[str, list[str]]:
    """Заголовки в конце блока — тема следующей задачи; внутри — текст."""
    found = []
    while True:
        items = headings(body)
        if not items or body[items[-1][1]:].strip():
            break
        start, _end, title = items[-1]
        found.insert(0, title)
        body = body[:start].rstrip()
    return replace_headings(body), found


def strip_plain_heading(body: str, title: str) -> tuple[str, str]:
    """Заголовок темы простой строкой (OCR потерял ``\\section*``) в конце
    блока: «…\\⏎Прямая. Луч». Снимается, если совпадает с темой из таблицы."""
    lines = body.rstrip().split("\n")
    for size in (1, 2, 3):
        if len(lines) <= size:
            break
        tail = " ".join(re.sub(r"\\\\\s*$", "", line).strip() for line in lines[-size:])
        plain = MATH_SPAN_RE.sub(" ", tail)
        if tail and len(plain) <= len(title) + 15 and _similar(tail, title) >= 0.8:
            return "\n".join(lines[:-size]).rstrip(), tail
    return body, ""


def _topic_for(number: int, topics: list[dict]) -> dict | None:
    current = None
    for topic in topics:
        if topic["first"] <= number:
            current = topic
    return current


def adopt_following_pictures(text: str, figures: Figures, diagnostics: dict) -> str:
    """Подпись потеряна, картинка — ниже ссылки, иногда в блоке следующей
    задачи (после её пунктов): ссылка на неизвестный рисунок берёт первую
    картинку без подписи после себя в пределах страницы."""
    plain = _without_math(text)
    claims = []
    taken = set()
    for match in FIG_REF_RE.finditer(plain):
        for number in _figure_numbers(match.group("nums")):
            if number in figures.by_number or number in {n for n, _p in claims}:
                continue
            picture = next((m for m in GRAPHICS_RE.finditer(text, match.end(), match.end() + 1500)
                            if m.start() not in taken), None)
            if picture is None:
                continue
            taken.add(picture.start())
            claims.append((number, picture))
    for number, picture in sorted(claims, key=lambda item: -item[1].start()):
        figures.add(number, picture.group("path"))
        diagnostics["figures_caption_lost"].append(f"рис. {number}")
        text = text[:picture.start()] + FIGURE_TOKEN.format(number) + text[picture.end():]
    return text


def adopt_uncaptioned(marker: Marker, body: str, figures: Figures,
                      used_figures: set[str], diagnostics: dict) -> str:
    """Подпись потеряна, а картинка стоит в самой задаче со ссылкой
    («…на рисунке 16.\\⏎\\includegraphics{…}»): ссылка получает её."""
    unknown = []
    for match in FIG_REF_RE.finditer(_without_math(body)):
        for number in _figure_numbers(match.group("nums")):
            if number not in figures.by_number and number not in unknown:
                unknown.append(number)
    bare = list(GRAPHICS_RE.finditer(body))
    if not unknown or len(bare) < len(unknown):
        return body
    for number, picture in zip(unknown, bare):
        figures.add(number, picture.group("path"))
        used_figures.add(number)
        diagnostics["figures_caption_lost"].append(f"{marker.external_id}: рис. {number}")
    for picture in reversed(bare[:len(unknown)]):
        body = body[:picture.start()] + body[picture.end():]
    return body


def build_task(marker: Marker, body: str, path: list[str], figures: Figures,
               used_figures: set[str], diagnostics: dict) -> TaskDraft:
    own = referenced_figures(body, figures)
    # Рисунок, на который ссылается задача, стоит в ней; на прежнем месте
    # (у соседней задачи) его нет. Без ссылки — остаётся по месту.
    positional: list[str] = []

    def place(match: re.Match) -> str:
        number = match.group("num")
        if number not in used_figures:
            # Без ссылки — рисунок той задачи, у которой стоит; в конец
            # условия, а не посреди фразы, куда его поставил OCR.
            diagnostics["figures_positional"].append(f"{marker.external_id}: рис. {number}")
            positional.extend(figures.by_number[number])
        return ""
    body = FIGURE_TOKEN_RE.sub(place, body)
    body = adopt_uncaptioned(marker, body, figures, used_figures, diagnostics)
    body, missing = replace_figure_refs(body, figures)
    body = restore_stars(body)
    body = wrap_bare_arithmetic(body)
    body = group_thousands(body)
    body, reordered = reorder_column_items(body)
    if reordered:
        diagnostics["column_items"].append(marker.external_id)
    task = task_from_block(marker, body, path)
    if positional:
        task.text_latex = (task.text_latex.rstrip() + "\n"
                           + "\n".join(rf"\taskpic{{{p}}}" for p in positional))
    # «Несбалансированные окружения» — шум от array в пунктах-колонках.
    task.warnings = [w for w in task.warnings if "Несбалансированные" not in w]
    if missing:
        task.warnings.append("Не найден рисунок по подписи: " + ", ".join(missing))
        diagnostics["figures_missing_by_task"][marker.external_id] = missing
    return task


_TAIL_RE = re.compile(r"(?<=[.?!])(?:[ \t]*\\\\)?\s+(?=[А-ЯЁ][а-яё]*(?:\s+[^\s]+){2,}[.?!]?\s*$)")


def tidy_fields(task: TaskDraft) -> bool:
    """Хвосты OCR в полях: «\\\\» в конце, перенос строки посреди фразы и
    общая фраза после последнего пункта («2) 374? Ответ запишите в виде
    двойного неравенства») — в условие, иначе при выборе части пунктов она
    пропадёт. Вернуть, перенесён ли хвост."""
    def tidy(value: str) -> str:
        value = re.sub(r"(?<=[а-яё,])[ \t]*\n[ \t]*(?=[а-яё])", " ", value or "")
        value = re.sub(r"^(?:\s*\\\\)+\s*", "", value)
        return re.sub(r"(?:\s*\\\\)+\s*$", "", value).rstrip()

    task.text_latex = tidy(task.text_latex)
    for item in task.subitems:
        item.text_latex = tidy(item.text_latex)
    if len(task.subitems) < 2:
        return False
    last = task.subitems[-1]
    plain = MATH_SPAN_RE.sub(lambda m: "x" * len(m.group(0)), last.text_latex)
    match = _TAIL_RE.search(plain)
    if not match or any(_TAIL_RE.search(MATH_SPAN_RE.sub("x", item.text_latex))
                        for item in task.subitems[:-1]):
        return False
    head = last.text_latex[:match.start()].strip()
    if not head:
        return False
    # Голова последнего пункта — того же масштаба, что и другие пункты:
    # иначе фраза может быть вопросом самого пункта («3) Цена 200 р.
    # Найдите новую цену…»), а не общим требованием.
    def size(value: str) -> int:
        return len(MATH_SPAN_RE.sub("x", value or ""))
    longest = max(size(item.text_latex) for item in task.subitems[:-1])
    if size(head) > 2 * longest + 10 or re.search(r"[.?!]\s+\S", MATH_SPAN_RE.sub("x", head)):
        return False
    tail = last.text_latex[match.end():].strip()
    if not re.search(r"[.?!]\)?$", tail):
        tail += "."
    last.text_latex = re.sub(r"(?:\s*\\\\)+$|[.;,]$", "", head)
    task.text_latex = task.text_latex.rstrip() + "\n" + tail
    task.warnings.append("Общая фраза перенесена из последнего пункта в условие: проверить")
    return True


def _finish(task: TaskDraft, grade: int) -> None:
    # lift_common_tail (Потоскуев) не проверяет масштаб головы пункта и
    # уносит в условие вопрос самого пункта — здесь tidy_fields с защитой.
    tidy_fields(task)
    _finish_fields(task)
    canon_fields(task)
    # «-$140^{\\circ}$» — минус снаружи формулы выйдет дефисом.
    for item in [task, *task.subitems]:
        item.text_latex = re.sub(r"(?:(?<=^)|(?<=[\s(]))-(\$|\\\()(?=\d)", r"\1-", item.text_latex)
    finalize_draft_images(task)
    task.grade_band_codes = [f"GRADE_{grade}"] if grade else []
    fields = [task.text_latex] + [item.text_latex for item in task.subitems]
    if any(math_delimiters_broken(value) for value in fields):
        task.warnings.append("Вложенные или незакрытые формулы: сверить с книгой")
        task.confidence = max(0.0, task.confidence - 0.3)


def parse_exercises(text: str, zones: list, book: dict, figures: Figures,
                    used: set[str], diagnostics: dict) -> list[TaskDraft]:
    spec = book.get("exercises") or {}
    topics = spec.get("topics") or []
    expected = spec.get("tasks")
    tasks: list[TaskDraft] = []
    by_number_topic: dict[int, str] = {}
    for k, start, end in zones:
        zone = _clean_running(text[start:end])
        candidates = _task_candidates(zone)
        chain = monotonic_numbers(candidates, 0, 6, expected)
        markers = [Marker(b, e, f"ДМ.В{k}/{n}") for b, e, n in chain]
        numbers = [n for _b, _e, n in chain]
        diagnostics["tasks_by_variant"][f"В{k}"] = len(markers)
        top = expected or (max(numbers) if numbers else 0)
        diagnostics["missing_task_ids"].extend(
            f"ДМ.В{k}/{n}" for n in range(1, top + 1) if n not in set(numbers))
        # Заголовок перед первой задачей варианта.
        preamble, lead = split_trailing_headings(zone[:markers[0].start] if markers else zone)
        heading = " ".join(lead)
        first_topic = _topic_for(numbers[0], topics) if numbers else None
        if not heading and first_topic:
            heading = strip_plain_heading(preamble, first_topic["title"])[1]
        found_titles = []
        for index, (marker, raw) in enumerate(blocks(zone, markers)):
            number = numbers[index]
            topic = _topic_for(number, topics)
            if topic:
                # Смешанная тема («Повторение»): темы отдельных задач по номеру.
                title = topic["title"]
                code = ((spec.get("numbers") or {}).get(str(number))
                        or topic.get("topic", ""))
                if number == topic["first"]:
                    found_titles.append((topic["title"], heading))
            else:
                title = heading or by_number_topic.get(number, "") or "Без темы"
                code = ""
            by_number_topic.setdefault(number, title)
            body, next_heading = split_trailing_headings(raw)
            following = numbers[index + 1] if index + 1 < len(numbers) else None
            next_topic = _topic_for(following, topics) if following else None
            if not next_heading and next_topic and next_topic["first"] == following:
                body, plain = strip_plain_heading(body, next_topic["title"])
                if plain:
                    next_heading = [plain]
            path = [EXERCISES_TITLE, title, f"Вариант {k}"]
            task = build_task(marker, body, path, figures, used, diagnostics)
            task.source_number = str(number)
            task.collection_title = f"Вариант {k}"
            task.topic_original = title
            task.topic_code = code
            _finish(task, book.get("grade", 0))
            tasks.append(task)
            if next_heading:
                heading = " ".join(next_heading)
        for title, seen in found_titles:
            if not seen or _similar(title, seen) < 0.6:
                diagnostics["topic_headings_mismatch"].append(
                    f"В{k}: «{title}» — в тексте «{seen or '—'}»")
    return tasks


def work_zones(text: str, start: int, end: int,
               works: list) -> list[tuple[int, int, int, int]]:
    """(вариант, номер работы, начало, конец): вариант растёт при сбросе номера."""
    found = [(s, e, n) for s, e, n in works if start <= s < end]
    zones = []
    variant = 1
    previous = 0
    for index, (s, e, n) in enumerate(found):
        if n <= previous:
            variant += 1
        previous = n
        stop = found[index + 1][0] if index + 1 < len(found) else end
        zones.append((variant, n, e, stop))
    return zones


def parse_tests(text: str, zones: list, book: dict, figures: Figures,
                used: set[str], diagnostics: dict) -> list[TaskDraft]:
    spec = book.get("tests") or {}
    works = {work["number"]: work for work in spec.get("works") or []}
    tasks: list[TaskDraft] = []
    for k, n, start, end in zones:
        zone = _clean_running(text[start:end])
        candidates = _task_candidates(zone)
        work = works.get(n, {})
        chain = monotonic_numbers(candidates, 0, 3, work.get("tasks"))
        key = f"КР{n}.В{k}"
        # «Тема. …» — до первой задачи, иногда в две строки.
        head = zone[:chain[0][0]] if chain else zone
        theme = THEME_RE.sub("", replace_headings(head))
        theme = re.sub(r"\s*\\\\\s*|\s+|[{}]", " ", theme)
        theme = re.sub(r"\s+", " ", theme).strip().rstrip(".")
        title = work.get("title") or theme
        if work.get("title") and theme and _similar(work["title"], theme[:len(work["title"]) + 5]) < 0.6:
            diagnostics["topic_headings_mismatch"].append(f"{key}: «{work['title']}» — в тексте «{theme}»")
        diagnostics["tests_by_work"][key] = len(chain)
        if work.get("tasks") and len(chain) != work["tasks"]:
            diagnostics["tests_task_count_mismatch"].append(
                f"{key}: {len(chain)} из {work['tasks']}")
        work_title = f"Контрольная работа № {n}" + (f". {title}" if title else "")
        markers = [Marker(b, e, f"{key}/{m}") for b, e, m in chain]
        for marker, raw in blocks(zone, markers):
            body, _next = split_trailing_headings(raw)
            path = [TESTS_TITLE, work_title, f"Вариант {k}"]
            task = build_task(marker, body, path, figures, used, diagnostics)
            task.source_number = marker.external_id.rsplit("/", 1)[1]
            task.collection_title = f"Вариант {k}"
            task.topic_original = title
            # Итоговая работа смешанная: темы по номеру задачи.
            task.topic_code = ((work.get("topics") or {}).get(task.source_number)
                               or work.get("topic", ""))
            _finish(task, book.get("grade", 0))
            tasks.append(task)
    expected_variants = spec.get("variants")
    if expected_variants:
        found = sorted({k for k, *_rest in zones})
        if found != list(range(1, expected_variants + 1)):
            diagnostics["tests_variants_mismatch"] = found
    return tasks


def parse_merzlyak_dm(text: str, book: dict | None = None) -> tuple[list[TaskDraft], dict]:
    """Разбор TEX Mathpix; ``book`` — описание книги вместо поиска по титулу."""
    text, repairs = apply_source_repairs(text.replace("\r\n", "\n"), REPAIRS_PATH)
    figures = Figures()
    text = prepare_text(text, figures)
    book = book or detect_book(text)
    diagnostics: dict = {
        "book": book["title"] if book else "",
        "book_unknown": bool(not book or book.get("unknown")),
        "tasks_by_variant": {},
        "tests_by_work": {},
        "missing_task_ids": [],
        "topic_headings_mismatch": [],
        "tests_task_count_mismatch": [],
        "column_items": [],
        "figures_positional": [],
        "figures_missing_by_task": {},
        "figures_caption_lost": [],
        "source_repairs_applied": repairs,
    }
    book = book or {"title": "", "grade": 0}
    if book.get("grade") == 5:
        # «Саша \\(-\\frac{5}{10}\\) арбуза» — тире OCR прочитал как минус
        # (в 5 классе отрицательных чисел нет).
        text = re.sub(r"([а-яё])\s*\\\((\\displaystyle\s*)?-\s*(?=\\frac)", r"\1 — \\(\2", text)
    text = extract_figures(text, figures)
    text = adopt_following_pictures(text, figures, diagnostics)
    variants, works = _line_events(text)
    first_work = next((s for s, _e, n in works if n == 1), None)
    exercises_end = first_work if first_work is not None else len(text)
    # Начало контрольных — «Вариант 1» прямо перед «Контрольная работа № 1».
    tests_end = len(text)
    if first_work is not None:
        before = [s for s, _e, k in variants if k == 1 and 0 <= first_work - s < 300]
        if before:
            exercises_end = before[-1]
        tail = BOOK_END_RE.search(text, first_work)
        if tail:
            tests_end = tail.start()
    expected_variants = (book.get("exercises") or {}).get("variants", 4)
    zones = exercise_variants(text, 0, exercises_end, variants, expected_variants)
    if not zones:
        raise ValueError(
            "Не найдены «Упражнения» ДМ Мерзляка: нет строки «Вариант 1» "
            "с задачей 1 после неё")
    diagnostics["exercise_variants"] = [k for k, *_rest in zones]
    if len(zones) != expected_variants:
        diagnostics["exercise_variants_mismatch"] = f"{len(zones)} из {expected_variants}"
    # Все ссылки на рисунки — заранее: рисунок уходит к задаче со ссылкой.
    used = set(referenced_figures(text, figures))
    with numeric_subitem_labels():
        tasks = parse_exercises(text, zones, book, figures, used, diagnostics)
        if first_work is not None:
            tasks += parse_tests(
                text, work_zones(text, exercises_end, tests_end, works),
                book, figures, used, diagnostics)
    diagnostics["figures_numbered"] = len(figures.by_number)
    diagnostics["figures_merged"] = figures.merged
    diagnostics["figure_captions_without_picture"] = figures.stray_captions
    diagnostics["figures_unreferenced"] = sorted(
        set(figures.by_number) - used, key=int)
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["unique_tasks"] = len({t.external_id for t in tasks})
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_section"] = dict(Counter(t.source_path[0] for t in tasks))
    return tasks, diagnostics

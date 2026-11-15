"""Профиль пособия Прокофьева и Корянова «Многогранники» (ЕГЭ, задача С2).

А. А. Прокофьев, А. Г. Корянов. «Математика. ЕГЭ 2013. Многогранники:
типы задач и методы их решения (типовые задания С2)», OCR Mathpix по PDF
(вёрстка в две колонки, страница PDF = страница книги).

Особенности книги:

- главы → параграфы (1.1–1.7, 2.1–2.3, 3.1–3.4), внутри параграфа —
  подзаголовки методов («Координатный метод», «Метод объёмов»…), то
  ``\\section*``, то строкой в тексте; таблица — ``data/koryanov_structure.json``;
- 120 разобранных примеров со сквозной нумерацией: «Пример N. …»,
  «Решение. …», «Ответ: …» — ключ «П17», разбор — авторское решение;
  часть примеров решена несколькими способами («2-й способ …»), после
  ответа бывает «Замечание»; дальше по тексту — теория, она в пример не идёт;
- 176 тренировочных упражнений со сквозной нумерацией (ключ «17») в конце
  параграфов главы 1 и одним блоком в конце главы 2; ответы и указания —
  в конце книги плотным потоком «1. … 2. …», который Mathpix превратил во
  вложенные ``enumerate`` со ``\\setcounter``;
- рисунки «Рис. N» со сквозной нумерацией: ссылка «(см. рис. N)» в
  условии или разборе ставит рисунок в это поле;
- 3.4 «Опорные задачи» — теоремы с доказательствами, в импорт не входят.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .textbook_parser import (
    Marker, TaskDraft, clean, finalize_draft_images, task_from_block)
from .volchkevich_parser import canon_field


DATA_DIR = Path(__file__).with_name("data")
STRUCTURE_PATH = DATA_DIR / "koryanov_structure.json"
REPAIRS_PATH = DATA_DIR / "koryanov_repairs.json"

SIGNATURE = "Многогранники: \\\\\n типы задач и методы их решения"


def load_structure(path: Path = STRUCTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_repairs(text: str, path: Path = REPAIRS_PATH) -> tuple[str, dict, list[str]]:
    """Сверенные с PDF правки, привязанные к sha256 исходного TEX.

    ``patches`` — точечные замены текста OCR до разбора (фрагмент ``before``
    встречается ровно один раз); ``tasks`` — поля задачи, переписанные по
    скану целиком (``text``, ``answer``, ``solution``); ``figures`` —
    рисунки, которые OCR потерял (номер → файл вырезки из PDF); ``fixes`` —
    точечные правки готового поля карточки после всей нормализации
    (``old`` → ``new``, ``old`` встречается ровно один раз).
    """
    spec = {"tasks": {}, "figures": {}, "fixes": []}
    if not path.exists():
        return text, spec, []
    data = json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    applied: list[str] = []
    for edition in data.get("editions", []):
        if edition.get("source_sha256") != digest:
            continue
        for patch in edition.get("patches", []):
            count = text.count(patch["before"])
            if count != 1:
                raise ValueError(
                    f"Сверенный фрагмент {patch['id']} встречается {count} раз")
            text = text.replace(patch["before"], patch["after"], 1)
            applied.append(patch["id"])
        spec["tasks"].update(edition.get("tasks", {}))
        spec["figures"].update(edition.get("figures", {}))
        spec["fixes"].extend(edition.get("fixes", []))
    return text, spec, applied


# --------------------------------------------------------------------------
# Подготовка текста OCR
# --------------------------------------------------------------------------

# «Peшeние», «Peueние», «Peueнue», «Pешение» — латиница и «u» вместо «ш»/«и».
SOLUTION_WORD_RE = re.compile(r"[PР][eе][шuщ][eе][нn][иu][eе]\s*\.")
ANSWER_WORD_RE = re.compile(r"(?:Ombem|OTBET|O[тm]в[eе]т|Отвeт)(?=\s*[.:}])")
# «\(B\) единичном кубе» — латинский двойник предлога «В» в формуле.
LOOKALIKE_LEAD_RE = re.compile(r"(?m)(?:(?<=^)|(?<=[.:] ))\\\(\s*([BC])\s*\\\)\s+(?=[а-яё])")
# «6 с м», «5 c м^{3}», «8 c м^{3}» — единица, разорванная OCR.
SPLIT_CM_RE = re.compile(r"(?<=\d)\s*[сc]\s*[мM](?![а-яё])")
DISPLAY_RE = re.compile(r"\\\[(?P<body>.*?)\\\]", re.S)
# «\text { Ombem: }», «\text { Ответ }:», «\text { Ombem. }» внутри выносной.
DISPLAY_ANSWER_RE = re.compile(
    r"(?:&\s*)?\\text\s*\{\s*Ответ\s*[:.]?\s*\}\s*:?\s*(?:&\s*)?")


def _close_envs(body: str) -> str:
    """Дописывает \\end{…} к окружениям, оставшимся открытыми."""
    stack: list[str] = []
    for match in re.finditer(r"\\(begin|end)\{([^{}]+)\}", body):
        if match.group(1) == "begin":
            stack.append(match.group(2))
        elif stack and stack[-1] == match.group(2):
            stack.pop()
    return body + "".join(f"\n\\end{{{env}}}" for env in reversed(stack))


def _strip_envs(body: str) -> str:
    body = re.sub(r"\\(?:begin|end)\{[^{}]+\}(?:\{[^{}]*\})?", " ", body)
    body = re.sub(r"(?<!\\)&|\\\\|\\quad", " ", body)
    return re.sub(r"\s+", " ", body).strip()


def lift_display_answers(text: str) -> str:
    """«…=\\frac{\\sqrt6}3 . \\quad \\text{Ответ:} \\frac{\\sqrt6}3 .» внутри
    выносной формулы → формула до ответа и строка «Ответ: \\(…\\).»."""
    def fix(match: re.Match) -> str:
        body = match.group("body")
        answer = DISPLAY_ANSWER_RE.search(body)
        if answer is None:
            return match.group(0)
        head = re.sub(r"(?:\\quad|\\\\|\s|&)*$", "", body[:answer.start()])
        tail = _strip_envs(body[answer.end():])
        tail = re.sub(r"\\text\s*\{\s*\.?\s*\}", "", tail)
        tail = re.sub(r"\\text\s*\{\s*(и|или)\s*\}", r"\\) \1 \\(", tail)
        tail = re.sub(r"\s*\.\s*$", "", tail).strip()
        out = ""
        if _strip_envs(head):
            out = "\\[" + _close_envs(head) + "\n\\]\n\n"
        return out + f"Ответ: \\({tail}\\)."
    return DISPLAY_RE.sub(fix, text)


def prepare_text(text: str) -> str:
    text = SOLUTION_WORD_RE.sub("Решение.", text)
    text = ANSWER_WORD_RE.sub("Ответ", text)
    text = lift_display_answers(text)
    text = LOOKALIKE_LEAD_RE.sub(lambda m: "В " if m.group(1) == "B" else "С ", text)
    text = SPLIT_CM_RE.sub(" см", text)
    text = re.sub(r"(?<![A-Za-zА-Яа-я\\])[сc]\s*[мM](?=\^|\s*\\right)", "см", text)
    text = text.replace("\\mathrm{och}", "\\text{осн}")
    # «\(6 см, 10 см\)» — перечень длин: число формулой, единица текстом.
    text = re.sub(r"\\\(\s*(\d+(?:,\d+)?\s*см(?:\s*,\s*\d+(?:,\d+)?\s*см)+)\s*\\\)",
                  lambda m: ", ".join("\\(" + re.sub(r"\s*см", "", part).strip() + "\\) см"
                                      for part in m.group(1).split(",") if part.strip()),
                  text)
    # «длина ребра которого равна \(а\)» — кириллическая «а» вместо буквы.
    text = re.sub(r"\\\(\s*а\s*\\\)(?=\.)", r"\\(a\\)", text)
    # «\mathrm{~cm}^{3}» — сантиметры, «\mathrm{~V}» — буква V (объём).
    text = re.sub(r"\\mathrm\{~cm\}", lambda m: "\\text{см}", text)
    text = re.sub(r"\\mathrm\{~([A-Z])\}", r"\1", text)
    # «\(2 \sqrt{30} . C D\)» — конец фразы и начало следующей в одной формуле.
    text = re.sub(r"\\\((?P<body>(?:(?!\\\)).)*?)\s\.\s+(?=[A-Z](?![a-z]))",
                  lambda m: "\\(" + m.group("body").rstrip() + "\\). \\(", text)
    # Градусы: «30°» в тексте — формула, «60°» в формуле — ^{\circ}.
    text = degrees(text)
    # Колонтитул страницы посреди слова: «пирами04.12.2012\\ \href{…}{www.alexlarin.net} ды».
    text = re.sub(r"\d\d\.\d\d\.\d{4}\\\\\s*\\href\{[^{}]*\}\{www\.alexlarin\.net\}\s*", "", text)
    # «ко-\nторого» — перенос слова колонки.
    text = re.sub(r"(?<=[а-яё])-\n[ \t]*\n?[ \t]*(?=[а-яё])", "", text)
    # «\(A B C D A_{1} B_{1} C_{1} D_{1} c\) ребром» — предлог «с» в формуле.
    text = re.sub(r"\s+c\\\)\s+(?=[а-яё])", r"\\) с ", text)
    # «\(B_{1} C_{1}, K\) — середина» — следующая точка в той же формуле.
    text = re.sub(r",\s*([A-Z](?:_\{\d\})?)\\\)(\s+(?:-|—)\s)", r"\\), \\(\1\\)\2", text)
    # «(см. рис.\\ 84)» — ссылка, разорванная переносом строки.
    text = re.sub(r"рис\.\s*\\\\\s*\n\s*(?=\d)", "рис. ", text)
    # «(см. рис. \(31 a\) )» — номер рисунка OCR унёс в формулу.
    text = re.sub(r"рис\.\s*\\\(\s*(\d{1,3})\s*([a-eа-е])?\s*\\\)\s*(?=\))",
                  lambda m: f"рис. {m.group(1)}{m.group(2) or ''}", text)
    return text


# --------------------------------------------------------------------------
# Рисунки
# --------------------------------------------------------------------------

FIGURE_RE = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.S)
GRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{(?P<path>[^{}\s\\]+)\}")
# «Рис. 126», «Рис. \(127_{\text {в }}\)» — номер и, бывает, буква части.
CAPTION_RE = re.compile(
    r"\\caption\{\s*Рис\.?\s*(?:\\\(\s*)?(?P<num>\d{1,3})"
    r"(?:_\{\\text\s*\{\s*(?P<part>[а-я])\s*\}\})?")
# «(см. рис. 1)», «(см. рис. 126a)», «(рис. 5, 6)», «(см. рис. 51 и 52)».
_FIG_NUM = r"\d{1,3}(?:[а-яa-e](?![а-яёa-z]))?"
PAREN_FIG_REF_RE = re.compile(
    r"\(\s*(?:см\.\s*)?рис(?:унок|унке|унки)?\.?\s*(?P<nums>" + _FIG_NUM
    + r"(?:\s*(?:,|и|[-–—])\s*" + _FIG_NUM + r")*)\s*\)")
# «на рисунке 2», «(см. рис. 24), то» уже в скобках; «рис. 23» в тексте.
INLINE_FIG_REF_RE = re.compile(
    r"(?P<word>[Рр]ис(?:ун(?:ок|ке|ка|ки|ках|кам|ком|ками))?\.?)\s*(?P<nums>" + _FIG_NUM
    + r"(?:\s*(?:,|и|[-–—])\s*" + _FIG_NUM + r")*)")
_LATIN_PARTS = str.maketrans("abe", "абе")


@dataclass
class Figures:
    by_number: dict[str, list[str]] = field(default_factory=dict)
    position: dict[str, int] = field(default_factory=dict)


FIGURE_MARK_RE = re.compile(r"\x00(?P<num>[^\x00]+)\x00")
# «равно-» + рисунок + «бедренных»: перенос слова, которое обтекало рисунок.
_WRAPPED_HYPHEN_RE = re.compile(
    r"(?<=[а-яё])-[ \t]*\n\s*(?P<marks>(?:\x00[^\x00]+\x00\s*)*)(?=[а-яё])")


def extract_figures(text: str, extra: dict[str, str]) -> tuple[str, Figures]:
    """Подписанные «Рис. N» рисунки уходят в индекс, на их месте — пусто.

    Позиция рисунка нужна, чтобы найти пример, внутри разбора которого он
    стоит: метка рисунка живёт в тексте до конца правок и снимается
    последней. Рисунки без подписи (титульный лист) остаются в тексте и в
    задачи не попадают — титул вне зоны разбора.
    """
    figures = Figures()

    def replace(match: re.Match) -> str:
        block = match.group(0)
        paths = [m.group("path") for m in GRAPHICS_RE.finditer(block)]
        caption = CAPTION_RE.search(block)
        if not caption or not paths:
            return block
        number = caption.group("num") + (caption.group("part") or "")
        figures.by_number.setdefault(number, []).extend(paths)
        return f"\n\x00{number}\x00\n"

    text = FIGURE_RE.sub(replace, text)
    # Рисунок, который OCR потерял (на его месте строка «Рис. 109»),
    # вырезан из PDF и задан сверенной правкой.
    for number, path in extra.items():
        figures.by_number.setdefault(str(number), []).append(path)
        text = re.sub(r"(?m)^Рис\.\s*" + re.escape(str(number)) + r"\s*$",
                      f"\x00{number}\x00", text, count=1)
    text = _WRAPPED_HYPHEN_RE.sub(lambda m: m.group("marks").strip(), text)
    out: list[str] = []
    last = length = 0
    for match in FIGURE_MARK_RE.finditer(text):
        piece = text[last:match.start()]
        out.append(piece)
        length += len(piece)
        figures.position.setdefault(match.group("num"), length)
        last = match.end()
    out.append(text[last:])
    return "".join(out), figures


def _ref_numbers(raw: str) -> list[str]:
    numbers: list[str] = []
    parts = re.findall(r"\d{1,3}(?:[а-яa-e](?![а-яёa-z]))?|[-–—]", raw)
    for index, part in enumerate(parts):
        if part in "-–—":
            continue
        if index >= 2 and parts[index - 1] in "-–—" and part.isdigit() and parts[index - 2].isdigit():
            first, last = int(parts[index - 2]), int(part)
            if 0 < last - first <= 10:
                numbers.extend(str(n) for n in range(first + 1, last + 1))
                continue
        numbers.append(part.translate(_LATIN_PARTS))
    return numbers


def _paths_for(number: str, figures: Figures) -> list[str] | None:
    if number in figures.by_number:
        return figures.by_number[number]
    base = re.match(r"\d+", number).group(0)
    return figures.by_number.get(base)


def _attach_positional_figures(task: TaskDraft, figures: Figures, used: set[str],
                               ranges: dict[str, tuple[int, int]]) -> list[str]:
    """Рисунок внутри разбора примера без ссылки на него — в конец разбора.

    Ссылки нет только там, где OCR её потерял (сверено с PDF); рисунок
    принадлежит примеру, в тексте которого стоит.
    """
    span = ranges.get(task.external_id)
    if not span:
        return []
    found = []
    for number, position in sorted(figures.position.items(), key=lambda kv: kv[1]):
        base = re.match(r"\d+", number).group(0)
        if base in used or not span[0] <= position < span[1]:
            continue
        used.add(base)
        found.append(number)
        tokens = " ".join(rf"\taskpic{{{path}}}" for path in figures.by_number[number])
        task.author_solution_latex = (task.author_solution_latex.rstrip() + "\n\n" + tokens).strip()
    if found:
        task.warnings.append("Рисунок без ссылки привязан по положению: проверить")
    return found


def attach_figures(task: TaskDraft, figures: Figures, used: set[str]) -> list[str]:
    """Ссылка «(см. рис. N)» → \\taskpic в том поле, где она стоит.

    Номер рисунка книги в задаче не нужен — рисунок стоит в ней самой:
    «(см. рис. 1)» → рисунок, «на рисунке 2» → «на рисунке \\taskpic»,
    буква части остаётся: «(см. рис. 126б)» → «\\taskpic (рис. б)».
    Повторная ссылка на уже поставленный рисунок исчезает, а с буквой
    части — остаётся «(рис. б)». Ссылка на рисунок вне индекса остаётся
    как в книге и попадает в диагностику.
    """
    missing: list[str] = []
    placed: set[str] = set()

    def resolve(raw: str) -> tuple[list[str], list[str], bool]:
        tokens, parts, known = [], [], False
        for number in _ref_numbers(raw):
            paths = _paths_for(number, figures)
            if not paths:
                missing.append(number)
                continue
            known = True
            used.add(re.match(r"\d+", number).group(0))
            letter = re.sub(r"\d+", "", number)
            if letter:
                parts.append(letter)
                if len(paths) > 1 and number not in figures.by_number:
                    # «Рис. 126» — две полосы: части «а, б» и «в, г».
                    index = min(len(paths) - 1, "абвгдеж".find(letter) // 2)
                    paths = paths[index:index + 1]
            for path in paths:
                if path not in placed:
                    placed.add(path)
                    tokens.append(rf"\taskpic{{{path}}}")
        return tokens, parts, known

    def rewrite(value: str) -> str:
        def paren(match: re.Match) -> str:
            tokens, parts, known = resolve(match.group("nums"))
            if not known:
                return match.group(0)
            label = f"(рис. {', '.join(parts)})" if parts else ""
            return " ".join(filter(None, [" ".join(tokens), label])) or "\x00"

        def inline(match: re.Match) -> str:
            # «как показано на рисунке 23» — рисунок уже стоит в задаче:
            # остаётся «на рисунке».
            tokens, parts, known = resolve(match.group("nums"))
            if not known:
                return match.group(0)
            word = match.group("word")
            if word.startswith("рис") and not word.startswith("рисун"):
                word = "рисунке"  # «на рис. 70 эта плоскость» → «на рисунке …»
            return " ".join(filter(None, [word, " ".join(tokens), ", ".join(parts)]))

        value = PAREN_FIG_REF_RE.sub(paren, value or "")
        value = re.sub(r"[ \t]*\x00", "", value)
        value = INLINE_FIG_REF_RE.sub(inline, value)
        return re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", value)

    # Сначала условие: рисунок встаёт туда, где его видит ученик, а
    # повторная ссылка исчезает уже в разборе.
    task.text_latex = rewrite(task.text_latex)
    for sub in task.subitems:
        sub.text_latex = rewrite(sub.text_latex)
    task.author_solution_latex = rewrite(task.author_solution_latex)
    task.author_answer_latex = rewrite(task.author_answer_latex)
    return list(dict.fromkeys(missing))


# --------------------------------------------------------------------------
# Структура: параграфы, подзаголовки методов, зоны
# --------------------------------------------------------------------------

HEADING_RE = re.compile(r"\\section\*\{(?P<title>[^{}]*)\}")
EXAMPLE_RE = re.compile(r"(?m)^[ \t]*(?:\\item\[\][ \t]*)?Пример[ \t]+(?P<number>\d{1,3})\.")
EXERCISES_HEADING = "Тренировочные упражнения"


@dataclass
class Mark:
    pos: int
    end: int
    kind: str  # paragraph | method | exercises | other | example | chapter3
    title: str = ""
    number: int = 0
    paragraph: dict | None = None


def _method_lines(text: str, methods: list[dict], start: int, stop: int) -> list[Mark]:
    """Подзаголовки методов строкой в тексте («Метод объёмов\\\\»)."""
    marks = []
    for method in methods:
        pattern = re.compile(
            r"(?m)^[ \t]*" + re.escape(method["title"]) + r"[ \t]*\}?[ \t]*(?:\\\\)?[ \t]*$")
        for match in pattern.finditer(text, start, stop):
            marks.append(Mark(match.start(), match.end(), "method", method["title"]))
    return marks


def structure_marks(text: str, structure: dict, start: int, stop: int) -> list[Mark]:
    by_heading = {p["heading"]: p for p in structure["paragraphs"]}
    method_titles = {m["title"] for m in structure["methods"]}
    marks: list[Mark] = []
    for match in HEADING_RE.finditer(text, start, stop):
        title = match.group("title").strip()
        if title in by_heading:
            marks.append(Mark(match.start(), match.end(), "paragraph", title,
                              paragraph=by_heading[title]))
        elif title == EXERCISES_HEADING:
            marks.append(Mark(match.start(), match.end(), "exercises", title))
        elif title in method_titles:
            marks.append(Mark(match.start(), match.end(), "method", title))
        else:
            marks.append(Mark(match.start(), match.end(), "other", title))
    marks.extend(_method_lines(text, structure["methods"], start, stop))
    # «Глава 3. Дополнения» строкой без \section — конец упражнений главы 2.
    for match in re.finditer(r"(?m)^[ \t]*Глава\s+\d\.[^\n]*$", text[start:stop]):
        marks.append(Mark(start + match.start(), start + match.end(), "other", match.group(0).strip()))
    for match in EXAMPLE_RE.finditer(text, start, stop):
        marks.append(Mark(match.start(), match.end(), "example", number=int(match.group("number"))))
    return sorted(marks, key=lambda m: m.pos)


# --------------------------------------------------------------------------
# Примеры
# --------------------------------------------------------------------------

SOLUTION_RE = re.compile(r"Решение\s*\.")
ANSWER_RE = re.compile(r"(?:\\item\[\]\s*)?Ответ\s*[:.]")
# После ответа разбор продолжают «Замечание», следующий способ решения.
CONTINUATION_RE = re.compile(
    r"^\s*(?:\\\\\s*)?(?:Решение\.\s*(?=\d-й))?(?:Замечание|Примечание|\d-й\s+способ|[Вв]торой\s+способ|[Дд]ругой\s+способ)")
# Ответ — до пустой строки, переноса «\\» перед текстом или «Замечания».
ANSWER_END_RE = re.compile(r"\n\s*\n|\\\\\s*\n(?=\s*[А-ЯЁA-Z\d])|(?=\s*Замечание)")


@dataclass
class ExampleParts:
    stem: str
    solution: str
    answer: str
    dropped: str


def split_example(body: str) -> ExampleParts:
    """(условие, разбор, ответ, отброшенный хвост).

    Разбор — после «Решение.»; ответ — после последнего «Ответ:» в цепочке
    «ответ → Замечание / N-й способ → ответ…». Текст после ответа, который
    не продолжает разбор, — теория параграфа, в пример не входит.
    """
    solution_at = SOLUTION_RE.search(body)
    answers = list(ANSWER_RE.finditer(body))
    if not answers:
        stem_end = solution_at.start() if solution_at else len(body)
        solution = body[solution_at.end():] if solution_at else ""
        return ExampleParts(body[:stem_end], solution, "", "")
    stem_end = solution_at.start() if solution_at and solution_at.start() < answers[0].start() else answers[0].start()
    sol_start = solution_at.end() if solution_at and solution_at.start() < answers[0].start() else stem_end
    kept_end = len(body)
    last = None
    for index, answer in enumerate(answers):
        if answer.start() < stem_end:
            continue
        tail = body[answer.end():]
        display = re.match(r"\s*\\\[.*?\\\]", tail, re.S)
        if display:
            # «Ответ:» и формула ответа выносной строкой ниже.
            answer_end = answer.end() + display.end()
        else:
            stop = ANSWER_END_RE.search(tail)
            answer_end = answer.end() + (stop.start() if stop else len(tail))
        last = (answer, answer_end)
        following = body[answer_end:answers[index + 1].start() if index + 1 < len(answers) else len(body)]
        if index + 1 < len(answers) and CONTINUATION_RE.match(following):
            continue
        if CONTINUATION_RE.match(following):
            # Замечание или способ без своего ответа — до конца блока.
            kept_end = len(body)
        else:
            kept_end = answer_end
        break
    answer, answer_end = last
    answer_text = body[answer.end():answer_end]
    solution = body[sol_start:kept_end]
    rest = body[answer_end:kept_end]
    if answer_end >= kept_end - 1 or not rest.strip():
        solution = body[sol_start:answer.start()]
    elif re.match(r"\s*(?:\\\\\s*)?(?:Замечание|Примечание)", rest) and not ANSWER_RE.search(rest):
        # После ответа — только замечание: ответ в своём поле, замечание — в разборе.
        solution = body[sol_start:answer.start()].rstrip() + "\n\n" + rest.strip()
    else:
        # Ответ посреди разбора (дальше «Замечание» или другой способ):
        # строка ответа остаётся на месте, как в книге.
        solution = body[sol_start:kept_end]
    return ExampleParts(body[:stem_end], solution, answer_text, body[kept_end:])


def _example_answer(value: str) -> str:
    value = value.strip()
    # «Ответ:» и выносная формула ниже — ответ строкой.
    display = re.fullmatch(r"\\\[(?P<body>.*?)\\\]\s*\.?", value, re.S)
    if display:
        value = "\\(" + re.sub(r"\s+", " ", display.group("body")).strip().rstrip(".").strip() + "\\)"
    value = re.sub(r"\\\\\s*$", "", value).strip()
    value = re.sub(r"\s*\.\s*$", "", value)
    value = re.sub(r"(?<=\\\))\s*\.$", "", value)
    # «Ответ: 5/7.» — дробь.
    value = re.sub(r"^(\d+)\s*/\s*(\d+)$", lambda m: f"\\(\\frac{{{m.group(1)}}}{{{m.group(2)}}}\\)", value)
    return clean(value)


def _clean_solution(value: str) -> str:
    value = re.sub(r"\\\\\s*$", "", value.strip()).strip()
    return clean(value)


# --------------------------------------------------------------------------
# Упражнения
# --------------------------------------------------------------------------

ENUM_TOKEN_RE = re.compile(
    r"\\begin\{enumerate\}|\\end\{enumerate\}|\\setcounter\{enum[iv]+\}\{(?P<counter>\d+)\}"
    r"|(?m:^[ \t]*\\item\b(?:\[[^\]]*\])?)|(?m:^[ \t]*(?P<plain>\d{1,3})\.[ \t]+)")


def exercise_items(zone: str) -> list[tuple[int, str]]:
    """Пункты зоны упражнений: ``\\item`` с номером по счётчику списка и
    строки «17. …» без списка. Текст после ``\\end{enumerate}`` до
    следующего номера — перенос колонки, продолжает последний пункт."""
    items: list[list] = []
    counters: list[int] = []
    for token in ENUM_TOKEN_RE.finditer(zone):
        raw = token.group(0)
        if raw.startswith("\\begin"):
            counters.append(0)
        elif raw.startswith("\\end"):
            if counters:
                counters.pop()
        elif token.group("counter") is not None:
            if counters:
                counters[-1] = int(token.group("counter"))
        elif token.group("plain") is not None:
            items.append([int(token.group("plain")), token.end()])
        else:
            if not counters:
                counters.append(0)
            counters[-1] += 1
            items.append([counters[-1], token.end()])
    out = []
    for index, (number, start) in enumerate(items):
        end = len(zone)
        if index + 1 < len(items):
            nxt = items[index + 1][1]
            head = ENUM_TOKEN_RE.pattern  # noqa: F841 — для читаемости
            # Начало следующего пункта — сам маркер.
            end = zone.rfind("\n", 0, nxt)
            end = max(end, start)
        body = zone[start:end]
        body = re.sub(r"\\(?:begin|end)\{enumerate\}|\\setcounter\{enum[iv]+\}\{\d+\}", "", body)
        out.append((number, body.strip()))
    return out


# --------------------------------------------------------------------------
# Ответы и указания
# --------------------------------------------------------------------------

ANSWER_NUMBER_RE = re.compile(r"(?<![\d,{.])(?P<num>\d{1,3})\s*\.(?=\s|$)")
HINT_RE = re.compile(r"\s*Указание\s*\.\s*")


def _math_spans(value: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\\\(.*?\\\)", value, re.S)]


def answer_stream(zone: str, total: int) -> tuple[dict[int, str], list[str]]:
    """Ответы «1. … 2. …» → {номер: текст}.

    Mathpix превратил начало строки «N.» в ``\\item`` (номер — счётчик
    списка, при ``\\setcounter`` — явный), а глубину вложенности использовал
    вместо пропущенных номеров. Номер внутри строки принимается, только если
    он следующий по порядку: «2,4.», «130 .» и числа ответов не режут поток.
    """
    problems: list[str] = []
    # Перенос строки «100.\\» внутри потока — пробел.
    zone = re.sub(r"\\\\[ \t]*\n", " ", zone)
    # «\frac{3 \sqrt{46}}{\sqrt{239}} . \mathbf{5 0 .} \frac…» — номер в формуле.
    zone = re.sub(r"\s*\.\s*\\mathbf\{\s*(\d)\s*(\d)\s*\.\s*\}\s*",
                  lambda m: f"\\). {m.group(1)}{m.group(2)}. \\(", zone)
    chunks: list[tuple[int | None, str]] = []
    counters: list[tuple[int, bool]] = []
    tokens = list(re.finditer(
        r"\\begin\{enumerate\}|\\end\{enumerate\}|\\setcounter\{enum[iv]+\}\{(?P<counter>\d+)\}|\\item\b", zone))
    for index, token in enumerate(tokens):
        raw = token.group(0)
        if raw.startswith("\\begin"):
            counters.append((0, False))
        elif raw.startswith("\\end"):
            if counters:
                counters.pop()
        elif token.group("counter") is not None:
            if counters:
                counters[-1] = (int(token.group("counter")), True)
        else:
            value, explicit = counters[-1] if counters else (0, False)
            if counters:
                # Явный номер — только у первого пункта после \setcounter:
                # следующие строки списка — уже по номерам внутри строки.
                counters[-1] = (value + 1, False)
            end = tokens[index + 1].start() if index + 1 < len(tokens) else len(zone)
            content = zone[token.end():end].strip()
            if content:
                chunks.append((value + 1 if explicit else None, content))
    answers: dict[int, str] = {}
    current = 0
    for explicit, content in chunks:
        number = explicit if explicit is not None else current + 1
        if explicit is not None and explicit != current + 1:
            problems.append(f"после {current} идёт {explicit}: пропущены ответы")
        spans = _math_spans(content)
        pieces = []
        start = 0
        expected = number + 1
        for match in ANSWER_NUMBER_RE.finditer(content):
            if any(a < match.start() < b for a, b in spans):
                continue
            if int(match.group("num")) != expected:
                continue
            pieces.append((number, content[start:match.start()]))
            number, start, expected = expected, match.end(), expected + 1
        pieces.append((number, content[start:]))
        for key, value in pieces:
            value = value.strip()
            if key in answers:
                problems.append(f"ответ {key} встречается дважды")
            answers[key] = value
        current = number
    missing = [n for n in range(1, total + 1) if n not in answers]
    if missing:
        problems.append("нет ответов: " + ", ".join(map(str, missing)))
    return answers, problems


_DEGREE_RE = re.compile(r"(?<![\\\w])(\d+)\s*°")


def answer_latex(value: str) -> tuple[str, str]:
    """(ответ, указание). Голые числа — в формулу, «60°» — \\(60^{\\circ}\\)."""
    value = re.sub(r"\\\\\s*", " ", value).strip()
    hint = ""
    split = HINT_RE.search(value)
    if split:
        hint = value[split.end():].strip()
        value = value[:split.start()]
        hint = "Указание. " + clean(hint)
    value = re.sub(r"\s*\.\s*$", "", value.strip())
    value = re.sub(r"\\\(\s*\\quad\s*", r"\\(", value)
    value = _LABEL_RE.sub(lambda m: m.group(1).translate(_LATIN_LABELS) + ")", value)
    value = _DEGREE_RE.sub(r"\\(\1^{\\circ}\\)", value)
    value = clean(value)
    return value, hint


# --------------------------------------------------------------------------
# Оформление
# --------------------------------------------------------------------------

# Латинские буквы меток пунктов «a)», «e)» — кириллицей.
_LATIN_LABELS = str.maketrans("abe", "абе")
_LABEL_RE = re.compile(r"(?:(?<=^)|(?<=[;.]\s))([abe])\)(?=\s)")
MATH_RE = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]|\$\$.*?\$\$|\$[^$]*\$", re.S)
# Обозначения многогранников и точек в прозе: «MABCD», «прямой ВF», «МС» —
# OCR оставил вне формулы и смешал латиницу с кириллическими двойниками.
_LOOKALIKES = str.maketrans("АВСЕНКМОРТХ", "ABCEHKMOPTX")
_POINTS_RE = re.compile(
    r"(?<![\wА-Яа-яЁё\\{$])(?P<name>[A-ZАВСЕНКМОРТХ]{2,10}(?:_\{?\d\}?)?)(?![\wА-Яа-яЁё}$])")


def _prose(value: str, fix) -> str:
    out, pos = [], 0
    for match in MATH_RE.finditer(value):
        out.append(fix(value[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(fix(value[pos:]))
    return "".join(out)


# Латинские двойники внутри русского слова: «ребpa», «paвен», «coomветственно»
# (курсивное «т» OCR читает как «m», «и» — как «u»).
_CYRILLIC_TWINS = str.maketrans("acekmnopuxyABCEHKMOPTX", "асектпорихуАВСЕНКМОРТХ")
_MIXED_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")


def cyrillic_words(value: str) -> str:
    def fix(chunk: str) -> str:
        def word(match: re.Match) -> str:
            token = match.group(0)
            latin = re.findall(r"[A-Za-z]", token)
            if not latin or len(re.findall(r"[А-Яа-яЁё]", token)) < 2:
                return token
            if any(ch not in "acekmnopuxyABCEHKMOPTX" for ch in latin):
                return token
            return token.translate(_CYRILLIC_TWINS)
        return _MIXED_WORD_RE.sub(word, chunk)
    return _prose(value or "", fix)


def point_names(value: str) -> str:
    def fix(chunk: str) -> str:
        def wrap(match: re.Match) -> str:
            name = match.group("name")
            letters = re.sub(r"_.*", "", name)
            # Заглавное русское слово без латиницы — не обозначение.
            if not re.search("[A-Z]", letters) and len(letters) < 2:
                return name
            return "\\(" + name.translate(_LOOKALIKES) + "\\)"
        return _POINTS_RE.sub(wrap, chunk)
    return _prose(value or "", fix)


def degrees(value: str) -> str:
    """«30°» в тексте — формула \\(30^{\\circ}\\), «60°» в формуле — 60^{\\circ}."""
    out, pos = [], 0
    for match in MATH_RE.finditer(value):
        out.append(re.sub(r"(?<![\w{^])(\d+(?:,\d+)?)\s*°",
                          lambda m: "\\(" + m.group(1) + "^{\\circ}\\)", value[pos:match.start()]))
        out.append(re.sub(r"\s*°", lambda m: "^{\\circ}", match.group(0)))
        pos = match.end()
    out.append(re.sub(r"(?<![\w{^])(\d+(?:,\d+)?)\s*°",
                      lambda m: "\\(" + m.group(1) + "^{\\circ}\\)", value[pos:]))
    return "".join(out)


# Инициалы и сокращения («Л.М. Атанасян», «М.: Просвещение») — не точки.
_SINGLE_TWIN_RE = re.compile(r"(?<![\wА-Яа-яЁё\\{$.])([ЕНМРТХ])(?![\wА-Яа-яЁё}$.])")


def tidy(value: str) -> str:
    """Пробел перед знаком препинания после формулы: «равны $2$ , найдите»."""
    value = re.sub(r"(?<=\$|\))[ \t]+(?=[,.;:](?:\s|$))", "", value or "")
    # «(МИОО, $2010$)» — год в пометке источника — текст.
    value = re.sub(r"\(([^()$]*?),\s*\$(\d{4})\$\)", r"(\1, \2)", value)
    value = re.sub(r"\s*\\quad\s*\\\)", r"\\)", value)
    # Пустая формула «у \(\) которого» и перенос «\\» посреди фразы перед
    # формулой (стык колонок): «треугольника\\ \(A B C\)».
    value = re.sub(r"\s*\\\(\s*\\\)", "", value)
    value = re.sub(r"(?<=[а-яё,])[ \t]*\\\\[ \t]*\n[ \t]*(?=\\\(|[а-яё])", " ", value)
    # «co стороной» — предлог латиницей.
    value = _prose(value, lambda chunk: re.sub(r"(?<![A-Za-zА-Яа-яЁё])co(?= [а-яё])", "со", chunk))
    # Перевод строки посреди фразы (стык колонок): «при ребре\n\(B C\)».
    value = re.sub(r"(?<=[а-яё,])[ \t]*\n(?=[ \t]*(?:[а-яё]|\\\())", " ", value)
    value = re.sub(r"(?<=\\\))[ \t]*\n(?=[ \t]*[а-яё])", " ", value)
    # «(МИОО, 2010). в правильной» — заглавная после пометки источника.
    value = re.sub(r"(\((?:МИОО|ЕГЭ|Репетиционный ЕГЭ|аналог ЕГЭ)[^()]*\)\.\s+)([а-яё])",
                   lambda m: m.group(1) + m.group(2).upper(), value)
    # «\(\varphi-\) искомый угол» — тире OCR унёс в формулу как минус.
    value = re.sub(r"\s*-\\\)\s+(?=[а-яё])", r"\\) — ", value)
    # Дефис составного слова, потерянный на переносе.
    for word in ("поэтапно", "координатно"):
        value = re.sub(word + r"(?=вычислительн|векторн)", word + "-", value)
    # «\(A C=B D=14, \quad B C=A D=13, \quad A B=C D=15\)» — перечень
    # равенств одной строчной формулой не переносится в листке A5: по формуле на равенство.
    def split_list(match: re.Match) -> str:
        parts = re.split(r",\s*\\quad\s*", match.group(1))
        if len(parts) < 2 or not all("=" in part for part in parts) or re.search(r"\\left|\\begin", match.group(1)):
            return match.group(0)
        return ", ".join(f"\\({part.strip()}\\)" for part in parts)
    value = re.sub(r"\\\(((?:(?!\\\)).)*?,\s*\\quad(?:(?!\\\)).)*?)\\\)", split_list, value)
    # «1-й способ», «2-го» — порядковое числительное, не формула.
    value = re.sub(r"\$(\d)\$-(?=[а-я])", r"\1-", value)
    # «точки \(P\), М и \(K\)», «середину Е ребра» — точка кириллицей;
    # «равно а.» — длина ребра кириллической «а».
    value = _prose(value, lambda chunk: _SINGLE_TWIN_RE.sub(
        lambda m: "\\(" + m.group(1).translate(_LOOKALIKES) + "\\)", chunk))
    value = _prose(value, lambda chunk: re.sub(
        r"(?<=равн[оаы] )а(?=[.,;]|\s+(?:и|см)\b|$)|(?<=[а-яё] )а(?=[.,;](?:\s|$))",
        lambda m: "\\(a\\)", chunk))
    # «т.e.», «Ee высота» — латиница OCR в коротких словах.
    value = _prose(value, lambda chunk: re.sub(r"т\.e\.", "т.е.", re.sub(r"(?<![A-Za-z])Ee(?= [а-яё])", "Ее", chunk)))
    value = _prose(value, lambda chunk: re.sub(r"(?<=, )to(?= [а-яё])", "то", chunk))
    # «\\» в конце абзаца после формулы или слова с точкой — лишний.
    value = re.sub(r"(?<=\\\)\.)[ \t]*\\\\[ \t]*(?=\n)", "", value)
    # «на рисунке .» — номер рисунка ушёл, пробел перед точкой остался.
    value = _prose(value, lambda chunk: re.sub(r"(?<=[а-яё])[ \t]+(?=[.,;:](?:\s|$))", "", chunk))
    value = _prose(value, lambda chunk: re.sub(r"(?<![\w\\{$])Oxyz(?![\w}])", lambda m: "\\(Oxyz\\)", chunk))
    # Единица, оставшаяся в формуле с \text или в выносной: «432 см^{2}».
    def unit(match: re.Match) -> str:
        # \text{…} внутри формулы не трогаем: там единица уже текстом.
        parts = re.split(r"(\\(?:text|mathrm)\s*\{[^{}]*\})", match.group(0))
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r"(?<![\\A-Za-zА-Яа-яЁё{])\s*см(?![А-Яа-яЁё])",
                              lambda u: "\\text{ см}", parts[i])
        return "".join(parts)
    return MATH_RE.sub(unit, value)


# --------------------------------------------------------------------------
# Разбор целиком
# --------------------------------------------------------------------------

def _apply_override(task: TaskDraft, override: dict) -> None:
    if "text" in override:
        task.text_latex = override["text"]
    if "answer" in override:
        task.author_answer_latex = override["answer"]
    if "solution" in override:
        task.author_solution_latex = override["solution"]


FIX_FIELDS = {"text": "text_latex", "answer": "author_answer_latex",
              "solution": "author_solution_latex"}


def apply_fixes(task: TaskDraft, fixes: list[dict], diagnostics: dict) -> None:
    """Сверенные с PDF правки готового текста. Если общее правило уже
    сделало то же самое (``old`` нет, ``new`` есть), правка пропускается."""
    for fix in fixes:
        if fix["task"] != task.external_id:
            continue
        attr = FIX_FIELDS[fix["field"]]
        value = getattr(task, attr)
        count = value.count(fix["old"])
        if count == 1:
            setattr(task, attr, value.replace(fix["old"], fix["new"], 1))
            diagnostics["fixes_applied"].append(fix["id"])
        elif count == 0 and fix["new"] and fix["new"] in value:
            diagnostics["fixes_skipped"].append(fix["id"])
        else:
            diagnostics["fixes_failed"].append(f"{fix['id']}: «было» встречается {count} раз")


def _paragraph_path(structure: dict, paragraph: dict, kind: str) -> list[str]:
    chapter = next(c for c in structure["chapters"] if c["number"] == paragraph["chapter"])
    return [chapter["title"], paragraph["title"], kind]


def _distribute_subitem_answer(task: TaskDraft) -> bool:
    """Ответ «а) 4; б) …; в) …» — по пунктам с теми же метками."""
    if not task.subitems or not task.author_answer_latex:
        return False
    parts = re.split(r"(?:^|(?<=[;.]))\s*([а-з])\)\s*", task.author_answer_latex)
    labels = parts[1::2]
    values = [re.sub(r"\s*[;.]\s*$", "", v).strip() for v in parts[2::2]]
    own = [re.sub(r"\W", "", item.label) for item in task.subitems]
    if parts[0].strip() or labels != own:
        return False
    for item, value in zip(task.subitems, values):
        item.author_answer_latex = value
    task.author_answer_latex = ""
    return True


def parse_koryanov(text: str, *, structure: dict | None = None,
                   repairs_path: Path = REPAIRS_PATH) -> tuple[list[TaskDraft], dict]:
    structure = structure or load_structure()
    text = text.replace("\r\n", "\n")
    if "типы задач и методы их решения" not in text or "Многогранники" not in text:
        raise ValueError("Не найдено пособие Прокофьева и Корянова «Многогранники»")
    text, repairs, patches = load_repairs(text, repairs_path)
    text = prepare_text(text)
    text, figures = extract_figures(text, repairs["figures"])
    diagnostics: dict = {
        "source_repairs_applied": patches,
        "overrides_applied": [],
        "count_mismatch": [],
        "missing_answers": [],
        "missing_solutions": [],
        "dropped_tails": {},
        "answer_stream_problems": [],
        "figures_missing_by_task": {},
        "figures_unreferenced": [],
        "figures_positional": {},
        "extra_solutions": [],
        "fixes_applied": [],
        "fixes_skipped": [],
        "fixes_failed": [],
        "methods": {},
    }
    start = text.find(structure["body_start"])
    stop = text.find(structure["body_end"])
    answers_at = text.find(structure["answers_start"])
    answers_end = text.find(structure["answers_end"])
    if min(start, stop, answers_at, answers_end) < 0:
        raise ValueError("Не найдены границы глав или раздела ответов")
    marks = structure_marks(text, structure, start, stop)
    marks.append(Mark(stop, stop, "other", "end"))
    method_codes = {m["title"]: m["method"] for m in structure["methods"]}

    tasks: list[TaskDraft] = []
    paragraph: dict | None = None
    method = ""
    example_numbers: list[int] = []
    exercise_numbers: list[int] = []
    example_paragraph: dict[int, str] = {}
    example_ranges: dict[str, tuple[int, int]] = {}
    for index, mark in enumerate(marks):
        if mark.kind == "paragraph":
            paragraph, method = mark.paragraph, ""
            continue
        if mark.kind == "method":
            method = mark.title
            continue
        nxt = marks[index + 1].pos if index + 1 < len(marks) else stop
        if mark.kind == "example":
            key = f"П{mark.number}"
            body = text[mark.end:nxt]
            stop_at = structure.get("example_stops", {}).get(key)
            if stop_at:
                cut = body.find(stop_at)
                if cut < 0:
                    diagnostics["count_mismatch"].append(f"{key}: нет конца разбора «{stop_at}»")
                else:
                    nxt = mark.end + cut
                    diagnostics["dropped_tails"][key] = re.sub(r"\s+", " ", body[cut:].strip())[:120]
                    body = body[:cut]
            parts = split_example(body)
            path = _paragraph_path(structure, paragraph, structure["examples_title"])
            task = task_from_block(Marker(0, 0, key), clean(parts.stem.strip()), path)
            task.author_solution_latex = _clean_solution(parts.solution)
            task.author_answer_latex = _example_answer(parts.answer)
            task.topic_code = paragraph["topic"]
            task.topic_original = paragraph["title"]
            kept = (mark.end, nxt - len(parts.dropped))
            example_ranges[key] = kept
            if parts.dropped.strip():
                diagnostics["dropped_tails"][key] = re.sub(r"\s+", " ", parts.dropped.strip())[:120]
            if method:
                diagnostics["methods"][key] = [method, method_codes.get(method, "")]
            example_numbers.append(mark.number)
            example_paragraph[mark.number] = paragraph["key"]
            tasks.append(task)
        elif mark.kind == "exercises":
            chapter = next(c for c in structure["chapters"] if c["number"] == paragraph["chapter"])
            for number, body in exercise_items(text[mark.end:nxt]):
                if "exercises" in paragraph and paragraph["exercises"][0] <= number <= paragraph["exercises"][1]:
                    path = _paragraph_path(structure, paragraph, structure["exercises_title"])
                    topic, title = paragraph["topic"], paragraph["title"]
                elif "exercises" in chapter and chapter["exercises"][0] <= number <= chapter["exercises"][1]:
                    path = [chapter["title"], structure["exercises_title"]]
                    topic, title = "", chapter["title"]
                else:
                    diagnostics["count_mismatch"].append(f"упражнение {number} вне ожидаемых границ ({paragraph['key']})")
                    continue
                task = task_from_block(Marker(0, 0, str(number)), clean(body), path)
                task.topic_code = topic
                task.topic_original = title
                exercise_numbers.append(number)
                tasks.append(task)

    by_id = {task.external_id: task for task in tasks}
    for extra in structure.get("extra_solutions", []):
        at = text.find(extra["anchor"], start, stop)
        task = by_id.get(extra["task"])
        if at < 0 or task is None:
            diagnostics["count_mismatch"].append(f"нет дополнительного решения {extra['task']}")
            continue
        after = next(m.pos for m in marks if m.pos > at)
        parts = split_example(text[at + len(extra["anchor"]):after])
        own = re.sub(r"^\s*(?:\\\\\s*)?", "", parts.solution)
        block = f"{extra['title']} {_clean_solution(own)}"
        task.author_solution_latex = task.author_solution_latex.rstrip() + "\n\n" + block
        example_ranges[extra["task"] + "+"] = (at, after)
        diagnostics["extra_solutions"].append(extra["task"])

    if example_numbers != list(range(1, structure["examples_total"] + 1)):
        diagnostics["count_mismatch"].append(f"примеры: {example_numbers}")
    if exercise_numbers != list(range(1, structure["exercises_total"] + 1)):
        diagnostics["count_mismatch"].append(f"упражнения: {exercise_numbers}")
    for paragraph_spec in structure["paragraphs"]:
        if "examples" not in paragraph_spec:
            continue
        first, last = paragraph_spec["examples"]
        found = [n for n, key in example_paragraph.items() if key == paragraph_spec["key"]]
        if sorted(found) != list(range(first, last + 1)):
            diagnostics["count_mismatch"].append(
                f"{paragraph_spec['key']}: примеры {sorted(found)}, ожидалось {first}–{last}")

    answers, problems = answer_stream(text[answers_at + len(structure["answers_start"]):answers_end],
                                      structure["exercises_total"])
    diagnostics["answer_stream_problems"] = problems

    used: set[str] = set()
    for task in tasks:
        if not task.external_id.startswith("П"):
            raw = answers.get(int(task.external_id), "")
            task.author_answer_latex, hint = answer_latex(raw) if raw else ("", "")
            if hint:
                task.author_solution_latex = hint
        if task.external_id in repairs["tasks"]:
            _apply_override(task, repairs["tasks"][task.external_id])
            diagnostics["overrides_applied"].append(task.external_id)
        for item in task.subitems:
            item.label = item.label.translate(_LATIN_LABELS)
        task.author_answer_latex = _LABEL_RE.sub(
            lambda m: m.group(1).translate(_LATIN_LABELS) + ")", task.author_answer_latex)
        _distribute_subitem_answer(task)
        missing = attach_figures(task, figures, used)
        if missing:
            diagnostics["figures_missing_by_task"][task.external_id] = missing
        positional = _attach_positional_figures(task, figures, used, example_ranges)
        if positional:
            diagnostics["figures_positional"][task.external_id] = positional
        task.text_latex = tidy(canon_field(point_names(cyrillic_words(task.text_latex))))
        task.author_solution_latex = tidy(canon_field(point_names(cyrillic_words(task.author_solution_latex))))
        task.author_answer_latex = tidy(canon_field(task.author_answer_latex))
        for item in task.subitems:
            item.text_latex = tidy(canon_field(point_names(cyrillic_words(item.text_latex))))
            item.author_answer_latex = tidy(canon_field(item.author_answer_latex))
            item.author_solution_latex = tidy(canon_field(point_names(item.author_solution_latex)))
        task.topic_code = structure.get("topics", {}).get(task.external_id, task.topic_code)
        task.collection_title = task.source_path[-1]
        task.grade_band_codes = list(structure["grade_bands"])
        has_answer = task.author_answer_latex or any(i.author_answer_latex for i in task.subitems)
        if not has_answer:
            diagnostics["missing_answers"].append(task.external_id)
        if task.external_id.startswith("П") and not task.author_solution_latex:
            diagnostics["missing_solutions"].append(task.external_id)
        finalize_draft_images(task)
        # Правки готового текста — последними, по тому, что видит редактор
        # (\taskpic{N} уже пронумерованы).
        apply_fixes(task, repairs["fixes"], diagnostics)
    body_numbers = {n for n, pos in figures.position.items() if start <= pos < stop}
    diagnostics["figures_unreferenced"] = sorted(
        (n for n in body_numbers if re.match(r"\d+", n).group(0) not in used),
        key=lambda n: (int(re.match(r"\d+", n).group(0)), n))
    diagnostics["figures_total"] = len(figures.by_number)
    diagnostics["unique_tasks"] = len({t.external_id for t in tasks})
    diagnostics["task_marker_occurrences"] = len(tasks)
    diagnostics["duplicate_task_ids"] = [
        key for key, count in Counter(t.external_id for t in tasks).items() if count > 1]
    diagnostics["tasks_by_section"] = dict(Counter(" / ".join(t.source_path) for t in tasks))
    return tasks, diagnostics

"""Профиль открытого банка ОГЭ (сборник Остромогильского / ФИПИ).

Условия режет из OCR-TeX по маркерам «Задача N.P» / «Аналог N.P.A».
Авторские ответы сливает из интерактивного PDF по якорям ``ans::``.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .textbook_parser import (
    TASK_IMAGE_RE, TaskDraft, apply_imported_answer, finalize_draft_images,
    normalize_imported_text)


EXAM_TITLES = {
    1: 'Практические задачи',
    2: 'Практические задачи',
    3: 'Практические задачи',
    4: 'Практические задачи',
    5: 'Практические задачи',
    6: 'Дроби',
    7: 'Координатная прямая',
    8: 'Степени и корни',
    9: 'Уравнения',
    10: 'Вероятности',
    11: 'Графики функций',
    12: 'Расчёты по формулам',
    13: 'Неравенства',
    14: 'Прогрессии',
    15: 'Треугольники',
    16: 'Окружности',
    17: 'Четырёхугольники',
    18: 'Задачи на клетчатой бумаге',
    19: 'Геометрические высказывания',
    20: 'Алгебраические задачи',
    21: 'Текстовые задачи',
    22: 'Построение графиков',
    23: 'Геометрические вычисления',
    24: 'Геометрические доказательства',
    25: 'Сложная геометрия',
}

EXAM_TOPIC_CODES = {
    1: 'ARI.06', 2: 'ARI.06', 3: 'ARI.06', 4: 'ARI.06', 5: 'ARI.06',
    6: 'ARI.03',
    7: 'ARI.03.07',
    8: 'ARI.05',
    9: 'ALG.03',
    10: 'STA.03',
    11: 'ALG.05',
    12: 'ARI.06',
    13: 'ALG.04',
    14: 'ALG.06',
    15: 'GEO.02',
    16: 'GEO.04',
    17: 'GEO.03',
    18: 'GEO.06',
    19: 'GEO.01',
    20: 'ALG.03',
    21: 'ALG.09',
    22: 'ALG.05.03',
    23: 'GEO.02',
    24: 'GEO.02',
    25: 'GEO.02',
}

OGE_TOPIC_ALIASES = {
    'практические задачи': 'ARI.06',
    'маршруты': 'ARI.06',
    'шины': 'ARI.06',
    'участки': 'ARI.06',
    'листы': 'ARI.06',
    'печки': 'ARI.06',
    'квартиры': 'ARI.06',
    'тарифы': 'ARI.06',
    'дроби': 'ARI.03',
    'десятичные дроби': 'ARI.03.05',
    'обыкновенные дроби': 'ARI.03.04',
    'координатная прямая': 'ARI.03.07',
    'степени и корни': 'ARI.05',
    'уравнения': 'ALG.03',
    'вероятности': 'STA.03',
    'графики функций': 'ALG.05',
    'расчеты по формулам': 'ARI.06',
    'расчёты по формулам': 'ARI.06',
    'неравенства': 'ALG.04',
    'прогрессии': 'ALG.06',
    'треугольники': 'GEO.02',
    'окружности': 'GEO.04',
    'окружность': 'GEO.04',
    'четырехугольники': 'GEO.03',
    'четырёхугольники': 'GEO.03',
    'задачи на клетчатой бумаге': 'GEO.06',
    'клетчатая бумага': 'GEO.06',
    'геометрические высказывания': 'GEO.01',
    'алгебраические задачи': 'ALG.03',
    'текстовые задачи': 'ALG.09',
    'построение графиков': 'ALG.05.03',
    'геометрические вычисления': 'GEO.02',
    'геометрические доказательства': 'GEO.02',
    'сложная геометрия': 'GEO.02',
    'геометрические задачи повышенной сложности': 'GEO.02',
    'окружность, круг и их элементы': 'GEO.04',
    'треугольники и их элементы': 'GEO.02',
    'выражения, уравнения и неравенства': 'ALG.03',
    'геометрические задачи на вычисление': 'GEO.02',
    'построение графиков функций': 'ALG.05.03',
    'геометрические задачи на доказательство': 'GEO.02',
    'анализ геометрических высказываний': 'GEO.01',
}

NAV_RE = re.compile(
    r'(?:\\begin\{center\}\s*)?\\begin\{tabular\}'
    r'(?:\[[^\]]*\])?\{[^}]*\}\s*\\hline\s*'
    r'Оглавление\b[\s\S]*?\\end\{tabular\}\s*(?:\\end\{center\})?',
    re.I)
BLANK_ANSWER_TABLE_RE = re.compile(
    r'(?:\\begin\{(?:center|table)\}(?:\[[^\]]*\])?\s*)*'
    r'\\begin\{tabular\}'
    r'(?:\[[^\]]*\])?\{[^}]*\}\s*'
    r'(?:\\hline\s*)?'
    r'(?:Ответ:\s*)?(?:&\s*|\\\\\s*|\\hline\s*|\$\\hline\$\s*)*'
    r'\\end\{tabular\}'
    r'(?:\s*\\end\{(?:center|table)\})*',
    re.I)
ESCAPED_TABULAR_RE = re.compile(
    r'\\textbackslash\s+begin\\?\{tabular\\?\}[\s\S]*?'
    r'\\textbackslash\s+end\\?\{tabular\\?\}',
    re.I)
ANSWER_SECTION_RE = re.compile(r'\\section\*\{Ответ:[^}]*\}')
EMPTY_ITEMIZE_RE = re.compile(
    r'\\begin\{itemize\}\s*(?:\\item\s*)*\\end\{itemize\}', re.I)
NAV_BUTTON_LINE_RE = re.compile(
    r'(?m)^\s*(?:Прототип|Аналоги|Аналог(?!\s+\d)|Ответ:?)\s*(?:\\\\)?\s*$')
INLINE_NAV_WORD_RE = re.compile(
    r'(?<![А-Яа-яA-Za-z])(?:Прототип|Аналоги)(?:\\\\)?(?![А-Яа-яA-Za-z])')
ANSWER_BLANK_LINE_RE = re.compile(
    r'(?m)^\s*Ответ:(?!\s*дайте).*$')
OCR_FOOTER_TAIL_RE = re.compile(
    r'(?s)(?:\\\\)?\s*'
    r'(?:Оглавление\b|Справочный материал\b|'
    r'\\section\*\{-?\s*№|'
    r'\$?\\textbackslash|'
    r'\$\\(?:ggg|gg|lll|ll)\$).*$')
NAV_GLYPH_LINE_RE = re.compile(
    r'(?m)^\s*(?:(?:[<>|])+\s*|\$\\(?:ggg|gg|lll|ll)\$\s*|'
    r'\\textbackslash\s+\S+\s*|□+\s*)+(?:\\\\)?\s*$')
SECTION_CMD_RE = re.compile(r'\\(?:sub)*section\*?\{[^{}]*\}(?:\\\\)?')
BOX_LINE_RE = re.compile(r'(?m)^\s*[□]+\s*(?:\\\\)?\s*$')
OCR_IMAGE_SIZE_RE = re.compile(
    r'(?:^|/)[^/]*-(?P<page>\d+)_(?P<h>\d+)_(?P<w>\d+)_\d+_(?P<x>\d+)$')
GRID_FIGURE_EXAM = 18
GRID_FIGURE_MISSING = 'Нет рисунка с клетчатой бумагой'
TASK_START_RE = re.compile(
    r'(?m)^(?:\\section\*\{)?(?P<kind>Задача|Аналог)\s+'
    r'(?P<id>\d+\.\d+(?:\.\d+)?)')
SHARED_RE = re.compile(
    r'(?m)^(?:\\section\*\{)?Текст к задачам\s+'
    r'(?P<a>\d+\.\d+(?:\.\d+)?)'
    r'\s*[-–—-]\s*'
    r'(?P<b>\d+\.\d+(?:\.\d+)?)')
EXAM_HEADING_RE = re.compile(
    r'(?m)^(?:\\section\*\{)?-?\s*№\s*(?P<n>\d+)\.\s*(?P<title>[^\n}\\]+)')
MAJOR_RE = re.compile(
    r'(?m)^\\section\*\{(?P<title>'
    r'ПРАКТИЧЕСКИЕ ЗАДАЧИ|АЛГЕБРА|ГЕОМЕТРИЯ|'
    r'ЗАДАЧИ С РАЗВЁРНУТЫМ ОТВЕТОМ|АНАЛОГИ|'
    r'СПРАВОЧНЫЙ МАТЕРИАЛ)\}')
PRACTICAL_CLUSTER_RE = re.compile(
    r'(?m)^(?:\\section\*\{)?(?:№\s*1\s*[-–—]\s*№\s*5\.\s*)?'
    r'(?P<title>Маршруты|Шины|ШІины|Участки|Листы|Печки|Квартиры|Тарифы)'
    r'\.?\}?\s*$')
ANSWER_KEY_START_RE = re.compile(r'№\s*1\.1\s*&')
TAG_RE = re.compile(r'\b(DEMO|OLD|NEW|SIM)\b')
TRAILING_NOISE_RE = re.compile(
    r'(?m)^\s*(?:Ответ:?|Аналоги|Прототип|\\section\*\{Ответ:[^}]*\})\s*(?:\\\\)?\s*$')
PAGE_JUNK_RE = re.compile(
    r'(?:\$\\ggg\$|\$2 \\gg\$|\\\\sum_\{i=1\}\^\{\\\\infty\}.*Start|'
    r'Библиотека MathStart|Группа MathStart.*)', re.I)
ANSWER_KEY_LINE_RE = re.compile(
    r'№\s*(?P<id>\d+(?:\.\d+){1,2})\s*\n(?P<val>[^\n]+)')
LOCATOR_RE = re.compile(r'^\d+\.\d+(?:\.\d+)?$')


def exam_number(locator: str) -> int:
    return int(locator.split('.', 1)[0])


def is_analog_id(locator: str) -> bool:
    return locator.count('.') >= 2


def exam_item_code(locator: str) -> str:
    return f'OGE_2026_{exam_number(locator):02d}'


def expand_shared_ids(start_id: str, end_id: str) -> list[str]:
    start_parts = start_id.split('.')
    end_parts = end_id.split('.')
    if start_parts[1:] != end_parts[1:]:
        return [start_id, end_id]
    first, last = int(start_parts[0]), int(end_parts[0])
    rest = start_parts[1:]
    return ['.'.join([str(n), *rest]) for n in range(first, last + 1)]


def strip_oge_noise(text: str) -> str:
    """Убирает колонтитулы OCR, пустые бланки ответа и мусор навигации."""
    text = NAV_RE.sub('\n', text)
    text = BLANK_ANSWER_TABLE_RE.sub('\n', text)
    text = ESCAPED_TABULAR_RE.sub('\n', text)
    text = EMPTY_ITEMIZE_RE.sub('\n', text)
    text = ANSWER_SECTION_RE.sub('\n', text)
    text = PAGE_JUNK_RE.sub('', text)
    return text


def is_answer_blank_image(path: str) -> bool:
    """Узнаёт типовой бланк справа по размерам и позиции в этом OCR.

    Одна лишь малая высота опасна: так выглядят координатные прямые.
    Неизвестные размеры сохраняем для последующей сверки с источником.
    """
    stem = Path(str(path or '').replace('\\', '/')).stem
    match = OCR_IMAGE_SIZE_RE.search(stem)
    if not match:
        return False
    height = int(match.group('h'))
    width = int(match.group('w'))
    left = int(match.group('x'))
    return 60 <= height <= 90 and 580 <= width <= 610 and 1200 <= left <= 1250


def drop_junk_graphics(text: str) -> str:
    """Выкидывает includegraphics бланков ответа и пустые \\taskpic."""

    def replace(match: re.Match) -> str:
        if is_answer_blank_image(match.group('path')):
            return ''
        return match.group(0)

    return TASK_IMAGE_RE.sub(replace, text or '')


def select_figure_span(
        bands: list[tuple[int, int]], height: int) -> tuple[int, int] | None:
    """Оставляет сетку и буквы вершин, без кнопок и таблицы «Ответ»."""
    del height
    rest = [(start, end) for start, end in bands if start > 100]
    if not rest:
        return None
    main = max(rest, key=lambda item: item[1] - item[0])
    top, bot = main
    for start, end in rest:
        band_h = end - start
        if end <= top and top - end <= 40:
            top = min(top, start)
        elif start >= bot and start - bot <= 40 and band_h <= 30:
            bot = max(bot, end)
    return top, bot


def _ink_row_bands(pix, threshold: int = 90) -> list[tuple[int, int]]:
    width, height = pix.width, pix.height
    samples = pix.samples
    channels = pix.n
    bands: list[tuple[int, int]] = []
    start = None
    limit = threshold * 3
    for y in range(height):
        ink = False
        offset = y * width * channels
        for x in range(width):
            index = offset + x * channels
            if samples[index] + samples[index + 1] + samples[index + 2] < limit:
                ink = True
                break
        if ink and start is None:
            start = y
        elif not ink and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, height))
    return bands


def _ink_col_span(pix, top: int, bot: int, threshold: int = 90) -> tuple[int, int]:
    width = pix.width
    samples = pix.samples
    channels = pix.n
    limit = threshold * 3
    left = width
    right = 0
    for y in range(top, bot):
        offset = y * width * channels
        for x in range(width):
            index = offset + x * channels
            if samples[index] + samples[index + 1] + samples[index + 2] < limit:
                if x < left:
                    left = x
                if x > right:
                    right = x
    if left > right:
        return 0, width
    return left, right + 1


def extract_grid_figures(pdf_path: Path) -> dict[str, bytes]:
    """Вырезает векторные рисунки №18 из интерактивного PDF."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            'Для рисунков №18 нужен PyMuPDF (pip install pymupdf).'
        ) from exc
    doc = fitz.open(pdf_path)
    figures: dict[str, bytes] = {}
    try:
        dests = doc.resolve_names()
        page_h = float(doc[0].rect.height)
        by_page: dict[int, list[tuple[str, float]]] = {}
        for key, info in dests.items():
            if not key.startswith('task::18.') or not isinstance(info, dict):
                continue
            locator = key[6:]
            if not LOCATOR_RE.fullmatch(locator) or locator.startswith('0.'):
                continue
            top = page_h - float(info['to'][1])
            by_page.setdefault(info['page'], []).append((locator, top))
        for page_no, items in by_page.items():
            items.sort(key=lambda item: item[1])
            page = doc[page_no]
            for index, (locator, top) in enumerate(items):
                y0 = max(40.0, top - 4)
                y1 = (items[index + 1][1] - 4 if index + 1 < len(items)
                      else min(page_h - 60, y0 + 250))
                y1 = min(y1, y0 + 250)
                clip = fitz.Rect(368, y0, 555, y1)
                if clip.height < 20 or clip.width < 20:
                    continue
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(2.5, 2.5), clip=clip, alpha=False)
                bands = _ink_row_bands(pix)
                span = select_figure_span(bands, pix.height)
                if span is None:
                    continue
                top_px, bot_px = span
                left, right = _ink_col_span(pix, top_px, bot_px)
                pad = 14
                box = fitz.Rect(
                    clip.x0 + max(0, left - pad) / 2.5,
                    clip.y0 + max(0, top_px - pad) / 2.5,
                    clip.x0 + min(pix.width, right + pad) / 2.5,
                    clip.y0 + min(pix.height, bot_px + pad) / 2.5,
                )
                if box.width < 24 or box.height < 24:
                    continue
                tight = page.get_pixmap(
                    matrix=fitz.Matrix(2, 2), clip=box, alpha=False)
                figures[locator] = tight.tobytes('png')
    finally:
        doc.close()
    return figures


def grid_figure_stem(locator: str) -> str:
    return 'oge-' + locator.replace('.', '-')


def attach_grid_figures(
        tasks: list[TaskDraft], figures: dict[str, bytes],
        dest: Path | None = None) -> dict[str, str]:
    """Меняет OCR-кадры №18 на вырезанные из PDF сетки."""
    written: dict[str, str] = {}
    if dest is not None:
        dest.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        if exam_number(task.external_id) != GRID_FIGURE_EXAM:
            continue
        data = figures.get(task.external_id)
        if not data:
            if GRID_FIGURE_MISSING not in task.warnings:
                task.warnings.append(GRID_FIGURE_MISSING)
            task.confidence = min(task.confidence, 0.7)
            continue
        stem = grid_figure_stem(task.external_id)
        if dest is not None:
            (dest / f'{stem}.png').write_bytes(data)
        body = TASK_IMAGE_RE.sub('', task.text_latex)
        body = re.sub(r'(?:\\\\\s*)+$', '', body).strip()
        body = f'{body}\n\\includegraphics{{{stem}}}'.strip()
        task.text_latex = body
        task.images = []
        finalize_draft_images(task)
        written[task.external_id] = stem
    return written


def clip_oge_body(text: str) -> str:
    """Оставляет задачи: от практических до ключа / справочника."""
    start = re.search(r'\\section\*\{ПРАКТИЧЕСКИЕ ЗАДАЧИ\}', text)
    body = text[start.start():] if start else text
    key = ANSWER_KEY_START_RE.search(body)
    if key:
        body = body[:key.start()]
    sprav = re.search(r'\\section\*\{СПРАВОЧНЫЙ МАТЕРИАЛ\}', body)
    if sprav:
        body = body[:sprav.start()]
    return body


def parse_answer_key_text(text: str) -> dict[str, str]:
    """Разбирает плотный ключ ``№6.1\\n15,3.`` со страниц PDF."""
    answers = {}
    for match in ANSWER_KEY_LINE_RE.finditer(text):
        locator = match.group('id')
        if LOCATOR_RE.fullmatch(locator) and not locator.startswith('0.'):
            answers[locator] = match.group('val').strip()
    return answers


def parse_tex_formula_answers(text: str, allowed_ids) -> dict[str, str]:
    """Читает целые дроби и корни из OCR-таблицы печатного ключа.

    PDF подтверждает номера ответов, но его линейный текст теряет двумерную
    запись формул. Остальные ответы остаются из PDF; неизвестные команды
    и незакрытые формулы не подменяют его результат.
    """
    start = ANSWER_KEY_START_RE.search(text)
    if not start:
        return {}
    key = text[start.start():]
    # OCR оборачивает некоторые номера в отдельную одноколоночную таблицу.
    key = re.sub(
        r'\\begin\{tabular\}(?:\[[^]]*\])?\{[lcr]\}'
        r'((?:(?!\\begin\{tabular\}).)*?)\\end\{tabular\}',
        lambda match: match.group(1).replace(r'\\', ' ').replace('□', ' '),
        key, flags=re.DOTALL)
    allowed_ids = set(allowed_ids)
    result = {}
    for match in re.finditer(r'№\s*(\d+\.\d+(?:\.\d+)?)(?![.\d])(?=\s|&)', key):
        locator = match.group(1)
        if locator not in allowed_ids:
            continue
        tail = key[match.end():].split(r'\\', 1)[0].split('№', 1)[0]
        cells = [cell.strip() for cell in tail.split('&') if cell.strip()]
        if not cells:
            continue
        value = re.sub(r'^\\multicolumn\{\d+\}\{[^}]+\}\{(.*)\}$',
                       r'\1', cells[0], flags=re.DOTALL)
        if not re.search(r'\\(?:frac|sqrt)\b', value):
            continue
        commands = set(re.findall(r'\\([A-Za-z]+)', value))
        if commands - {'frac', 'sqrt', 'left', 'right', 'displaystyle', 'infty', 'cup'}:
            continue
        depth = 0
        valid = True
        for char in value:
            depth += (char == '{') - (char == '}')
            if depth < 0:
                valid = False
        if not valid or depth or value.count('$') % 2:
            continue
        if locator in result and result[locator] != normalize_oge_answer(value):
            # Два разных значения одного номера требуют ручной сверки.
            result[locator] = ''
        elif locator not in result:
            result[locator] = normalize_oge_answer(value)
    return {key: value for key, value in result.items() if value}


def normalize_oge_answer(raw: str) -> str:
    """Готовит строку ключа к ``author_answer_latex``."""
    value = (raw or '').strip().replace('−', '-').replace('–', '-')
    value = re.sub(r'\s+', ' ', value)
    if value.endswith('.') and not value.endswith('...'):
        value = value[:-1].rstrip()
    multi = re.fullmatch(r'<\s*([0-9 ]+)\s*>', value)
    if multi:
        value = multi.group(1).replace(' ', '')
    if re.fullmatch(r'-?\d{1,3}(?: \d{3})+(?:[.,]\d+)?', value):
        value = value.replace(' ', '')
    # В PDF фигурные скобки — печатные символы множества. В TeX они
    # служебные; аргументы уже имеющихся команд менять нельзя.
    if '\\' not in value:
        value = re.sub(r'\{(-?\d+(?:[.,]\d+)?)\}', r'\\{\1\\}', value)
    value = value.replace('∪', r'\cup ').replace('∞', r'\infty ')
    pair = re.fullmatch(r'(-?\d+)([°∘]?)\s*и\s*(-?\d+)([°∘]?)', value)
    if pair:
        a, a_degree, b, b_degree = pair.groups()
        a += r'^{\circ}' if a_degree else ''
        b += r'^{\circ}' if b_degree else ''
        return apply_imported_answer(f'${a}$ и ${b}$')
    if re.fullmatch(r'-?\d+(?:[.,]\d+)?', value):
        value = f'${value}$'
    mathish = any(token in value for token in ('\\', '∪', 'cup', '{', '}', ';'))
    interval = bool(re.search(r'[\[\(\]\)]', value)) and any(
        ch in value for ch in ';,')
    if (mathish or interval) and not value.startswith('$'):
        value = f'${value}$'
    result = apply_imported_answer(value)
    # OCR ключа оборачивает часть пары в $$ внутри уже открытого $...$.
    # Для чисто математического ответа оставляем одну пару разделителей;
    # текстовые ответы (например «2 и 3») сохраняют отдельные формулы.
    if result.count('$') > 2 and not re.search(r'[А-Яа-яЁё]', result):
        result = '$' + result.replace('$', '').strip() + '$'
    return result


def _coordinate_fraction_from_words(words):
    """Восстанавливает пару координат с одной вертикальной дробью из PDF.

    При другой структуре ответ не угадывается: возвращается None.
    """
    numerators = [(word, re.fullmatch(r'\(︂(-?\d+)', word[4])) for word in words]
    numerators = [(word, match.group(1)) for word, match in numerators if match]
    if len(numerators) != 1:
        return None
    numerator, value = numerators[0]
    denominators = [word for word in words
                    if re.fullmatch(r'\d+;?', word[4])
                    and numerator[0] < word[0] < numerator[2]
                    and 7 < word[1] - numerator[1] < 25]
    if len(denominators) != 1:
        return None
    denominator = denominators[0]
    if int(denominator[4].rstrip(';')) == 0:
        return None
    parts = []
    for word in sorted(words, key=lambda word: word[0]):
        if word == numerator:
            parts.append(r'(\frac{%s}{%s}' % (value, denominator[4].rstrip(';')))
            if denominator[4].endswith(';'):
                parts.append(';')
        elif word != denominator:
            parts.append(word[4].replace('︂', '').replace('−', '-'))
    text = ''.join(parts)
    if not re.fullmatch(r'\(\\frac\{-?\d+\}\{\d+\};-?\d+\);\(-?\d+;-?\d+\)\.?', text):
        return None
    return normalize_oge_answer(text)


def extract_pdf_answers(pdf_path: Path) -> tuple[dict[str, str], set[str]]:
    """Читает якоря ``ans::`` / ``task::`` и текст ключа из PDF."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            'Для разбора PDF нужен PyMuPDF (pip install pymupdf).'
        ) from exc
    doc = fitz.open(pdf_path)
    try:
        dests = doc.resolve_names()
        ans_pages = sorted({
            info['page'] for key, info in dests.items()
            if key.startswith('ans::') and isinstance(info, dict)
        })
        chunks = [doc[page].get_text('text') for page in ans_pages]
        expected_ids = {
            key[6:] for key in dests
            if key.startswith('task::') and LOCATOR_RE.fullmatch(key[6:])
            and not key.startswith('task::0.')
        }
        raw_answers = parse_answer_key_text('\n'.join(chunks))
        answers = {locator: normalize_oge_answer(raw)
                   for locator, raw in raw_answers.items()}
        page_words = {}
        for locator, raw in raw_answers.items():
            if '(︂' not in raw or 'ans::' + locator not in dests:
                continue
            page_number = dests['ans::' + locator]['page']
            if page_number not in page_words:
                page_words[page_number] = doc[page_number].get_text('words')
            words = page_words[page_number]
            labels = [word for word in words if word[4] == '№' + locator]
            if len(labels) != 1:
                continue
            label = labels[0]
            center = (label[1] + label[3]) / 2
            neighbors = [(word[1] + word[3]) / 2 for word in words
                         if word[4].startswith('№') and abs(word[0] - label[0]) < 20]
            top = (max((y for y in neighbors if y < center), default=center - 40) + center) / 2
            bottom = (min((y for y in neighbors if y > center), default=center + 40) + center) / 2
            page_width = doc[page_number].rect.width
            right = page_width / 2 if label[0] < page_width / 2 else page_width
            cell = [word for word in words if label[2] < word[0] < right
                    and top < (word[1] + word[3]) / 2 < bottom]
            repaired = _coordinate_fraction_from_words(cell)
            if repaired:
                answers[locator] = repaired
    finally:
        doc.close()
    return answers, expected_ids


def normalize_oge_choices(text: str) -> str:
    """Сохраняет номера четырёх вариантов в формате сайта и PDF."""
    def replace(match: re.Match) -> str:
        body = match.group(1)
        if r'\begin{enumerate}' in body or r'\end{enumerate}' in body:
            return match.group(0)
        # OCR иногда оставляет номер второго/третьего пункта внутри $…$.
        explicit = list(re.finditer(r'(?m)^\s*\$([234])\)', body))
        if len(re.findall(r'\\item\b', body)) == 3 and len(explicit) == 1:
            marker = explicit[0]
            before = len(re.findall(r'\\item\b', body[:marker.start()]))
            if int(marker.group(1)) == before + 1:
                body = body[:marker.start()] + '\n\\item $' + body[marker.end():]
        parts = re.split(r'\\item\b', body)
        if len(parts) != 5 or parts[0].strip():
            return match.group(0)
        choices = []
        for index, part in enumerate(parts[1:], 1):
            value = part.strip()
            if value.startswith('['):
                return match.group(0)
            value = re.sub(r'\\hspace\{0pt\}\s*', '', value)
            value = re.sub(r'(?:\\\\\s*)+$', '', value).strip()
            choices.append(f'{index}) {value}')
        return ('\\\\\n').join(choices)

    text = re.sub(r'\\begin\{enumerate\}(.*?)\\end\{enumerate\}',
                  replace, text or '', flags=re.DOTALL)
    # OCR теряет тире в определении медианы и делает из продолжения пункт.
    text = re.sub(r'(\$[^$]+\$)\s*\\begin\{itemize\}\s*\\item\s+'
                  r'(медиана,(?:(?!\\item|\\begin|\\end).)+)\\end\{itemize\}',
                  lambda m: m[1] + ' — ' + m[2].strip(), text, flags=re.DOTALL)

    def labelled_items(match):
        body = match.group(1)
        if r'\begin{' in body or r'\end{' in body:
            return match.group(0)
        parts = re.split(r'\\item\s*\[([^\]]+)\]', body)
        if parts[0].strip() or len(parts) < 3:
            return match.group(0)
        labels, values = parts[1::2], parts[2::2]
        numbered = len(labels) > 1 and labels == [f'{i})' for i in range(1, len(labels) + 1)]
        bullets = all(label == '-' for label in labels)
        if not (numbered or bullets) or any(r'\item' in value for value in values):
            return match.group(0)
        return ('\\\\\n').join(
            f'{label if numbered else "—"} {value.strip()}'
            for label, value in zip(labels, values))

    return re.sub(r'\\begin\{itemize\}(.*?)\\end\{itemize\}',
                  labelled_items, text, flags=re.DOTALL)


# Самостоятельные рубрики этого сборника, проверенные по исходному ключу разделов.
OGE_SECTION_TITLES = {
    '№1-№5. Квартиры.',
    'Вероятность противоположного события.',
    'Вписанные четырёхугольники.',
    'Вписанный треугольник.',
    'Выбор двух верных высказываний.',
    'Выражения с квадратными корнями.',
    'Выражения со степенями.',
    'Вычисления с квадратными корнями.',
    'Геометрическая прогрессия.',
    'Гиперболы с выколотой точкой.',
    'Дерево случайного опыта.',
    'Диаграммы Эйлера — Венна.',
    'Дробно-линейные функции с модулем.',
    'Задачи на работу.',
    'Задачи на смеси.',
    'Задачи посложнее.',
    'Задачи средней сложности.',
    'Касательная и секущая.',
    'Квадрат.',
    'Квадратичная зависимость.',
    'Квадратичные неравенства.',
    'Квадратичные функции с модулем.',
    'Квадратные уравнения.',
    'Медиана, биссектриса, высота и средняя линия.',
    'Неполные квадратные уравнения.',
    'Неравенства.',
    'Обыкновенные дроби.',
    'Описанные четырехугольники.',
    'Описанный треугольник.',
    'Параллелограмм и ромб.',
    'Площади.',
    'Площадь треугольника.',
    'Подобные треугольники.',
    'Прямоугольник.',
    'Прямоугольный треугольник.',
    'Равные треугольники.',
    'Ромб.',
    'Системы уравнений.',
    'Сравнение дробей.',
    'Статистическое определение вероятности.',
    'Трапеция.',
    'Уравнения.',
    'Хорды.',
}


def strip_oge_answer_tail(text: str) -> str:
    """Снимает конечный пустой бланк, в том числе приклеенный к условию."""
    return re.sub(r'''(?<!\w)Ответ:(?:\s|Ответ:|[—–+|□•"'`-])*$''', '', text).rstrip()


def normalize_oge_tariff_tables(text: str) -> str:
    """Переносит длинные ячейки тарифов внутри ширины печатного листка."""
    def replace(match):
        table = match.group(0)
        # Вложенные таблицы требуют отдельной сверки структуры.
        if table.count(r'\begin{tabular}') != 1:
            return table
        flat = re.sub(r'\s+', ' ', table)
        if 'Тарифный план & Абонентская плата & Плата за трафик' in flat:
            table = table.replace(r'{|l|l|l|}', r'{|p{1.7cm}|p{2.8cm}|p{3cm}|}', 1)
        elif ('Стоимость перехода на тариф &' in flat
              and 'Абонентская плата в месяц &' in flat):
            table = table.replace(r'{|l|l|}', r'{|p{4.3cm}|p{3.2cm}|}', 1)
            table = table.replace(r'\multicolumn{2}{|l|}',
                                  r'\multicolumn{2}{|p{7.9cm}|}')
            table = table.replace(r'на территории $P \Phi$', 'на территории РФ')
        return table
    return re.sub(r'\\begin\{tabular\}.*?\\end\{tabular\}', replace,
                  text, flags=re.DOTALL)


def normalize_oge_tire_tables(text: str) -> str:
    """Упрощает двухстрочный заголовок шин, сохраняя все строки размеров."""
    def replace(match):
        table = match.group(0)
        if 'Ширина шины' not in table or 'Диаметр диска' not in table:
            return table
        lines = table.splitlines()
        headings = [index for index, line in enumerate(lines) if re.match(r'\s*&\s*\d', line)]
        if len(headings) != 1:
            return table
        head = headings[0]
        diameters = [cell.strip() for cell in lines[head].strip().removesuffix(r'\\').split('&')[1:]]
        if not diameters or not all(value.isdigit() for value in diameters):
            return table
        data = []
        for line in lines[head + 1:]:
            if re.match(r'\s*\d+\s*&', line):
                if len(line.strip().removesuffix(r'\\').split('&')) != len(diameters) + 1:
                    return table
                data.append(line)
            elif line.strip() not in ('', r'\hline', r'\end{tabular}'):
                return table
        if not data:
            return table
        columns = '|p{2cm}|' + 'p{1.3cm}|' * len(diameters)
        title = 'Ширина шины, мм & ' + ' & '.join('Диск $' + value + '$ дюймов' for value in diameters) + r' \\'
        return (r'\begin{tabular}{' + columns + '}\n' + r'\hline' + '\n' + title + '\n'
                + r'\hline' + '\n' + '\n'.join(line + '\n' + r'\hline' for line in data)
                + '\n' + r'\end{tabular}')
    return re.sub(r'\\begin\{tabular\}.*?\\end\{tabular\}', replace, text, flags=re.DOTALL)


def normalize_oge_practical_tables(text: str) -> str:
    """Форматирует узнаваемые таблицы цен и печей без изменения чисел."""
    def replace(match):
        table = match.group(0)
        if table.count(r'\begin{tabular}') != 1:
            return table
        flat = re.sub(r'\s+', ' ', table.replace(r'\hspace{0pt}', ''))
        wrap_words = False
        if 'Продукт &' in flat:
            wrap_words = True
            table = table.replace(r'{|l|l|l|l|l|}',
                                  r'{|p{2cm}|p{1.4cm}|p{1.4cm}|p{1.4cm}|p{1.4cm}|}', 1)
        elif 'Номер печи & Тип & Объём помещения' in flat:
            wrap_words = True
            table = table.replace(r'{|l|l|l|l|l|}',
                                  r'{|p{1.1cm}|p{2.2cm}|p{1.7cm}|p{1cm}|p{1.5cm}|}', 1)
            table = table.replace(r'Объём помещения, $\mathbf{m}^{3}$',
                                  r'Объём помещения, $\text{м}^{3}$')
        if 'Номер печи &' in flat:
            table = table.replace('Macca, кг', 'Масса, кг')
        if wrap_words:
            # TeX не переносит первое слово в p-ячейке без нулевого отступа.
            table = re.sub(r'((?:\\hline|&|\\\\)\s*)(?=[А-Яа-яЁё])',
                           r'\1\\hspace{0pt}', table)
        return table
    return re.sub(r'\\begin\{tabular\}.*?\\end\{tabular\}', replace,
                  normalize_oge_tariff_tables(normalize_oge_tire_tables(text)), flags=re.DOTALL)


def _clean_body(raw: str) -> str:
    from .ostromogilsky_apartment_tables import normalize_apartment_tables
    has_answer_blank = bool(re.search(r'(?m)^\s*Ответ:', raw))
    body = strip_oge_noise(raw)
    body = drop_junk_graphics(body)
    body = OCR_FOOTER_TAIL_RE.sub('', body)
    body = NAV_BUTTON_LINE_RE.sub('', body)
    body = TRAILING_NOISE_RE.sub('', body)
    body = ANSWER_BLANK_LINE_RE.sub('', body)
    body = INLINE_NAV_WORD_RE.sub('', body)
    body = SECTION_CMD_RE.sub('', body)
    body = re.sub(r'^\\(?:sub)*section\*?\{', '', body.strip())
    body = NAV_GLYPH_LINE_RE.sub('', body)
    body = BOX_LINE_RE.sub('', body)
    body = re.sub(r'(?m)^\s*Ответ:\s*$', '', body)
    body = re.sub(r'(?m)(?:\\\\)?\n\s*\d{2,4}\s*(?:\\\\)?\s*$', '', body)
    body = re.sub(r"(?:\\\\)?\n\s*['`]\s*$", '', body)
    body = re.sub(r'\n{3,}', '\n\n', body).strip()
    body = re.sub(r'(?:\\\\\s*)+$', '', body).strip()
    body = re.sub(r'(?:\\\\[ \t]*){2,}', r'\\\\', body)
    # Одиночная клетка бланка иногда распознана как отдельный пункт списка.
    body = re.sub(r'\\begin\{itemize\}\s*\\item\s*□(?:\s|\\\\)*\\end\{itemize\}\s*$', '', body).rstrip()
    body = normalize_oge_choices(normalize_imported_text(body))
    body = normalize_oge_practical_tables(body)
    body = normalize_apartment_tables(body)
    # Рубрика относится к следующей задаче; удаляем лишь отдельный хвост.
    head, separator, tail = body.rpartition("\n\n")
    if separator and head.strip() and tail.strip() in OGE_SECTION_TITLES:
        body = head.rstrip()
    if has_answer_blank:
        # OCR превращает клетки бланка в отдельный абзац из штрихов.
        # Без маркера бланка и внутри формул такие символы не удаляем.
        body = re.sub(r'''\n\s*\n[\s—–+|□•"'`-]+$''', '', body).rstrip()
    return strip_oge_answer_tail(body)


def _earliest_cut(start: int, end: int, *hit_lists) -> int:
    cut = end
    for hits in hit_lists:
        for item in hits:
            pos = item.start()
            if start < pos < cut:
                cut = pos
    return cut


def _line_end(text: str, pos: int) -> int:
    newline = text.find('\n', pos)
    return len(text) if newline < 0 else newline + 1


def _cluster_slug(title: str) -> str:
    text = re.sub(r'\s+', '-', (title or '').strip().lower())
    text = text.replace('ё', 'е').replace('і', 'и')
    text = re.sub(r'[^a-z0-9а-я-]+', '', text).strip('-')
    return text or 'cluster'


def _collection_for(locator: str, exam_title: str, cluster: str) -> tuple[
        list[str], str, str]:
    number = exam_number(locator)
    analog = is_analog_id(locator)
    kind = 'Аналоги' if analog else 'Прототипы'
    if number <= 5:
        cluster_name = cluster or 'Практический комплекс'
        path = [
            '№1–5. Практические задачи',
            cluster_name,
            kind,
        ]
        proto = locator.split('.')[1]
        key = (
            f'oge/01-05/{_cluster_slug(cluster_name)}/'
            f'{"analog" if analog else "proto"}/{proto}'
        )
        title = f'{cluster_name} — {kind.lower()}'
        return path, key, title
    heading = f'№{number}. {exam_title}'
    path = [heading, kind]
    key = f'oge/{number:02d}/{"analog" if analog else "proto"}'
    return path, key, f'{heading} — {kind.lower()}'


def parse_ostromogilsky(
        text: str, *,
        answers: dict[str, str] | None = None,
        expected_ids: set[str] | None = None,
        pdf_task_contexts=None,
) -> tuple[list[TaskDraft], dict]:
    """Режет OCR-TeX банка ОГЭ и сливает ответы по ``N.P.A``."""
    if answers is None:
        raise ValueError(
            'Для профиля ostromogilsky обязателен ключ ответов из PDF')

    formula_answers = parse_tex_formula_answers(text, answers)
    answers = {**answers, **formula_answers}

    # OCR иногда приклеивает следующий заголовок к последней строке задачи.
    text = re.sub(
        r'(?<=[^\S\n])(?=(?:Задача|Аналог)\s+\d+\.\d+(?:\.\d+)?\.)',
        '\n', text)
    clipped = clip_oge_body(strip_oge_noise(text))
    markers = list(TASK_START_RE.finditer(clipped))
    shared_hits = list(SHARED_RE.finditer(clipped))
    exam_heads = list(EXAM_HEADING_RE.finditer(clipped))
    major_hits = list(MAJOR_RE.finditer(clipped))
    cluster_hits = list(PRACTICAL_CLUSTER_RE.finditer(clipped))

    analog_from = next(
        (item.start() for item in major_hits if item.group('title') == 'АНАЛОГИ'),
        len(clipped))

    def heading_at(pos: int, hits, default=''):
        current = default
        for item in hits:
            if item.start() > pos:
                break
            current = item
        return current

    shared_bodies: dict[str, str] = {}
    for index, hit in enumerate(shared_hits):
        start = _line_end(clipped, hit.start())
        following = [item.start() for item in markers if item.start() > hit.start()]
        following += [item.start() for item in shared_hits[index + 1:]]
        end = min(following) if following else len(clipped)
        end = _earliest_cut(hit.start(), end, exam_heads, major_hits)
        body = _clean_body(clipped[start:end])
        for locator in expand_shared_ids(hit.group('a'), hit.group('b')):
            shared_bodies[locator] = body

    cluster_by_proto: dict[str, str] = {}
    tasks: list[TaskDraft] = []
    seen: dict[str, int] = {}
    duplicates: list[str] = []

    for index, hit in enumerate(markers):
        locator = hit.group('id')
        if locator.startswith('0.'):
            continue
        if locator in seen:
            duplicates.append(locator)
            continue
        seen[locator] = index
        start = _line_end(clipped, hit.start())
        end = markers[index + 1].start() if index + 1 < len(markers) else len(clipped)
        end = _earliest_cut(
            hit.start(), end, exam_heads, major_hits, shared_hits)
        header = clipped[hit.start():start]
        tags = TAG_RE.findall(header)
        body = _clean_body(clipped[start:end])
        shared = shared_bodies.get(locator, '')
        if shared:
            body = f'{shared}\n\n{body}'.strip() if body else shared
        if not body:
            continue

        number = exam_number(locator)
        exam_hit = heading_at(hit.start(), exam_heads)
        if exam_hit and int(exam_hit.group('n')) == number:
            exam_title = exam_hit.group('title').strip().rstrip('.')
        else:
            exam_title = EXAM_TITLES.get(number, f'Задание {number}')
        cluster_hit = heading_at(hit.start(), cluster_hits)
        cluster = ''
        if number <= 5 and is_analog_id(locator):
            # В разделе аналогов заголовки тем могут отсутствовать: последний
            # заголовок прототипов («Тарифы») к ним не относится.
            proto = locator.split('.')[1]
            cluster = cluster_by_proto.get(proto, '')
        elif number <= 5 and cluster_hit:
            cluster = cluster_hit.group('title').replace('ШІины', 'Шины')
            proto = locator.split('.')[1]
            cluster_by_proto.setdefault(proto, cluster)
        elif number <= 5:
            proto = locator.split('.')[1]
            cluster = cluster_by_proto.get(proto, '')

        path, collection_key, collection_title = _collection_for(
            locator, exam_title, cluster)
        warnings: list[str] = []
        answer = answers.get(locator, '')
        if not answer and number != 24:
            warnings.append('Нет авторского ответа в ключе PDF')
        if hit.start() >= analog_from and not is_analog_id(locator):
            warnings.append('Маркер аналога без третьего номера')

        draft = TaskDraft(
            external_id=locator,
            source_number=locator,
            source_path=path,
            collection_key=collection_key,
            collection_title=collection_title,
            topic_original=exam_title,
            text_latex=body,
            author_answer_latex=answer,
            exam_item_codes=[exam_item_code(locator)],
            grade_band_codes=['GRADE_9'],
            tags=tags,
            warnings=warnings,
            confidence=1.0 if not warnings else 0.7,
        )
        finalize_draft_images(draft)
        tasks.append(draft)

    recovered = []
    if pdf_task_contexts:
        from .ostromogilsky_splits import recover_geometry_splits, recover_practical_splits
        tasks, recovered = recover_geometry_splits(tasks, pdf_task_contexts, answers)
        tasks, practical_recovered = recover_practical_splits(tasks, pdf_task_contexts, answers)
        recovered.extend(practical_recovered)
    parsed_ids = {task.external_id for task in tasks}
    expected = {
        item for item in (expected_ids or set())
        if not item.startswith('0.')
    }
    missing = sorted(expected - parsed_ids, key=lambda item: [
        int(part) for part in item.split('.')])
    extra_answers = sorted(set(answers) - parsed_ids, key=lambda item: [
        int(part) for part in item.split('.')])
    by_exam = Counter(exam_number(task.external_id) for task in tasks)
    diagnostics = {
        'unique_tasks': len(tasks),
        'pdf_verified_splits': recovered,
        'prototype_count': sum(not is_analog_id(t.external_id) for t in tasks),
        'analog_count': sum(is_analog_id(t.external_id) for t in tasks),
        'duplicate_task_ids': sorted(set(duplicates)),
        'missing_task_ids': missing,
        'answers_without_task': extra_answers,
        'tasks_with_shared_stem': sum(
            1 for task in tasks if task.external_id in shared_bodies),
        'answers_matched': sum(bool(task.author_answer_latex) for task in tasks),
        'formula_answers_from_tex': len(formula_answers),
        'expected_pdf_tasks': len(expected),
        'expected_pdf_answers': len(answers),
        'tasks_by_exam': {
            str(number): count for number, count in sorted(by_exam.items())
        },
        'shared_blocks': len(shared_hits),
    }
    return tasks, diagnostics


def bundle_from_pdf(
        tasks_text: str, answers_pdf: Path, *,
        tasks_file: str = 'tasks.tex', answers_file: str = '') -> tuple[
            list[TaskDraft], dict]:
    answers, expected_ids = extract_pdf_answers(answers_pdf)
    from .ostromogilsky_splits import extract_pdf_task_contexts
    return parse_ostromogilsky(
        tasks_text, answers=answers, expected_ids=expected_ids,
        pdf_task_contexts=extract_pdf_task_contexts(answers_pdf))

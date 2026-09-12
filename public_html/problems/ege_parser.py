"""Разбор открытого банка ЕГЭ по профильной математике.

Этот модуль намеренно не использует правила ремонта банка ОГЭ.  OCR-TeX и
интерактивный PDF здесь являются двумя независимыми источниками: TeX даёт
исходную разметку и картинки, PDF подтверждает полный список заданий и
позволяет восстановить потерянные OCR-границы.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from .textbook_parser import (
    TaskDraft, apply_imported_answer, finalize_draft_images,
    normalize_imported_text, split_subitems,
    read_group,
)


LOCATOR_RE = re.compile(r"\d+\.\d+(?:\.\d+)?\Z")
TASK_START_RE = re.compile(
    r"(?m)^\s*(?:\\section\*\{)?(?P<kind>Задача|Аналог)\s+"
    r"(?P<id>\d+\.\d+(?:\.\d+)?)\.(?P<header>[^\n}]*)\}?"
)
EXAM_HEADING_RE = re.compile(
    r"(?m)^\s*(?:\\section\*\{)?№\s*(?P<number>\d+)\.\s*"
    r"(?P<title>[^\\\n}]+)"
)
TAG_RE = re.compile(r"\b(?:SIM|DEMO|NEW)\b")
PDF_TASK_RE = re.compile(r"(?:Задача|Аналог)\s+(\d+\.\d+(?:\.\d+)?)\.")
PDF_NOISE_RE = re.compile(
    r"(?ms)^\s*(?:Оглавление|<\s*<\s*<|Ответы|Библиотека MathStart|"
    r"Группа MathStart).*?(?=\n(?:Задача|№|\Z))"
)
NAVIGATION_TABLE_RE = re.compile(
    r'(?s)\\begin\{tabular\}(?:\[[^]]*\])?\{[^}]*\}'
    r'(?:(?!\\begin\{tabular\}).)*?Оглавление.*?\\end\{tabular\}'
)
BLANK_ANSWER_TABLE_RE = re.compile(
    r'(?s)\\begin\{tabular\}(?:\[[^]]*\])?\{[^}]*\}'
    r'(?:(?!\\begin\{tabular\}).)*?Ответ:\s*(?:&\s*){2,}'
    r'(?:(?!\\begin\{tabular\}).)*?\\end\{tabular\}'
)
EMPTY_LAYOUT_TABLE_RE = re.compile(
    r'(?s)\\begin\{tabular\}(?:\[[^]]*\])?\{[^}]*\}'
    r'(?:\s|&|\\\\|\\hline|Аналоги|Ответ|□)*\\end\{tabular\}'
)
UNMARKED_TASK_RE = re.compile(
    r'(?m)(?:^|\n)\s*(?:Ответ:\s*){2,}(?:Аналоги\s+)?Ответ\s*\n+'
)
SECTION_CUT_RE = re.compile(
    r'(?m)^\s*\\section\*\{(?:№\s*\d+\.|СТАРЫЕ ЗАДАЧИ|'
    r'ЗАДАЧИ С (?:КРАТКИМ|РАЗВЁРНУТЫМ) ОТВЕТОМ|АНАЛОГИ)'
)
CHAPTER_TITLES = {
    1: 'Планиметрия 1', 2: 'Векторы', 3: 'Стереометрия 1',
    4: 'Вероятность 1', 5: 'Вероятность 2', 6: 'Случайные величины',
    7: 'Уравнения 1', 8: 'Вычисления и преобразования',
    9: 'Производная и её график', 10: 'Задачи с прикладным содержанием',
    11: 'Текстовые задачи', 12: 'Анализ графика', 13: 'Финансовые задачи',
    14: 'Уравнения 2', 15: 'Стереометрия 2', 16: 'Неравенства',
    17: 'Экстремальные задачи', 18: 'Планиметрия 2',
    19: 'Задачи с параметром', 20: '«Нестандартные» задачи',
}


def _sort_key(locator: str) -> tuple[int, ...]:
    return tuple(int(part) for part in locator.split('.'))


def exam_number(locator: str) -> int:
    return int(locator.split('.', 1)[0])


def exam_item_code(locator: str) -> str:
    """Код линии ЕГЭ, к которой относится задание."""
    return f"EGE_PROFILE_2027_{exam_number(locator):02d}"


def normalize_ege_answer(raw: str) -> str:
    """Безопасная нормализация текстового ответа из печатного ключа."""
    value = (raw or '').strip().replace('−', '-').replace('–', '-')
    value = re.sub(r"\s+", " ", value)
    if value.endswith('.') and not value.endswith('...'):
        value = value[:-1].rstrip()
    if re.fullmatch(r"-?\d+(?:[.,]\d+)?", value):
        value = f"${value}$"
    elif ('\\' in value or '∪' in value or '∞' in value) and not value.startswith('$'):
        value = '$' + value.replace('∪', r'\cup ').replace('∞', r'\infty ') + '$'
    return apply_imported_answer(value)


def _pdf_marker_rect(page, locator: str):
    """Находит напечатанный заголовок, не доверяя одной named destination."""
    for kind in ('Задача', 'Аналог'):
        rects = page.search_for(f"{kind} {locator}.")
        if rects:
            return rects[0]
    # В некоторых версиях PDF номер разбит на отдельные слова.
    words = page.get_text('words')
    for index, word in enumerate(words[:-1]):
        if word[4] in {'Задача', 'Аналог'} and index + 1 < len(words):
            number = words[index + 1][4].rstrip('.')
            if number == locator:
                import fitz
                return fitz.Rect(word[:4]) | fitz.Rect(words[index + 1][:4])
    return None


def _clip_for_marker(page, marker):
    """Возвращает прямоугольник от заголовка до следующей задачи на странице."""
    import fitz
    words = page.get_text('words')
    bottoms = []
    for index, word in enumerate(words[:-1]):
        if (word[4] in {'Задача', 'Аналог'}
                and words[index + 1][4].rstrip('.').count('.') >= 1):
            if word[1] > marker.y1 + 2:
                bottoms.append(word[1])
    bottom = min(bottoms) if bottoms else page.rect.height
    return fitz.Rect(0, max(0, marker.y0 - 3), page.rect.width, bottom)


def _json_rect(rect) -> list[float]:
    return [round(value, 2) for value in (rect.x0, rect.y0, rect.x1, rect.y1)]


def _answer_clip(page, locator: str, destination, words):
    """Ячейка ответа по её фактической подписи, не по системе координат link."""
    import fitz
    labels = [fitz.Rect(word[:4]) for word in words if word[4] == '№' + locator]
    if not labels:
        return None
    point = destination.get('to') or (0, 0)
    target_y = float(point[1]) if len(point) > 1 else 0.0
    label = min(labels, key=lambda item: abs(item.y0 - target_y))
    center = (label.y0 + label.y1) / 2
    neighbor_centers = [
        (word[1] + word[3]) / 2 for word in words
        if word[4].startswith('№') and abs(word[0] - label.x0) < 20
    ]
    top = (max((y for y in neighbor_centers if y < center), default=center - 40)
           + center) / 2
    bottom = (min((y for y in neighbor_centers if y > center), default=center + 40)
              + center) / 2
    following_columns = [word[0] - 5 for word in words
                         if word[4].startswith('№') and word[0] > label.x1 + 35
                         and top <= (word[1] + word[3]) / 2 <= bottom]
    right = min(following_columns, default=page.rect.width - 45)
    return fitz.Rect(label.x0, top, right, bottom)


def build_pdf_index(pdf_path: Path) -> dict:
    """Индексирует подтверждённые PDF-задания и их ссылки на ответы.

    Номера из ``task::`` принимаются только если на целевой странице реально
    напечатан заголовок «Задача N.P.».  Это отсеивает ложный ``task::5.8.1``
    с титульной страницы и делает индекс пригодным для QA без TeX.
    """
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('Для разбора PDF нужен PyMuPDF (pip install pymupdf).') from exc

    doc = fitz.open(pdf_path)
    try:
        destinations = doc.resolve_names()
        tasks: dict[str, dict] = {}
        invalid: list[dict] = []
        for key, destination in destinations.items():
            if not key.startswith('task::'):
                continue
            locator = key[6:]
            if not LOCATOR_RE.fullmatch(locator) or not isinstance(destination, dict):
                invalid.append({'anchor': key, 'reason': 'некорректный номер'})
                continue
            if not 1 <= exam_number(locator) <= 20:
                invalid.append({'anchor': key, 'id': locator,
                                'reason': 'старое задание вне банка 1–20'})
                continue
            page_number = destination.get('page')
            if not isinstance(page_number, int) or not 0 <= page_number < len(doc):
                invalid.append({'anchor': key, 'reason': 'некорректная страница'})
                continue
            page = doc[page_number]
            marker = _pdf_marker_rect(page, locator)
            if marker is None:
                invalid.append({
                    'anchor': key, 'id': locator, 'page': page_number + 1,
                    'reason': 'на странице назначения нет маркера задания',
                })
                continue
            clip = _clip_for_marker(page, marker)
            text = page.get_text('text', clip=clip).strip()
            # search_for can in theory find a reference to a task in prose.
            matched = PDF_TASK_RE.search(text)
            if not matched or matched.group(1) != locator:
                invalid.append({'anchor': key, 'id': locator, 'page': page_number + 1,
                                'reason': 'маркер задания не подтверждён текстом'})
                continue
            tasks[locator] = {'page': page_number + 1, 'clip': _json_rect(clip), 'text': text}

        answer_words: dict[int, list] = {}
        for locator, row in tasks.items():
            destination = destinations.get('ans::' + locator)
            if not isinstance(destination, dict) or not isinstance(destination.get('page'), int):
                continue
            page_number = destination['page']
            if not 0 <= page_number < len(doc):
                continue
            page = doc[page_number]
            if page_number not in answer_words:
                answer_words[page_number] = page.get_text('words')
            words = answer_words[page_number]
            answer_clip = _answer_clip(page, locator, destination, words)
            row['answer_page'] = page_number + 1
            if answer_clip is not None:
                row['answer_clip'] = _json_rect(answer_clip)
        return {'tasks': dict(sorted(tasks.items(), key=lambda pair: _sort_key(pair[0]))),
                'invalid_anchors': invalid}
    finally:
        doc.close()


def extract_pdf_answers(pdf_path: Path) -> tuple[dict[str, str], set[str]]:
    """Извлекает текстовые ответы; список номеров берёт из независимого индекса."""
    # Существующая функция хорошо обрабатывает многоколоночный ключ и дроби.
    # Это общий разбор PDF, а не набор ремонтов ОГЭ.
    from .ostromogilsky_parser import extract_pdf_answers as extract
    answers, _ignored = extract(pdf_path)
    index = build_pdf_index(pdf_path)
    expected = set(index['tasks'])
    return ({key: value for key, value in answers.items() if key in expected}, expected)


def parse_tex_formula_answers(text: str, allowed_ids) -> dict[str, str]:
    """Берёт из TeX только явно распознанные дроби и корни ключа ответов."""
    from .ostromogilsky_parser import parse_tex_formula_answers as parse
    return parse(text, allowed_ids)


def _strip_tex_navigation(value: str) -> str:
    value = re.sub(r'\\caption\{Ответ:\s*\}', '', value)
    value = NAVIGATION_TABLE_RE.sub('\n', value)
    value = BLANK_ANSWER_TABLE_RE.sub('\n', value)
    value = EMPTY_LAYOUT_TABLE_RE.sub('\n', value)
    value = re.sub(r'(?m)^\s*(?:Аналоги|Ответ)\s*(?:\\\\)?\s*$', '', value)
    value = re.sub(r'(?m)^\s*Ответ:(?:\s*Ответ:)*.*$', '', value)
    # Полные и обломанные пустые бланки: таблицы с данными не совпадают.
    value = re.sub(r'\\textbackslash\s+(?:begin|end)\\?\{tabular\\?\}(?:\\?\{[^\n]*?\\?\})?', '', value)
    value = re.sub(r'\\textbackslash\s+hline', r'\\hline', value)
    value = re.sub(r'(?s)\\begin\{tabular\}(?:\[[^]]*\])?\{[^}]*\}'
                   r'(?:\s|&|\\\\|\\hline|Ответ:)*\\end\{tabular\}', '', value)
    value = re.sub(r'(?m)^\s*(?:Аналоги|Прототип|Ответ|SIM|DEMO|NEW)(?:\s|Аналоги|Прототип|Ответ|SIM|DEMO|NEW|\\\\)*$', '', value)
    value = re.sub(r'(?m)^\s*(?:\\hline|\\&|[&+—\-|□]|\\\\|\s)+$', '', value)
    value = re.sub(r'Ответ:(?!\s*дайте)[^\n]*', '', value)
    value = re.sub(r'(?s)\n\s*[А-ЯЁ][А-Яа-яЁё\s-]{0,70}'
                   r'(?:уравнения|неравенства|функции)\.\s*$', '', value)
    value = re.sub(r'(?s)\nОглавление.*$', '', value)
    value = re.sub(r'(?m)^\s*\\(?:section\*|caption)\{[^\n]*\}\s*$', '', value)
    value = re.sub(r'\\begin\{table\}(?:\[[^]]*\])?\s*\\end\{table\}', '', value)
    return value.strip()


def _topic_at(position: int, headings, source: str = '') -> str:
    current = ''
    for heading in headings:
        if heading.start() > position:
            break
        current = heading.group('title').strip().rstrip('.').replace('\\\\', '').strip()
    if not current:
        return f'Задание {position}'
    # Сразу после заголовка № обычно напечатана короткая подгруппа
    # («Треугольник.», «Прямая.»). Берём только первую строку блока, чтобы
    # не принять за тему текст предыдущей задачи.
    if source:
        heading = next((item for item in reversed(headings)
                        if item.start() <= position), None)
        if heading:
            tail = source[heading.end():position]
            for line in tail.splitlines():
                candidate = line.strip().replace(r'\\', '').strip()
                if not candidate or candidate.startswith(('Задача ', 'Аналог ')):
                    continue
                if (len(candidate) <= 90 and '\\' not in candidate
                        and not candidate.startswith(('Ответ', 'Аналоги'))):
                    return f'{current}. {candidate.rstrip(".")}'
                break
    return current


def _letter_subitems(body: str):
    body = re.sub(r'\\item\s*\[\s*\]\s*', ' ', body)
    # Численные списки часто входят в условие (например, финансовое). Здесь
    # самостоятельными подпунктами являются только явно помеченные буквы.
    match = re.fullmatch(r'(?s)(?P<parent>.*?)\\begin\{itemize\}(?P<items>.*?)\\end\{itemize\}\s*', body)
    if match:
        pieces = re.split(r'\\item\s*\[([^\]]+)\]', match.group('items'))
        if len(pieces) >= 5 and not pieces[0].strip():
            from .textbook_parser import SubitemDraft
            labels = {'a': 'а', 'b': 'б', 'v': 'в'}
            subitems = []
            for label, item in zip(pieces[1::2], pieces[2::2]):
                key = label.strip().rstrip(')').lower()
                key = labels.get(key, key)
                subitems.append(SubitemDraft(key, normalize_imported_text(item).strip()))
            parent = match.group('parent').strip()
        else:
            parent, subitems = split_subitems(body, allow_numbered_parts=False)
    else:
        parent, subitems = split_subitems(body, allow_numbered_parts=False)
    if len(subitems) < 2:
        return body, []
    aliases = {'a': 'а', 'b': 'б', 'v': 'в'}
    for item in subitems:
        item.label = aliases.get(item.label.lower(), item.label.lower())
    if not all(re.fullmatch(r'[а-я]', item.label) for item in subitems):
        return body, []
    return parent, subitems


def _plain_bullet_lists(body: str) -> str:
    """Сохраняет условия финансовых задач списком внутри одной карточки."""
    def convert(match):
        content = match.group(1)
        labels = re.findall(r'\\item\s*(?:\[([^]]*)\])?', content)
        if not labels or any(label.strip() not in {'', '-'} for label in labels):
            return match.group(0)
        return re.sub(r'\\item\s*(?:\[[^]]*\])?\s*', '\n\n— ', content).strip()
    return re.sub(r'(?s)\\begin\{itemize\}(.*?)\\end\{itemize\}', convert, body)


def _remove_empty_arrays(body: str) -> str:
    """Распознаёт также повреждённую OCR оболочку пустого бланка ответа."""
    def replace(match):
        content = re.sub(r'\\(?:hline|text|mathrm)\b', '', match.group(1))
        return '' if not re.sub(r'[\s{}&\\□|]', '', content) else match.group(0)
    return re.sub(r'(?s)\\\[\s*\\begin\{array\}\{[^}]*\}(.*?)'
                  r'\\end\{array\}\s*\\\]', replace, body)


def _source_fields(locator: str, title: str) -> tuple[list[str], str, str]:
    """Путь хранит семейство прототипа, а не общий раздел «Аналоги»."""
    parts = locator.split('.')
    number = int(parts[0])
    prototype = '.'.join(parts[:2])
    heading = f'№{number}. {title}'
    path = [heading, f'Прототип {prototype}']
    key = f'ege/{number:02d}/{prototype}'
    if len(parts) == 3:
        path.append('Аналоги')
        key += '/analogs'
    return path, key, f'{heading} — прототип {prototype}'


def _pdf_body(context: dict, locator: str) -> str:
    text = context.get('text', '')
    text = re.sub(rf'(?s)^.*?(?:Задача|Аналог)\s+{re.escape(locator)}\.\s*', '', text, count=1)
    text = re.split(r'\n\s*(?:Ответ:|Оглавление)\b', text, maxsplit=1)[0]
    text = re.sub(r'(?m)^\s*(?:Аналоги|Прототип|Ответ|Ответ:|SIM|DEMO|NEW)\s*$', '', text)
    text = re.sub(r'(?<=[а-я])-\n(?=[а-я])', '', text)
    text = re.split(r'\n\s*Оглавление', text, maxsplit=1)[0]
    text = re.sub(r'(?m)^\s*[A-Za-z][0-9]*\s*$', '', text)
    return normalize_imported_text(text).strip()


def _word_tokens(value: str):
    """Русские слова и числа с позициями: достаточно для поиска OCR-фразы."""
    return [(match.group(0).lower().replace('ё', 'е'), match.start())
            for match in re.finditer(r'[А-Яа-яЁё]{3,}|\d+', value)]


def _unwrap_layout_tables(text):
    """Убирает OCR-таблицы раскладки карточек, сохраняя таблицы данных."""
    spans, stack = [], []
    for match in re.finditer(r'\\(begin|end)\{tabular\}', text):
        if match[1] == 'begin':
            stack.append(match.start())
        elif stack:
            start = stack.pop()
            if not stack and re.search(r'(?:Задача|[АA]налог)\s+\d+\.\d+', text[start:match.end()]):
                spans.append((start, match.end()))
    for start, end in reversed(spans):
        body = text[start:end]
        # multicolumn — оболочка ячейки, третья группа содержит сам текст.
        for match in reversed(list(re.finditer(r'\\multicolumn\s*\{', body))):
            try:
                _n, pos = read_group(body, match.end() - 1)
                while body[pos].isspace(): pos += 1
                _align, pos = read_group(body, pos)
                while body[pos].isspace(): pos += 1
                content, finish = read_group(body, pos)
                body = body[:match.start()] + content + body[finish:]
            except (ValueError, IndexError):
                continue
        for match in reversed(list(re.finditer(r'\\begin\{tabular\}(?:\[[^]]*\])?\s*\{', body))):
            try:
                _cols, finish = read_group(body, match.end() - 1)
                body = body[:match.start()] + '\n' + body[finish:]
            except ValueError:
                continue
        body = re.sub(r'\\end\{tabular\}|\\hline', '\n', body)
        body = body.replace('&', '\n').replace('□', '')
        body = re.sub(r'(?=(?:Задача|[АA]налог)\s+\d+\.\d+)', '\n', body)
        text = text[:start] + body + text[end:]
    return text.replace('Aналог ', 'Аналог ')


def _missing_marker_offset(raw: str, locator: str, context: dict,
                           left: int, right: int):
    """Находит начало потерянной карточки только в её соседнем TeX-окне."""
    pdf_words = _word_tokens(_pdf_body(context, locator))
    ignored = {'задача', 'аналог', 'прототип', 'ответ', 'sim', 'demo', 'new'}
    target = [word for word, _pos in pdf_words if word not in ignored]
    needle = target[:7]
    if len(needle) < 4:
        return None
    window = raw[left:right]
    source_words = _word_tokens(window)
    candidates = []
    for width in range(min(7, len(needle)), 2, -1):
        wanted = needle[:width]
        for index in range(len(source_words) - width + 1):
            if [word for word, _pos in source_words[index:index + width]] == wanted:
                sample = [word for word, _pos in source_words[index:index + len(target)]]
                score = SequenceMatcher(None, target, sample, autojunk=False).ratio()
                offset = left + source_words[index][1]
                # Сохраняем короткий предлог «В» / OCR «B» перед первым словом.
                line_start = raw.rfind('\n', left, offset) + 1
                prefix = raw[line_start:offset]
                if re.fullmatch(r'\s*(?:[А-ЯA-Z][а-я]{0,2})?\s*', prefix):
                    offset = line_start + len(prefix) - len(prefix.lstrip())
                candidates.append((score, offset))
        if candidates:
            break
    return max(candidates, default=(0, None), key=lambda item: (item[0], item[1] or 0))[1]


def _inject_missing_tex_markers(text: str, expected: set[str], contexts: dict):
    """Вставляет синтетические заголовки перед уже имеющимся OCR-условием.

    PDF здесь служит только ключом к соседнему TeX-отрезку; условие, формулы
    и includegraphics остаются исходными, а не плоским PDF-текстом.
    """
    markers = list(TASK_START_RE.finditer(text))
    present = {item.group('id'): item for item in markers
               if 1 <= exam_number(item.group('id')) <= 20}
    offsets: dict[str, int] = {}
    for locator in sorted(expected - set(present), key=_sort_key):
        context = contexts.get(locator)
        if not isinstance(context, dict):
            continue
        # Прототипы и аналоги расположены в разных крупных частях книги;
        # соседство определяем внутри того же вида номера, не по глобальному
        # числовому порядку (иначе 1.5 ищется после аналогов 1.5.*).
        ordered = sorted((key for key in present
                          if key.count('.') == locator.count('.')), key=_sort_key)
        before = [key for key in ordered if _sort_key(key) < _sort_key(locator)]
        after = [key for key in ordered if _sort_key(key) > _sort_key(locator)]
        left = present[before[-1]].end() if before else 0
        right = present[after[0]].start() if after else len(text)
        # Если OCR оставил ряд кнопок вместо номера, условие начинается после
        # последнего такого ряда, а не в тексте предыдущей карточки.
        offset = _missing_marker_offset(text, locator, context, left, right)
        if offset is not None:
            offsets[locator] = offset
    for locator, offset in sorted(offsets.items(), key=lambda item: item[1], reverse=True):
        kind = 'Аналог' if locator.count('.') == 2 else 'Задача'
        text = text[:offset] + f'\n{kind} {locator}.\n' + text[offset:]
    return text, set(offsets)


def parse_ege(text: str, *, answers: dict[str, str] | None = None,
              expected_ids: set[str] | None = None,
              pdf_task_contexts: dict | None = None) -> tuple[list[TaskDraft], dict]:
    """Разбирает OCR-TeX, восстанавливая только подтверждённые PDF-границы."""
    if answers is None:
        raise ValueError('Для профиля ЕГЭ обязателен ключ ответов из PDF')
    # Полный ключ уже должен быть подготовлен отдельным PDF/TeX-разбором.
    # Здесь нельзя подменять его частичным OCR-ключом дробей.
    answers = dict(answers)
    from .ege_repairs import repair_source
    text, source_repairs = repair_source(text)
    text = _unwrap_layout_tables(text)
    contexts = (pdf_task_contexts or {}).get('tasks', pdf_task_contexts or {})
    expected = set(expected_ids or contexts.keys())
    text, tex_recovered = _inject_missing_tex_markers(text, expected, contexts)
    markers = list(TASK_START_RE.finditer(text))
    headings = list(EXAM_HEADING_RE.finditer(text))
    rows: dict[str, TaskDraft] = {}
    raw_spans: dict[str, dict] = {}
    duplicates: list[str] = []
    titles_by_exam: dict[int, str] = {}
    for index, marker in enumerate(markers):
        locator = marker.group('id')
        if not 1 <= exam_number(locator) <= 20:
            continue
        if locator in rows:
            duplicates.append(locator)
            continue
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        section_cut = SECTION_CUT_RE.search(text, marker.end(), end)
        if section_cut:
            end = section_cut.start()
        raw_body = text[marker.end():end]
        # OCR иногда теряет заголовок следующей задачи, но оставляет ряд
        # кнопок «Ответ». Не приклеиваем её условие к предшественнику: сама
        # задача будет восстановлена только из подтверждённого PDF-контекста.
        unmarked = UNMARKED_TASK_RE.search(raw_body)
        if unmarked:
            raw_body = raw_body[:unmarked.start()]
        body = _strip_tex_navigation(raw_body)
        body = normalize_imported_text(body)
        body = body.replace(r"\mathrm{KM}", r"\text{км}")
        if not body:
            continue
        number = exam_number(locator)
        if marker.group('kind') == 'Аналог' and number in titles_by_exam:
            title = titles_by_exam[number]
        else:
            title = CHAPTER_TITLES.get(number, _topic_at(marker.start(), headings, text))
            if marker.group('kind') == 'Задача':
                titles_by_exam[number] = title
        body, subitems = _letter_subitems(body)
        warning = [] if locator in answers else ['Нет авторского ответа в ключе PDF']
        source_path, collection_key, collection_title = _source_fields(locator, title)
        rows[locator] = TaskDraft(
            external_id=locator, source_number=locator,
            source_path=source_path, collection_key=collection_key,
            collection_title=collection_title,
            topic_original=title, text_latex=body, subitems=subitems,
            author_answer_latex=answers.get(locator, ''),
            exam_item_codes=[exam_item_code(locator)], grade_band_codes=['GRADE_10_11'],
            tags=TAG_RE.findall(marker.group('header')), warnings=warning,
            confidence=1.0 if not warning else .7,
        )
        raw_spans[locator] = {'start': marker.start(), 'end': end}

    recovered: list[str] = []
    for locator in sorted(expected - set(rows), key=_sort_key):
        context = contexts.get(locator)
        if not isinstance(context, dict):
            continue
        body = _pdf_body(context, locator)
        if not body:
            continue
        body, subitems = _letter_subitems(body)
        warning = ['Граница восстановлена по PDF; в OCR-TeX нет маркера задания']
        if locator not in answers:
            warning.append('Нет авторского ответа в ключе PDF')
        number = exam_number(locator)
        title = titles_by_exam.get(number, f'Задание {number}')
        source_path, collection_key, collection_title = _source_fields(locator, title)
        rows[locator] = TaskDraft(
            external_id=locator, source_number=locator,
            source_path=source_path, collection_key=collection_key,
            collection_title=collection_title, topic_original=title,
            text_latex=body, subitems=subitems, author_answer_latex=answers.get(locator, ''),
            exam_item_codes=[exam_item_code(locator)], grade_band_codes=['GRADE_10_11'],
            warnings=warning, confidence=.55,
        )
        recovered.append(locator)

    tasks = [rows[key] for key in sorted(rows, key=_sort_key)]
    for task in tasks:
        finalize_draft_images(task)
        if task.external_id in contexts:
            task.tags = list(dict.fromkeys(TAG_RE.findall(contexts[task.external_id].get('text', ''))))
        if not task.subitems:
            task.text_latex, task.subitems = _letter_subitems(task.text_latex)
        task.text_latex = _plain_bullet_lists(task.text_latex)
        task.text_latex = _remove_empty_arrays(task.text_latex).strip()
        for item in task.subitems:
            item.text_latex = item.text_latex.strip()
        if (exam_number(task.external_id) in {15, 18}
                and [item.label for item in task.subitems] == ['а', 'б']
                and task.subitems[0].text_latex.startswith('Докажите')
                and not task.subitems[1].text_latex.startswith('Докажите')
                and task.author_answer_latex
                and not re.search(r'[аaбb]\)', task.author_answer_latex)):
            task.subitems[1].author_answer_latex = task.author_answer_latex
            task.author_answer_latex = ''
    parsed = set(rows)
    missing = sorted(expected - parsed, key=_sort_key)
    diagnostics = {
        'unique_tasks': len(tasks), 'tex_markers': len(markers),
        'duplicate_task_ids': sorted(set(duplicates), key=_sort_key),
        'missing_task_ids': missing, 'recovered_task_ids': recovered,
        'recovered_tex_marker_ids': sorted(tex_recovered, key=_sort_key),
        'prepared_tex_spans': raw_spans,
        'source_repairs': source_repairs,
        'answers_matched': sum(bool(item.author_answer_latex) or any(
            sub.author_answer_latex for sub in item.subitems) for item in tasks),
        'answers_without_task': sorted(set(answers) - parsed, key=_sort_key),
        'formula_answers_from_tex': 0,
        'expected_pdf_tasks': len(expected),
        'tasks_by_exam': {str(key): value for key, value in sorted(
            Counter(exam_number(item.external_id) for item in tasks).items())},
    }
    return tasks, diagnostics

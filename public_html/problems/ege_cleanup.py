"""Повторяемая очистка оформления ЕГЭ без изменения математического содержания."""
import re

# Формулы и аргументы команд не должны получать вложенные доллары.
_MATH = re.compile(r'(?<!\\)\$\$.*?(?<!\\)\$\$|\\\[.*?\\\]|(?<!\\)\$.*?(?<!\\)\$|\\\(.*?\\\)', re.S)
_NUMBER = re.compile(r'(?<![\w])[-+−]?\d+(?:[,.]\d+)?(?:°)?(?![\w])')
_TABLE = re.compile(r'\\begin\{tabular\}(?:\[[^]]*\])?\{[^}]*\}(.*?)\\end\{tabular\}', re.S)


def _noise_table(match):
    content = match[1]
    # Подписи вершин, ошибочно распознанные как одноколоночная таблица.
    labels = re.sub(r'\\\([A-Z](?:_\{\d+\})?\\\)|\\\\|\s', '', content)
    if not labels:
        return ''
    if '□' in content and not re.search(r'[а-яА-Я0-9]', content):
        return ''
    return match[0]


def strip_ege_noise(text):
    """Удаляет только узнаваемые строки навигации и пустые сетки."""
    text = _TABLE.sub(_noise_table, text or '')
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in {'Ответы', 'Оглавление', 'Аналоги', 'Прототип'}:
            continue
        if re.fullmatch(r'''[\s+|—\-□'"म]+''', stripped or 'a'):
            continue
        if re.fullmatch(r'(?:\$|\\\(|\\\)|\\\\|\s|\\textbackslash|\\ggg|ggg)+', stripped or 'a'):
            continue
        lines.append(line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def _command_end(text, start):
    """Пропускает TeX-команду и сбалансированные аргументы целиком."""
    command = re.match(r'\\[A-Za-z]+\*?', text[start:])
    if not command:
        return min(start + 2, len(text))
    end = start + command.end()
    while end < len(text):
        pos = end
        while pos < len(text) and text[pos] in ' \t':
            pos += 1
        if pos >= len(text) or text[pos] not in '{[':
            break
        opening = text[pos]; closing = '}' if opening == '{' else ']'
        depth = 1; pos += 1
        while pos < len(text) and depth:
            if text[pos] == '\\':
                pos += 2
                continue
            if text[pos] == opening:
                depth += 1
            elif text[pos] == closing:
                depth -= 1
            pos += 1
        if depth:
            break
        end = pos
    return end


def wrap_ege_numbers(text):
    """Числа обычного текста → $…$; формулы, подпункты и команды неизменны."""
    text = text or ''
    protected = {m.start(): m.end() for m in _MATH.finditer(text)}
    chunks = []; cursor = 0
    while cursor < len(text):
        if cursor in protected:
            end = protected[cursor]; chunks.append(text[cursor:end]); cursor = end
            continue
        if text[cursor] == '\\':
            end = _command_end(text, cursor); chunks.append(text[cursor:end]); cursor = end
            continue
        match = _NUMBER.match(text, cursor)
        if match:
            value = match[0].replace('−', '-').replace(',', '{,}')
            if value.endswith('°'):
                value = value[:-1] + r'^{\circ}'
            chunks.append('$' + value + '$'); cursor = match.end()
        else:
            chunks.append(text[cursor]); cursor += 1
    return ''.join(chunks)


def fix_approved_answer(number, text):
    """№19.26: знак объединения восстановлен по указанию редактора 12.09.2026."""
    expected = r'(-\infty;0)\cup\left(0;\frac{5}{3}\right]\{2\}\cup\{3\}'
    normalized = re.sub(r'\\displaystyle|\$|\\[()[\]]|\s+', '', text)
    if number == '19.26' and normalized == expected:
        return text.replace(r'\right]\{2\}', r'\right] \cup\{2\}')
    return text


def clean_ege_text(text):
    return wrap_ege_numbers(strip_ege_noise(text))


def split_line_subitems(text):
    """Три явные метки в начале строки надёжнее OCR-скобок в общем условии."""
    markers = list(re.finditer(r'(?m)^([aабв])\)\s*', text))
    labels = [('а' if m[1] == 'a' else m[1]) for m in markers]
    if labels != ['а', 'б', 'в']:
        return text, []
    rows = []
    for index, match in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        value = text[match.end():end].rstrip().removesuffix(r'\\').rstrip()
        rows.append({'label': labels[index], 'text_latex': value,
                     'author_answer_latex': '', 'author_solution_latex': ''})
    return text[:markers[0].start()].rstrip().removesuffix(r'\\').rstrip(), rows


def clean_ege_rows(rows):
    """Меняет только тексты, сохраняя ключи, метки, рисунки и статусы."""
    changed = []
    for row in rows:
        fields = []
        if not row.get('subitems'):
            parent, items = split_line_subitems(row['text_latex'])
            if items:
                from types import SimpleNamespace
                from .textbook_parser import redistribute_glued_subitem_answers
                task = SimpleNamespace(text_latex=parent, subitems=items,
                                       author_answer_latex=row.get('author_answer_latex', ''),
                                       author_solution_latex=row.get('author_solution_latex', ''))
                redistribute_glued_subitem_answers(task)
                row['text_latex'], row['subitems'] = parent, task.subitems
                row['author_answer_latex'] = task.author_answer_latex
                row['author_solution_latex'] = task.author_solution_latex
                fields.append({'field': 'subitems', 'reason': 'Восстановлены буквенные подпункты'})
        subs = row.get('subitems', [])
        if (row['external_id'].split('.')[0] in {'15', '18'}
                and [s.get('label') for s in subs] == ['а', 'б']
                and re.search(r'\bДокажите\b', subs[0]['text_latex'])
                and row.get('author_answer_latex')
                and not any(s.get('author_answer_latex') for s in subs)):
            answer = row['author_answer_latex']
            subs[1]['author_answer_latex'] = answer
            row['author_answer_latex'] = ''
            fields.append({'part': 0, 'field': 'author_answer_latex',
                           'before': answer, 'after': '', 'moved_to': 'б'})
        if row['external_id'] == PDF_FIGURE_ID and not row.get('images'):
            row['images'] = [PDF_FIGURE_STEM]
            row['text_latex'] += '\n\n' + r'\taskpic{1}'
            fields.append({'field': 'images', 'before': [], 'after': row['images']})
        for part_index, part in enumerate([row, *row.get('subitems', [])]):
            for key in ('text_latex', 'author_answer_latex', 'author_solution_latex'):
                before = part.get(key, '')
                after = clean_ege_text(fix_approved_answer(row['external_id'], before)
                                           if key == 'author_answer_latex' else before)
                if before != after:
                    part[key] = after
                    fields.append({'part': part_index, 'field': key,
                                   'before': before, 'after': after})
        if fields:
            changed.append({'id': row['external_id'], 'changes': fields})
    return changed


PDF_FIGURE_ID = '3.10.3'
PDF_FIGURE_STEM = 'ege-3-10-3'
PDF_FIGURE_PAGE = 241
PDF_FIGURE_CLIP = [402, 520, 521, 607]
PDF_SHA256 = '1e0b2ddcb9117cc7463ec2017e029148e7ce375687173873c389cfa6022e0773'


def clean_ege_drafts(tasks):
    """Тот же проход для объектов парсера; патчи источника уже применены."""
    counts = {'changed_fields': 0, 'restored_figures': []}
    for task in tasks:
        if not task.subitems:
            parent, items = split_line_subitems(task.text_latex)
            if items:
                from .textbook_parser import SubitemDraft, redistribute_glued_subitem_answers
                task.text_latex = parent
                task.subitems = [SubitemDraft(**item) for item in items]
                redistribute_glued_subitem_answers(task)
        for part in [task, *task.subitems]:
            for field in ('text_latex', 'author_answer_latex', 'author_solution_latex'):
                before = getattr(part, field, '')
                after = clean_ege_text(fix_approved_answer(task.external_id, before)
                                       if field == 'author_answer_latex' else before)
                if before != after:
                    setattr(part, field, after)
                    counts['changed_fields'] += 1
        if task.external_id == PDF_FIGURE_ID and not task.images:
            task.images = [PDF_FIGURE_STEM]
            task.text_latex += '\n\n' + r'\taskpic{1}'
            counts['restored_figures'].append(task.external_id)
    return counts

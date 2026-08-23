"""Импорт .tex-листка в формате пакета egor / egormath.

Разбирает документ на последовательность элементов (рубрики, задачи,
тексты) и шапку \\bighead. Задачи дедуплицируются по нормализованному
тексту условия: совпавшие переиспользуются из базы, новые создаются.
"""

import re

from problems.latex_utils import split_items
from problems.models import Task, TaskSubitem

from .models import Worksheet, WorksheetItem


class TexImportError(ValueError):
    pass


# --- Низкоуровневое чтение аргументов ---

def _skip_space(text, pos):
    """Пропускает пробелы и строчные комментарии (% до конца строки)."""
    n = len(text)
    while pos < n:
        c = text[pos]
        if c in ' \t\r\n':
            pos += 1
        elif c == '%':
            while pos < n and text[pos] != '\n':
                pos += 1
        else:
            break
    return pos


def _read_group(text, pos, open_ch, close_ch):
    """Читает сбалансированную группу {…} или […] начиная с open_ch.

    Возвращает (содержимое, позиция после close_ch) либо (None, pos),
    если группа не начинается в этой позиции.
    """
    pos = _skip_space(text, pos)
    if pos >= len(text) or text[pos] != open_ch:
        return None, pos
    brace = 0        # вложенность {…}
    bracket = 0      # вложенность […] на нулевой глубине скобок
    i = pos + 1
    start = i
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            brace += 1
        elif c == '}':
            if brace == 0 and close_ch == '}':
                return text[start:i], i + 1
            brace -= 1
        elif brace == 0 and close_ch == ']':
            if c == '[':
                bracket += 1
            elif c == ']':
                if bracket == 0:
                    return text[start:i], i + 1
                bracket -= 1
        i += 1
    raise TexImportError(
        f'Незакрытая группа {open_ch}…{close_ch} (позиция {pos}).')


def _unwrap_braces(text):
    """Снимает защитные внешние скобки: '[{…}]' экспортируется ради ']'."""
    t = text.strip()
    if len(t) < 2 or t[0] != '{' or t[-1] != '}':
        return t
    depth = 0
    i = 0
    n = len(t)
    while i < n:
        c = t[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and i != n - 1:
                return t  # первая группа закрывается раньше конца строки
        i += 1
    return t[1:-1]


def _read_args(text, pos, required, optional):
    """Читает required групп {…} и до optional групп […]."""
    args = []
    for _ in range(required):
        value, pos = _read_group(text, pos, '{', '}')
        if value is None:
            raise TexImportError(
                f'Ожидался обязательный аргумент {{…}} (позиция {pos}).')
        args.append(value)
    opts = []
    for _ in range(optional):
        value, new_pos = _read_group(text, pos, '[', ']')
        if value is None:
            break
        opts.append(_unwrap_braces(value))
        pos = new_pos
    return args, opts, pos


# --- Разбор документа ---

_COMMAND_RE = re.compile(
    r'\\(bighead|rubr|taskans|task|plaintext)\b')

_UNESCAPE = [
    (r'\&', '&'), (r'\%', '%'), (r'\$', '$'), (r'\#', '#'), (r'\_', '_'),
    (r'\{', '{'), (r'\}', '}'),
    (r'\textbackslash{}', '\\'),
    (r'\textasciitilde{}', '~'), (r'\textasciicircum{}', '^'),
]


def _unescape(text):
    """Обратное escape_latex для «обычных» полей шапки."""
    for src, dst in _UNESCAPE:
        text = text.replace(src, dst)
    return text.strip()


def _clean(text):
    """Причёсывает содержимое аргумента: убирает защитные %-переносы."""
    return re.sub(r'%\s*\n', '\n', text).strip()


# Графика в тексте задачи: \includegraphics[...]{файл} или \taskpic[...]{файл}
_GRAPHIC_RE = re.compile(
    r'\\(?:includegraphics|taskpic)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}')


def _extract_graphics(text, names):
    """Заменяет графику на ссылки \\taskpic{K} (K — номер внутри задачи).

    Имена файлов накапливаются в names; повторная ссылка на тот же файл
    получает тот же номер. Сами файлы при импорте не переносятся —
    их догружают на странице задачи (двухшаговый импорт)."""
    def repl(match):
        name = match.group(1).strip()
        if not name:
            return ''
        if name not in names:
            names.append(name)
        return '\\taskpic{%d}' % (names.index(name) + 1)
    return _GRAPHIC_RE.sub(repl, text)


def normalize_task_text(text):
    """Нормализация условия для дедупликации: пробелы и %-переносы."""
    return re.sub(r'\s+', ' ', _clean(text)).strip()


def parse_tex(source):
    """Разбирает .tex-документ.

    Возвращает dict:
      header: {title, left, right, subtitle}
      elements: список
        ('rubric', {'rubric', 'note'})
        ('task', {'stars', 'columns', 'text', 'subitems', 'answer',
                  'solution'})
        ('text', {'text'})
    """
    body = source
    m = re.search(r'\\begin\{document\}', source)
    if m:
        body = source[m.end():]
        m_end = re.search(r'\\end\{document\}', body)
        if m_end:
            body = body[:m_end.start()]

    header = {'title': '', 'left': '', 'right': '', 'subtitle': ''}
    elements = []
    pos = 0
    while True:
        m = _COMMAND_RE.search(body, pos)
        if m is None:
            break
        # Пропускаем закомментированные команды
        line_start = body.rfind('\n', 0, m.start()) + 1
        if '%' in body[line_start:m.start()].replace('\\%', ''):
            pos = m.end()
            continue
        name = m.group(1)
        pos = m.end()
        if name == 'bighead':
            args, opts, pos = _read_args(body, pos, required=3, optional=1)
            header = {
                'title': _unescape(args[0]),
                'left': _unescape(args[1]),
                'right': _unescape(args[2]),
                'subtitle': _unescape(opts[0]) if opts else '',
            }
        elif name == 'rubr':
            args, opts, pos = _read_args(body, pos, required=1, optional=1)
            elements.append(('rubric', {
                'rubric': _clean(args[0]),
                'note': _clean(opts[0]) if opts else '',
            }))
        elif name in ('task', 'taskans'):
            args, opts, pos = _read_args(body, pos, required=3, optional=3)
            try:
                stars = max(0, min(3, int(args[0].strip() or 0)))
            except ValueError:
                stars = 0
            try:
                columns = max(0, int(args[1].strip() or 0))
            except ValueError:
                columns = 0
            images = []
            text = _extract_graphics(_clean(args[2]), images)
            subitems = [
                _extract_graphics(chunk, images)
                for chunk in (split_items(_clean(opts[0])) if opts else [])
            ]
            elements.append(('task', {
                'stars': stars,
                'columns': columns,
                'text': text,
                'subitems': subitems,
                'answer': _clean(opts[1]) if len(opts) > 1 else '',
                'solution': _clean(opts[2]) if len(opts) > 2 else '',
                'images': images,
            }))
        elif name == 'plaintext':
            args, _, pos = _read_args(body, pos, required=1, optional=0)
            elements.append(('text', {'text': _clean(args[0])}))
    if not elements:
        raise TexImportError(
            'В документе не найдено ни одной команды \\task, \\rubr '
            'или \\plaintext.')
    return {'header': header, 'elements': elements}


# --- Дедупликация и создание ---

def _task_signature(text, subitems=()):
    """Ключ дедупликации: нормализованное условие + подпункты по порядку.

    Основное условие часто совпадает («Решите уравнение:» и т.п.),
    поэтому задачи с разными подпунктами — разные задачи.
    """
    return (normalize_task_text(text),
            tuple(s for s in (normalize_task_text(x) for x in subitems)
                  if s))


def _known_signatures():
    """Сигнатуры всех задач каталога: {(условие, подпункты): pk}."""
    subs = {}
    for task_id, sub_text in (TaskSubitem.objects
                              .filter(task__variant_of__isnull=True)
                              .order_by('task_id', 'order', 'id')
                              .values_list('task_id', 'text_latex')):
        subs.setdefault(task_id, []).append(sub_text)
    known = {}
    for pk, text in (Task.objects.filter(variant_of__isnull=True)
                     .values_list('pk', 'text_latex')):
        known.setdefault(_task_signature(text, subs.get(pk, ())), pk)
    return known


def match_existing_tasks(parsed):
    """Для каждой задачи ищет совпадение в базе по условию и подпунктам.

    Возвращает список той же длины, что elements: pk задачи или None
    (None и для нетасковых элементов).
    """
    known = _known_signatures()
    matches = []
    for kind, data in parsed['elements']:
        if kind != 'task':
            matches.append(None)
            continue
        matches.append(
            known.get(_task_signature(data['text'], data['subitems'])))
    return matches


def find_existing_task(text, subitems=()):
    """pk задачи каталога с тем же условием и подпунктами или None.

    Та же проверка, что при импорте, — используется и при ручном создании
    задачи, чтобы не плодить дубли под разными ID.
    """
    return _known_signatures().get(_task_signature(text, subitems))


def create_worksheet(parsed, owner, title='', overrides=None):
    """Создаёт листок с элементами; новые задачи сохраняются в базу.

    overrides — назначения из предпросмотра по индексу элемента:
    {'grade_level', 'topic_id', 'stars', 'answer', 'solution',
     'subitem_answers', 'subitem_solutions', 'skip'}.
    Класс/тема/звёзды применяются только к новым задачам; ответы и решения
    (в т.ч. по подпунктам) обновляются и у найденных в базе (горячее
    редактирование при импорте). skip — строка «удалена из импорта».

    Возвращает (worksheet, missing_images): файлы картинок при импорте
    не переносятся, missing_images — список {'task': Task, 'files': […]}
    для догрузки на страницах задач (двухшаговый импорт графики).
    """
    header = parsed['header']
    matches = match_existing_tasks(parsed)
    overrides = overrides or {}
    worksheet = Worksheet.objects.create(
        title=title or header['title'] or 'Импортированный листок',
        grade_label=header['left'],
        author_name=header['right'],
        subtitle=header['subtitle'],
        owner=owner,
    )
    missing_images = []
    for i, (kind, data) in enumerate(parsed['elements']):
        order = (i + 1) * 10
        if kind == 'rubric':
            WorksheetItem.objects.create(
                worksheet=worksheet, order=order,
                rubric=data['rubric'], rubric_note=data['note'])
        elif kind == 'text':
            WorksheetItem.objects.create(
                worksheet=worksheet, order=order, text_latex=data['text'])
        else:
            extra = overrides.get(i, {})
            if extra.get('skip'):
                continue
            sub_answers = extra.get('subitem_answers', {})
            sub_solutions = extra.get('subitem_solutions', {})
            task_pk = matches[i]
            if task_pk is not None:
                task = Task.objects.get(pk=task_pk)
                # Ответы/решения можно горячо править и у существующих
                # задач (класс/тему/звёзды существующих не трогаем)
                updates = []
                if 'answer' in extra and extra['answer'] != task.answer_latex:
                    task.answer_latex = extra['answer']
                    updates.append('answer_latex')
                if ('solution' in extra
                        and extra['solution'] != task.solution_latex):
                    task.solution_latex = extra['solution']
                    updates.append('solution_latex')
                if updates:
                    task.save(update_fields=updates)
                if sub_answers or sub_solutions:
                    for j, sub in enumerate(task.subitems.all()):
                        sub_updates = []
                        if (j in sub_answers
                                and sub_answers[j] != sub.answer_latex):
                            sub.answer_latex = sub_answers[j]
                            sub_updates.append('answer_latex')
                        if (j in sub_solutions
                                and sub_solutions[j] != sub.solution_latex):
                            sub.solution_latex = sub_solutions[j]
                            sub_updates.append('solution_latex')
                        if sub_updates:
                            sub.save(update_fields=sub_updates)
            else:
                task = Task.objects.create(
                    text_latex=data['text'],
                    stars=extra.get('stars', data['stars']),
                    columns=data['columns'],
                    answer_latex=extra.get('answer', data['answer']),
                    solution_latex=extra.get('solution', data['solution']),
                    grade_level=extra.get('grade_level'),
                    created_by=owner)
                if extra.get('topic_id'):
                    task.topics.add(extra['topic_id'])
                for j, chunk in enumerate(data['subitems']):
                    TaskSubitem.objects.create(
                        task=task, order=(j + 1) * 10, text_latex=chunk,
                        answer_latex=sub_answers.get(j, ''),
                        solution_latex=sub_solutions.get(j, ''))
                if data.get('images'):
                    missing_images.append(
                        {'task': task, 'files': data['images']})
            WorksheetItem.objects.create(
                worksheet=worksheet, task=task, order=order)
    return worksheet, missing_images

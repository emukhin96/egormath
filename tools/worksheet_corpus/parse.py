"""Разбор tex-листка в нейтральный черновик."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .detect import detect_dialect, grade_from_path, read_tex
from .latex_scan import (
    TITLE_PROPOSED_WARNING, clean_arg, clean_title_text, document_body,
    extract_choice_envs, extract_graphics, strip_answer_grids,
    strip_layout_space, strip_subitem_punct, extract_title_guess,
    find_env_spans,
    is_headerish_title, read_command_args, split_alpha_subitems, split_items,
    split_top_items, title_from_filename)
from .paths import assets_dir
from .store import draft_id, save_draft
from .subitems import ensure_subitem_fields, maybe_split_element

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.pdf')


class ParseError(ValueError):
    pass


def empty_header():
    return {'title': '', 'left': '', 'right': '', 'subtitle': ''}


def make_draft(*, rel_path, source_path, dialect, grade, header, elements,
               warnings=None, verdict='include'):
    header = dict(header or empty_header())
    title = clean_title_text(header.get('title') or '')
    title_origin = 'header'
    if not title or is_headerish_title(title):
        title = title_from_filename(rel_path) or title
        title_origin = 'filename' if title else ''
    header['title'] = title
    for key in ('left', 'right', 'subtitle'):
        header[key] = clean_title_text(header.get(key) or '')
    return {
        'schema_version': 1,
        'id': draft_id(rel_path),
        'source_path': str(source_path),
        'rel_path': rel_path,
        'dialect': dialect,
        'grade': grade,
        'title': title,
        'title_origin': title_origin,
        'header': header,
        'status': 'needs_review',
        'verdict': verdict,
        'warnings': list(warnings or []),
        'topic_code': '',
        'topic_codes': [],
        'topic_ids': [],
        'topic_candidates': [],
        'exam_item_codes': [],
        'elements': elements,
    }


def preprocess_mathneo(source: str) -> str:
    """\\starredtask / \\columned / \\hwork → обычные команды egor."""
    text = source
    text = re.sub(r'\\hwork\b', r'\\rubr{Домашняя работа}', text)
    text = re.sub(r'\\hw\b', r'\\rubr{Домашнее задание}', text)
    out = []
    pos = 0
    command_re = re.compile(r'\\(starredtask|columned)\b')
    while True:
        match = command_re.search(text, pos)
        if not match:
            out.append(text[pos:])
            break
        # закомментированная команда
        line_start = text.rfind('\n', 0, match.start()) + 1
        if '%' in text[line_start:match.start()].replace(r'\%', ''):
            out.append(text[pos:match.end()])
            pos = match.end()
            continue
        out.append(text[pos:match.start()])
        name = match.group(1)
        cur = match.end()
        if name == 'starredtask':
            parsed, cur = read_command_args(text, cur, required=2)
            if parsed is None:
                out.append(text[match.start():match.end()])
                pos = match.end()
                continue
            stars, body = parsed[0]
            replacement = _expand_starredtask(stars, body)
            out.append(replacement)
            pos = cur
        else:
            parsed, cur = read_command_args(text, cur, required=3)
            if parsed is None:
                out.append(text[match.start():match.end()])
                pos = match.end()
                continue
            cols, stem, items = parsed[0]
            out.append(_expand_columned_as_task(cols, stem, items))
            pos = cur
    return ''.join(out)


def _expand_columned_as_task(cols, stem, items):
    return '\\task{0}{%s}{%s}[%s]' % (
        cols.strip() or '0', stem, items)


def _expand_starredtask(stars, body):
    body = body.strip()
    col_m = re.match(r'\\columned\b', body)
    if col_m:
        parsed, _ = read_command_args(body, col_m.end(), required=3)
        if parsed is not None:
            cols, stem, items = parsed[0]
            return '\\task{%s}{%s}{%s}[%s]' % (
                stars.strip() or '0', cols.strip() or '0', stem, items)
    return '\\task{%s}{0}{%s}' % (stars.strip() or '0', body)


def parse_egor_source(source: str) -> dict:
    from worksheets.import_tex import TexImportError, parse_tex
    prepared = preprocess_mathneo(source)
    last_error = None
    for candidate in (prepared, source):
        try:
            parsed = parse_tex(candidate)
            break
        except TexImportError as exc:
            last_error = exc
            parsed = None
    if parsed is None:
        try:
            return parse_flexible_tasks(source)
        except ParseError as exc:
            raise ParseError(str(last_error or exc)) from last_error
    elements = []
    warnings = []
    for kind, data in parsed['elements']:
        if kind == 'rubric':
            elements.append({
                'kind': 'rubric',
                'rubric': data.get('rubric', ''),
                'note': data.get('note', ''),
            })
        elif kind == 'text':
            elements.append({
                'kind': 'text',
                'text': data.get('text', ''),
                'style': data.get('style', 'plain'),
            })
        else:
            images = list(data.get('images') or [])
            task = _split_inline_alpha({
                'kind': 'task',
                'text': data.get('text', ''),
                'subitems': list(data.get('subitems') or []),
                'stars': data.get('stars', 0),
                'columns': data.get('columns', 0),
                'answer': data.get('answer', ''),
                'solution': data.get('solution', ''),
                'subitem_answers': list(data.get('subitem_answers') or []),
                'subitem_solutions': list(data.get('subitem_solutions') or []),
                'images': images,
                'warnings': [],
                'status': 'needs_review',
                'skip': False,
            })
            ensure_subitem_fields(task)
            maybe_split_element(task)
            elements.append(task)
    if not any(el['kind'] == 'task' for el in elements):
        try:
            return parse_flexible_tasks(source)
        except ParseError:
            warnings.append('В egor-документе нет элементов')
    return {
        'header': parsed.get('header') or empty_header(),
        'elements': elements,
        'warnings': warnings,
    }


def parse_chem_math(source: str) -> dict:
    body = document_body(source)
    header = extract_title_guess(source, body)
    elements = []
    warnings = []
    pos = 0
    task_re = re.compile(r'\\task\b')
    while True:
        match = task_re.search(body, pos)
        if not match:
            break
        line_start = body.rfind('\n', 0, match.start()) + 1
        if '%' in body[line_start:match.start()].replace(r'\%', ''):
            pos = match.end()
            continue
        parsed, pos = read_command_args(body, match.end(), required=2)
        if parsed is None:
            warnings.append('Не удалось прочитать \\task (chem)')
            pos = match.end()
            continue
        text, answer = parsed[0]
        elements.append(_task_from_block(text, answer=clean_arg(answer)))
    if not elements:
        raise ParseError('В chem-math файле нет \\task')
    return {'header': header, 'elements': elements, 'warnings': warnings}


def parse_enumerate_source(source: str) -> dict:
    body = document_body(source)
    header = extract_title_guess(source, body)
    elements = []
    warnings = []
    spans = find_env_spans(body, 'enumerate')
    if not spans:
        spans = find_env_spans(body, 'enumerate*')
    if not spans:
        raise ParseError('Нет окружения enumerate')
    top_spans = []
    for start, end, inner in spans:
        nested = any(
            start > o_start and end < o_end
            for o_start, o_end, _ in spans)
        if nested:
            continue
        top_spans.append((start, end, inner))
    last_end = 0
    for start, end, inner in top_spans:
        between = body[last_end:start]
        _append_section_rubrics(between, elements)
        batch = []
        extras_after = []
        for raw in split_top_items(inner):
            task, extras = _task_and_sides(raw)
            batch.append(task)
            extras_after.append(extras)
        _rewire_list_images(batch)
        for task, extras in zip(batch, extras_after):
            elements.append(task)
            elements.extend(extras)
        last_end = end
    if not any(el['kind'] == 'task' for el in elements):
        try:
            return parse_flexible_tasks(source)
        except ParseError:
            raise ParseError('В enumerate нет пунктов-задач')
    return {'header': header, 'elements': elements, 'warnings': warnings}


def parse_zad_source(source: str) -> dict:
    body = document_body(source)
    header = extract_title_guess(source, body)
    elements = []
    warnings = []
    _append_section_rubrics(body[:body.find('\\zad')] if '\\zad' in body else '',
                            elements)
    parts = re.split(r'\\zad\b', body)
    batch = []
    extras_after = []
    for chunk in parts[1:]:
        # до следующего структурного маркера
        cut = re.search(
            r'\\(?:zad|subsection|section|begin\{document\}|end\{document\})\b',
            chunk)
        text = chunk[:cut.start()] if cut else chunk
        task, extras = _task_and_sides(text)
        batch.append(task)
        extras_after.append(extras)
    _rewire_list_images(batch)
    for task, extras in zip(batch, extras_after):
        elements.append(task)
        elements.extend(extras)
    if not any(el['kind'] == 'task' for el in elements):
        raise ParseError('Нет команд \\zad')
    return {'header': header, 'elements': elements, 'warnings': warnings}


def parse_exam_source(source: str) -> dict:
    body = document_body(source)
    header = extract_title_guess(source, body)
    elements = []
    warnings = ['Класс exam: границы \\question стоит проверить вручную']
    parts = re.split(r'\\question\b', body)
    for chunk in parts[1:]:
        cut = re.search(
            r'\\(?:question\b|end\{questions\}|end\{document\})',
            chunk)
        text = chunk[:cut.start()] if cut else chunk
        text = re.sub(r'\\begin\{solution\}[\s\S]*?\\end\{solution\}', '', text)
        text, choices = extract_choice_envs(text)
        part_chunks = re.split(r'\\part\b', text)
        if len(part_chunks) > 1:
            stem = part_chunks[0]
            subparts = [clean_arg(p) for p in part_chunks[1:] if clean_arg(p)]
            element = _task_from_block(stem)
            if subparts:
                element['subitems'] = subparts + list(element.get('subitems') or [])
        else:
            element = _task_from_block(text)
        if choices:
            element['choices'] = choices
        elements.append(element)
    if not any(el['kind'] == 'task' for el in elements):
        raise ParseError('В exam-файле нет \\question')
    return {'header': header, 'elements': elements, 'warnings': warnings}


def _looks_like_count(value):
    value = (value or '').strip()
    return value == '' or bool(re.fullmatch(r'\d{1,2}', value))


def parse_flexible_tasks(source: str) -> dict:
    """\\task / \\dtask с 1–3 обязательными аргументами (math, chem, смешанные)."""
    body = document_body(source)
    header = extract_title_guess(source, body)
    elements = []
    warnings = []
    pos = 0
    task_re = re.compile(r'\\(d?task)\b')
    while True:
        match = task_re.search(body, pos)
        if not match:
            break
        line_start = body.rfind('\n', 0, match.start()) + 1
        if '%' in body[line_start:match.start()].replace(r'\%', ''):
            pos = match.end()
            continue
        start = match.end()
        triple, pos3 = read_command_args(body, start, required=3, optional=3)
        if (triple is not None
                and _looks_like_count(triple[0][0])
                and _looks_like_count(triple[0][1])):
            args, opts = triple
            try:
                stars = max(0, min(3, int((args[0] or '0').strip() or 0)))
            except ValueError:
                stars = 0
            try:
                columns = max(0, int((args[1] or '0').strip() or 0))
            except ValueError:
                columns = 0
            element = _task_from_block(
                args[2],
                answer=clean_arg(opts[1]) if len(opts) > 1 else '')
            if opts and opts[0]:
                inner = opts[0]
                if r'\item' in inner:
                    element['subitems'] = [
                        extract_graphics(chunk, element['images'])
                        for chunk in split_top_items(inner) or split_items(inner)
                    ]
            if len(opts) > 2:
                element['solution'] = clean_arg(opts[2])
            element['stars'] = stars
            element['columns'] = columns or element['columns']
            elements.append(element)
            pos = pos3
            continue
        pair, pos2 = read_command_args(body, start, required=2, optional=1)
        if pair is not None:
            text, answer = pair[0]
            elements.append(_task_from_block(text, answer=clean_arg(answer)))
            pos = pos2
            continue
        single, pos1 = read_command_args(body, start, required=1, optional=2)
        if single is not None:
            text = single[0][0]
            opts = single[1]
            answer = ''
            if opts and r'\item' in opts[0]:
                element = _task_from_block(text)
                element['subitems'] = [
                    extract_graphics(chunk, element['images'])
                    for chunk in split_top_items(opts[0]) or split_items(opts[0])
                ]
                if len(opts) > 1:
                    element['answer'] = clean_arg(opts[1])
                elements.append(element)
            else:
                if opts:
                    answer = clean_arg(opts[0])
                elements.append(_task_from_block(text, answer=answer))
            pos = pos1
            continue
        warnings.append('Не удалось прочитать \\task')
        pos = match.end()
    if not any(el['kind'] == 'task' for el in elements):
        raise ParseError('Нет команд \\task')
    return {'header': header, 'elements': elements, 'warnings': warnings}


def _append_unique(elements, el):
    if not el:
        return
    if el.get('kind') == 'rubric' and elements:
        prev = elements[-1]
        if (prev.get('kind') == 'rubric'
                and prev.get('rubric') == el.get('rubric')):
            return
    elements.append(el)


def _insert_as_element(blob, style='memo'):
    raw = (blob or '').strip()
    if not raw:
        return None
    title = clean_title_text(raw)
    if raw.startswith('§') or (title or '').startswith('§'):
        if title:
            return {'kind': 'rubric', 'rubric': title, 'note': ''}
        return None
    return {'kind': 'text', 'text': raw[:800], 'style': style}


def _append_section_rubrics(text, elements):
    if not text or not text.strip():
        return
    for match in re.finditer(
            r'\\(?:subsection|section)\*?\{([^{}]+)\}', text):
        title = re.sub(r'\s+', ' ', match.group(1)).strip()
        if title:
            _append_unique(elements, {
                'kind': 'rubric', 'rubric': title, 'note': '',
            })
    for match in re.finditer(
            r'\\begin\{(?:example|myquote|chap|tcolorbox)\}([\s\S]*?)\\end\{(?:example|myquote|chap|tcolorbox)\}',
            text):
        blob = _plain_env_text(match.group(1))
        _append_unique(elements, _insert_as_element(blob, 'memo'))


SIDE_ENVS = (
    ('example', 'memo'),
    ('myquote', 'memo'),
    ('chap', 'plain'),
)


def _plain_env_text(inner):
    blob = re.sub(r'\\textbf\{([^{}]*)\}', r'\1', inner)
    blob = re.sub(r'\\textit\{([^{}]*)\}', r'\1', blob)
    blob = re.sub(r'\\parn\b', '\n\n', blob)
    blob = re.sub(r'\\(?:noindent|sf|footnotesize|par)\b', ' ', blob)
    blob = re.sub(r'\\begin\{(?:singlespace|myquote|tcolorbox)\}', ' ', blob)
    blob = re.sub(r'\\end\{(?:singlespace|myquote|tcolorbox)\}', ' ', blob)
    blob = re.sub(r'[ \t]+\n', '\n', blob)
    blob = re.sub(r'\n{3,}', '\n\n', blob)
    blob = re.sub(r'[ \t]{2,}', ' ', blob).strip()
    return blob


def _extract_side_envs(raw):
    """example / myquote — это вставки \\plaintext/\\ruletext, не часть задачи."""
    extras = []
    text = raw or ''
    for env, style in SIDE_ENVS:
        while True:
            spans = find_env_spans(text, env)
            if not spans:
                break
            start, end, inner = spans[0]
            blob = _plain_env_text(inner)
            el = _insert_as_element(blob, style)
            if el:
                extras.append(el)
            text = text[:start] + text[end:]
    return text, extras


CAPTION_TASK_RE = re.compile(r'(?i)к\s+задаче\s+(\d+)')
TASKPIC_RE = re.compile(r'\\taskpic\{\d+\}')
MAKEBOX_CAPTION_RE = re.compile(
    r'\\makebox(?:\s*\[[^\]]*\]){0,2}\s*\{[^{}]*к\s+задаче[^{}]*\}',
    re.I)
SETCOUNTER_RE = re.compile(r'(?m)^\s*%?\\setcounter\b[^\n]*\n?')


def _strip_caption_figures(text):
    """Убирает блок «К задаче N» + рисунки из условия."""
    cleaned = text or ''
    for start, end, inner in reversed(find_env_spans(cleaned, 'center')):
        if CAPTION_TASK_RE.search(inner) and (
                TASKPIC_RE.search(inner) or r'\includegraphics' in inner):
            cleaned = cleaned[:start] + cleaned[end:]
    cleaned = MAKEBOX_CAPTION_RE.sub('', cleaned)
    cleaned = SETCOUNTER_RE.sub('', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def _task_search_blob(task):
    parts = [task.get('text') or '']
    parts.extend(task.get('subitems') or [])
    return '\n'.join(parts)


def _file_image_names(names):
    return [name for name in (names or [])
            if name and not re.fullmatch(r'\d+', Path(name).name)]


def _apply_stripped_parts(task, parts):
    task['text'] = parts[0] if parts else ''
    n_sub = len(task.get('subitems') or [])
    if n_sub:
        task['subitems'] = parts[1:1 + n_sub]


def _rewire_list_images(tasks):
    """Рисунок с подписью «К задаче N» относится к N-му пункту этого списка."""
    pending = []
    for task in tasks:
        blob = _task_search_blob(task)
        caps = [int(m.group(1)) for m in CAPTION_TASK_RE.finditer(blob)]
        imgs = _file_image_names(task.get('images'))
        if not caps:
            task['images'] = imgs
            continue
        pairs = list(zip(caps, imgs))
        parts = [task.get('text') or ''] + list(task.get('subitems') or [])
        _apply_stripped_parts(task, [_strip_caption_figures(p) for p in parts])
        paired = {img for _, img in pairs}
        task['images'] = [name for name in imgs if name not in paired]
        pending.extend(pairs)
    for num, img in pending:
        idx = num - 1
        if 0 <= idx < len(tasks):
            dest = tasks[idx].setdefault('images', [])
            if img not in dest:
                dest.append(img)


def _split_inline_alpha(task):
    """В \\task без \\item режет «а) … б) …» из условия, как гибкий парсер."""
    if task.get('subitems'):
        return task
    stem, parts = split_alpha_subitems(task.get('text') or '')
    if parts:
        task['text'] = stem or ' '
        task['subitems'] = parts
    return task


def _task_and_sides(raw, answer=''):
    body, extras = _extract_side_envs(raw)
    return _task_from_block(body, answer=answer), extras


def _task_from_block(raw, answer=''):
    images = []
    text = extract_graphics(clean_arg(raw), images)
    text = strip_answer_grids(text)
    text = _strip_outer_lists(text)
    nested = (
        find_env_spans(text, 'enumerate*')
        or find_env_spans(text, 'enumerate')
        or find_env_spans(text, 'itemize')
    )
    subitems = []
    if nested:
        start, end, inner = nested[0]
        stem = (text[:start] + text[end:]).strip()
        subitems = [
            strip_subitem_punct(strip_layout_space(
                strip_answer_grids(extract_graphics(chunk, images))))
            for chunk in split_top_items(inner) or split_items(inner)
        ]
        text = stem
    else:
        stem, alpha = split_alpha_subitems(text)
        if alpha:
            text = stem
            subitems = [
                strip_subitem_punct(strip_layout_space(
                    strip_answer_grids(extract_graphics(chunk, images))))
                for chunk in alpha
            ]
    columns = 0
    if '\\begin{multicols}' in raw or r'{multicols}' in raw:
        m = re.search(r'\\begin\{multicols\}\{(\d+)\}', raw)
        if m:
            try:
                columns = int(m.group(1))
            except ValueError:
                columns = 0
    elif len(subitems) >= 4:
        columns = 2
    text = strip_layout_space(strip_answer_grids(text))
    answer = answer or ''
    task = {
        'kind': 'task',
        'text': text or ' ',
        'subitems': subitems,
        'choices': [],
        'stars': 0,
        'columns': columns,
        'answer': answer,
        'answer_origin': 'parsed' if answer.strip() else '',
        'solution': '',
        'subitem_answers': [],
        'subitem_solutions': [],
        'images': images,
        'warnings': [],
        'status': 'needs_review',
        'skip': False,
    }
    ensure_subitem_fields(task)
    maybe_split_element(task)
    return task


def _strip_outer_lists(text):
    text = text.strip()
    for env in ('enumerate*', 'enumerate', 'itemize'):
        prefix = '\\begin{%s}' % env
        suffix = '\\end{%s}' % env
        if text.startswith(prefix) and text.endswith(suffix):
            inner = text[len(prefix):-len(suffix)]
            inner = re.sub(r'^(\[[^\]]*\])', '', inner).strip()
            return inner
    return text


def _preserve_element_skips(draft, existing):
    old_els = existing.get('elements') or []
    new_els = draft.get('elements') or []
    for i, el in enumerate(new_els):
        if el.get('kind') != 'task' or i >= len(old_els):
            continue
        old = old_els[i]
        if old.get('kind') == 'task' and old.get('skip'):
            el['skip'] = True


def _preserve_element_answers(draft, existing):
    old_els = existing.get('elements') or []
    new_els = draft.get('elements') or []
    for i, el in enumerate(new_els):
        if el.get('kind') != 'task' or i >= len(old_els):
            continue
        old = old_els[i]
        if old.get('kind') != 'task':
            continue
        if not (el.get('answer') or '').strip() and (old.get('answer') or '').strip():
            el['answer'] = old['answer']
            if old.get('answer_origin'):
                el['answer_origin'] = old['answer_origin']
        if not (el.get('solution') or '').strip() and (old.get('solution') or '').strip():
            el['solution'] = old['solution']
        if old.get('subitem_answers'):
            el['subitem_answers'] = list(old['subitem_answers'])
        if old.get('subitem_solutions'):
            el['subitem_solutions'] = list(old['subitem_solutions'])
        if old.get('answer_origin') and not el.get('answer_origin'):
            el['answer_origin'] = old['answer_origin']
        ensure_subitem_fields(el)


def _preserve_review_fields(draft, existing):
    if not existing:
        return
    status = existing.get('status')
    if status in ('approved', 'skipped', 'imported', 'conflict'):
        draft['status'] = status
    if existing.get('topic_code') or existing.get('topic_codes') or existing.get('topic_ids'):
        draft['topic_code'] = existing.get('topic_code') or ''
        draft['topic_codes'] = list(existing.get('topic_codes') or [])
        draft['topic_ids'] = list(existing.get('topic_ids') or [])
        if draft['topic_code'] and draft['topic_code'] not in draft['topic_codes']:
            draft['topic_codes'] = [draft['topic_code']] + draft['topic_codes']
        draft['needs_topic_review'] = existing.get(
            'needs_topic_review', False)
        from .classify import _apply_topic_to_tasks
        _apply_topic_to_tasks(draft)
    if existing.get('exam_item_codes'):
        draft['exam_item_codes'] = existing['exam_item_codes']
    if existing.get('imported_worksheet_id'):
        draft['imported_worksheet_id'] = existing['imported_worksheet_id']
    if existing.get('title_origin') in ('proposed', 'manual'):
        draft['title_origin'] = existing['title_origin']
        draft['title'] = existing.get('title') or draft.get('title')
        header = dict(draft.get('header') or empty_header())
        header['title'] = draft['title']
        draft['header'] = header
        extra = [w for w in (existing.get('warnings') or [])
                 if w == TITLE_PROPOSED_WARNING]
        if extra:
            warns = list(draft.get('warnings') or [])
            for item in extra:
                if item not in warns:
                    warns.append(item)
            draft['warnings'] = warns
    _preserve_element_skips(draft, existing)
    _preserve_element_answers(draft, existing)


PARSERS = {
    'egor': parse_egor_source,
    'chem-math': parse_chem_math,
    'enumerate': parse_enumerate_source,
    'zad': parse_zad_source,
    'exam': parse_exam_source,
}


def resolve_images(source_dir: Path, names: list[str], draft_key: str):
    """Копирует найденные файлы в var/worksheets-import/assets/<id>/."""
    dest_root = assets_dir() / draft_key.replace('/', '__')
    resolved = []
    missing = []
    for name in names:
        raw = name.replace('\\', '/').strip()
        stem = Path(raw).name
        candidates = [source_dir / raw, source_dir / stem]
        found = None
        for cand in candidates:
            if cand.is_file():
                found = cand
                break
        if found is None:
            base = Path(stem).stem.lower()
            for extra in source_dir.iterdir() if source_dir.is_dir() else []:
                if extra.is_file() and extra.stem.lower() == base:
                    if extra.suffix.lower() in IMAGE_EXTS:
                        found = extra
                        break
        if found is None:
            missing.append(name)
            continue
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / found.name
        if not dest.exists() or dest.stat().st_size != found.stat().st_size:
            shutil.copy2(found, dest)
        resolved.append({
            'name': found.name,
            'source': str(found),
            'stored': str(dest),
        })
    return resolved, missing


def store_failed_draft(path: Path, *, rel_path: str, grade: int | None,
                       dialect: str, error) -> dict | None:
    """Черновик-заглушка, чтобы сломанный файл был виден на сверке."""
    from .store import load_draft
    key = draft_id(rel_path)
    existing = load_draft(key)
    if existing and existing.get('status') in ('approved', 'imported', 'skipped'):
        return existing
    source = read_tex(path)
    header = extract_title_guess(source)
    draft = make_draft(
        rel_path=rel_path,
        source_path=path,
        dialect=dialect,
        grade=grade_from_path(path, grade),
        header=header,
        elements=[],
        warnings=[f'Разбор не удался: {error}'],
        verdict='review',
    )
    _preserve_review_fields(draft, existing)
    save_draft(draft)
    return draft


def parse_file(path: Path, *, rel_path: str, grade: int | None,
               dialect: str | None = None) -> dict:
    source = read_tex(path)
    dialect = dialect or detect_dialect(source, path)
    parser = PARSERS.get(dialect)
    if parser is None:
        raise ParseError(f'Нет парсера для диалекта {dialect}')
    result = parser(source)
    header = result['header'] or empty_header()
    elements = result['elements']
    warnings = list(result.get('warnings') or [])
    key = draft_id(rel_path)
    all_names = []
    for el in elements:
        if el.get('kind') != 'task':
            continue
        el['images'] = _file_image_names(el.get('images'))
        for name in el.get('images') or []:
            if name not in all_names:
                all_names.append(name)
    resolved, missing = resolve_images(path.parent, all_names, key)
    by_stem = {Path(item['name']).stem.lower(): item for item in resolved}
    by_name = {item['name']: item for item in resolved}
    for el in elements:
        if el.get('kind') != 'task':
            continue
        stored = []
        for name in el.get('images') or []:
            item = by_name.get(Path(name).name) or by_stem.get(
                Path(name).stem.lower())
            if item:
                stored.append(item['stored'])
        el['image_files'] = stored
        el['image_names'] = [Path(p).name for p in stored]
    if missing:
        warnings.append('Не найдены рисунки: ' + ', '.join(missing))
    for el in elements:
        if el.get('kind') != 'task':
            continue
        el['text'] = strip_layout_space(el.get('text') or '')
        el['subitems'] = [
            strip_subitem_punct(strip_layout_space(s))
            for s in el.get('subitems') or []]
        el['choices'] = [
            strip_layout_space(s) for s in el.get('choices') or []]
    draft = make_draft(
        rel_path=rel_path,
        source_path=path,
        dialect=dialect,
        grade=grade_from_path(path, grade),
        header=header,
        elements=elements,
        warnings=warnings,
        verdict='review' if dialect == 'exam' else 'include',
    )
    if dialect == 'exam':
        draft['status'] = 'needs_review'
    from .classify import exam_codes_from_elements
    from .cleanup import clean_draft
    draft['exam_item_codes'] = exam_codes_from_elements(
        elements, draft.get('grade'))
    return clean_draft(draft)


def parse_and_store(path: Path, *, rel_path: str, grade: int | None,
                    dialect: str | None = None, force: bool = False) -> dict:
    from .store import load_draft
    existing = load_draft(draft_id(rel_path))
    if (existing and existing.get('status') in ('skipped', 'imported')
            and not force):
        return existing
    draft = parse_file(path, rel_path=rel_path, grade=grade, dialect=dialect)
    tag_codes = list(draft.get('exam_item_codes') or [])
    _preserve_review_fields(draft, existing)
    seen = set(draft.get('exam_item_codes') or [])
    merged = list(draft.get('exam_item_codes') or [])
    for code in tag_codes:
        if code not in seen:
            seen.add(code)
            merged.append(code)
    draft['exam_item_codes'] = merged
    from .emit import emit_egor_tex
    save_draft(draft)
    from .store import draft_tex_path
    draft_tex_path(draft['id']).parent.mkdir(parents=True, exist_ok=True)
    draft_tex_path(draft['id']).write_text(
        emit_egor_tex(draft), encoding='utf-8')
    return draft

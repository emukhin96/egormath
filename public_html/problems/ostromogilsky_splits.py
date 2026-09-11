"""Восстановление границ геометрических задач по независимому тексту PDF."""
import re
import unicodedata
from copy import deepcopy


def extract_pdf_task_contexts(pdf_path):
    """Возвращает порядок якорей и тексты геометрии без изменения источника."""
    import pymupdf
    with pymupdf.open(pdf_path) as doc:
        names = doc.resolve_names()
        keys = [key[6:] for key in names
                if re.fullmatch(r'task::(?:[1-9]\d*)\.\d+(?:\.\d+)?', key)]
        keys.sort(key=lambda key: (names['task::' + key]['page'],
                                   -names['task::' + key]['to'][1]))
        pages, result = {}, []
        for key in keys:
            page = names['task::' + key]['page']
            body = ''
            if key.startswith(('1.', '2.', '3.', '4.', '5.', '15.', '16.', '17.')):
                if page not in pages:
                    pages[page] = doc[page].get_text()
                text = pages[page]
                marker = re.search(r'(?:Задача|Аналог)\s+' + re.escape(key)
                                   + r'\.(?!\d)', text)
                if marker:
                    body = text[marker.end():].split('Ответ:', 1)[0]
                    body = re.split(r'(?:Задача|Аналог)\s+\d+\.', body, 1)[0]
                    body = re.sub(r'^(?:\s|Прототип|Аналоги|Ответ|DEMO|NEW|OLD|SIM)+', '', body)
                    body = unicodedata.normalize('NFKC', body)
                    body = re.sub(r'(?m)^[A-Z](?:\s+[A-Z])*\s*$', '', body)
                    body = re.sub(r'(?<=[а-я])-\n(?=[а-я])', '', body).strip()
            result.append({'id': key, 'page': page + 1, 'body': body})
        return result


def _canonical(text):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'\\taskpic\{\d+\}', '', text)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    text = text.replace('−', '-')
    return re.sub(r'[^a-zа-я0-9+=/\-]', '', text.lower())


def recover_geometry_splits(tasks, contexts, answers):
    """Разделяет склейку лишь при совпадении всех её фрагментов с PDF.

    Каждый фрагмент должен содержать ровно свой рисунок, причём страница
    OCR-рисунка должна совпасть с якорем соответствующей задачи в PDF.
    """
    from .ostromogilsky_parser import exam_item_code
    by_id = {task.external_id: task for task in tasks}
    replacements, recovered = {}, []
    for index, source in enumerate(contexts):
        key = source['id']
        if key not in by_id or not key.startswith(('15.', '16.', '17.')):
            continue
        following = []
        for candidate in contexts[index + 1:]:
            if candidate['id'] in by_id:
                break
            following.append(candidate)
        if not following:
            continue
        parent = by_id[key]
        sources = [source] + following
        if parent.subitems or len(parent.images) != len(sources):
            continue
        if any(row['id'].split('.')[0] != key.split('.')[0] for row in sources):
            continue
        fragments = re.split(r'(?<=\})\s*\n\s*\n(?=[А-Я])', parent.text_latex)
        if len(fragments) != len(sources):
            continue
        rows = []
        for number, (fragment, row, image) in enumerate(zip(fragments, sources, parent.images), 1):
            fragment = re.sub(r'\\begin\{tabular\}[^\n]*\s*(?:\\hline\s*)+\\end\{tabular\}\s*$', '', fragment).strip()
            fragment = fragment.replace(', a $', ', а $')
            image_page = re.search(r'-(\d{4})_', image)
            if (not row['body'] or _canonical(fragment) != _canonical(row['body'])
                    or re.findall(r'\\taskpic\{(\d+)\}', fragment) != [str(number)]
                    or not image_page or int(image_page.group(1)) != row['page']
                    or not answers.get(row['id'])):
                break
            draft = deepcopy(parent)
            draft.external_id = draft.source_number = row['id']
            draft.text_latex = re.sub(r'\\taskpic\{\d+\}', lambda match: r'\taskpic{1}', fragment)
            draft.images = [image]
            draft.author_answer_latex = answers[row['id']]
            # Ответ и решение родительской склейки не распространяются на соседа.
            draft.author_solution_latex = parent.author_solution_latex if number == 1 else ''
            draft.exam_item_codes = [exam_item_code(row['id'])]
            draft.tags = list(parent.tags) if number == 1 else []
            draft.warnings = list(parent.warnings) + ['Граница задачи восстановлена по тексту и странице PDF; требуется сверка']
            draft.confidence = min(draft.confidence, 0.9)
            rows.append(draft)
        if len(rows) == len(sources):
            replacements[key] = rows
            recovered.extend(row.external_id for row in rows[1:])
    return [row for task in tasks for row in replacements.get(task.external_id, [task])], recovered


def recover_practical_splits(tasks, contexts, answers):
    """Возвращает вопросы №1–5 из хвоста склейки, сохраняя общий текст.

    Общая часть берётся из соседнего самостоятельного вопроса того же
    варианта. Каждый отделяемый вопрос дословно сверяется с текстом PDF.
    """
    from .ostromogilsky_parser import exam_item_code
    by_id = {task.external_id: task for task in tasks}
    replacements, recovered = {}, []
    for index, source in enumerate(contexts):
        key = source['id']
        if key not in by_id or not key.startswith(('1.', '2.', '3.', '4.', '5.')):
            continue
        following, neighbor_source = [], None
        for candidate in contexts[index + 1:]:
            if candidate['id'] in by_id:
                neighbor_source = candidate
                break
            following.append(candidate)
        if not following or not neighbor_source:
            continue
        sources = following + [neighbor_source]
        if any(row['id'].split('.', 1)[1] != key.split('.', 1)[1]
               or not row['id'].startswith(('1.', '2.', '3.', '4.', '5.')) for row in sources):
            continue
        parent, neighbor = by_id[key], by_id[neighbor_source['id']]
        if parent.subitems or neighbor.subitems or parent.images != neighbor.images:
            continue
        common, separator, question = neighbor.text_latex.rpartition('\n\n')
        if (not separator or not common or not neighbor_source['body']
                or _canonical(question) != _canonical(neighbor_source['body'])
                or not parent.text_latex.startswith(common + '\n\n')):
            continue
        paragraphs = re.split(r'\n\s*\n', parent.text_latex)
        if len(paragraphs) <= len(following):
            continue
        tail = paragraphs[-len(following):]
        if any(not row['body'] or _canonical(fragment) != _canonical(row['body'])
               or r'\taskpic{' in fragment or not answers.get(row['id'])
               for fragment, row in zip(tail, following)):
            continue
        retained = '\n\n'.join(paragraphs[:-len(following)]).rstrip()
        if not retained.startswith(common + '\n\n'):
            continue
        first = deepcopy(parent)
        first.text_latex = retained
        rows = [first]
        for fragment, row in zip(tail, following):
            draft = deepcopy(neighbor)
            draft.external_id = draft.source_number = row['id']
            draft.text_latex = common + '\n\n' + fragment
            draft.author_answer_latex = answers[row['id']]
            draft.author_solution_latex = ''
            draft.exam_item_codes = [exam_item_code(row['id'])]
            draft.tags = []
            rows.append(draft)
        for draft in rows:
            draft.warnings.append('Граница задачи восстановлена по PDF с сохранением общего условия; требуется сверка')
            draft.confidence = min(draft.confidence, 0.9)
        replacements[key] = rows
        recovered.extend(row.external_id for row in rows[1:])
    return [row for task in tasks for row in replacements.get(task.external_id, [task])], recovered

"""Восстановление систем №13 из текста PDF и подписанных вариантов ответа."""
import re
import unicodedata
from copy import deepcopy
from pathlib import Path


SYSTEM_IDS = {*(f'13.2.{n}' for n in range(17, 20)), *(f'13.3.{n}' for n in range(13, 19))}


def _math_tex(text):
    text = re.sub(r'\s+', '', text)
    for source, target in [('−', '-'), ('≤', r'\leq '), ('≥', r'\geq '),
                           ('∞', r'\infty'), ('∪', r'\cup')]:
        text = text.replace(source, target)
    return re.sub(r'(?<=\d),(?=\d)', '{,}', text)


def system_body_from_pdf(source, graphical=False):
    """Проверяет две полные строки системы и все четыре текстовых варианта."""
    source = unicodedata.normalize('NFKC', source).replace('−', '-')
    source = re.sub(r'[\ufe00-\ufe0f]', '', source)
    source = re.sub(r'^(?:\s|Прототип|Аналоги|Ответ)+', '', source)
    head, separator, options = source.partition('1)')
    if not separator:
        return None
    match = re.fullmatch(r'Укажите решение системы неравенств\s*\{\s*([^\n]+),\s*\n([^\n]+)\.\s*', head)
    if not match:
        return None
    term = r'(?:\d+(?:,\d+)?x?|x)'
    expression = rf'[+-]?{term}(?:[+-]{term})*'
    relation = rf'{expression}[<>≤≥]{expression}'
    lines = [re.sub(r'\s+', '', s) for s in match.groups()]
    if not all(re.fullmatch(relation, s) for s in lines):
        return None
    body = ('Укажите решение системы неравенств\n\n' + r'\[\begin{cases}'
            + _math_tex(lines[0]) + r',\\' + _math_tex(lines[1]) + r'.\end{cases}\]')
    if graphical:
        if re.findall(r'(?<!\d)([1-4])\)', '1)' + options) != ['1', '2', '3', '4']:
            return None
        return body + '\n\n' + r'\taskpic{1}'
    choices = re.fullmatch(r'(.+?);\s*2\)(.+?);\s*3\)(.+?);\s*4\)(.+?)\.\s*', options, re.S)
    if not choices:
        return None
    endpoint = r'[+-]?(?:\d+(?:,\d+)?|∞)'
    interval = rf'[\[(]{endpoint};{endpoint}[\])]'
    rendered = []
    for index, value in enumerate(choices.groups(), 1):
        value = re.sub(r'\s+', '', value)
        if value == 'нетрешений':
            option = 'нет решений'
        elif re.fullmatch(rf'{interval}(?:∪{interval})*', value):
            option = '$' + _math_tex(value) + '$'
        else:
            return None
        rendered.append(f'{index}) {option}' + (';' if index < 4 else '.') + r'\\')
    return body + '\n\n' + '\n'.join(rendered)


def extract_pdf_systems(pdf_path):
    """Берёт каждое условие по его маркеру, рисунки — вместе с номерами 1–4."""
    import pymupdf as fitz
    result = {}
    with fitz.open(pdf_path) as doc:
        names = doc.resolve_names()
        for key in sorted(SYSTEM_IDS):
            info = names.get('task::' + key)
            if not info:
                continue
            page = doc[info['page']]
            marker = re.search(r'(?:Аналог|Задача)\s+' + re.escape(key) + r'\.(?!\d)', page.get_text())
            if not marker:
                continue
            source = page.get_text()[marker.end():].split('Ответ:', 1)[0]
            if re.search(r'(?:Аналог|Задача)\s+\d+\.', source):
                continue
            graphical = key.startswith('13.2.')
            body = system_body_from_pdf(source, graphical)
            if body is None:
                continue
            image = None
            if graphical:
                top = page.rect.height - info['to'][1]
                blanks = [r for r in page.search_for('Ответ:') if r.y0 > top + 25]
                if not blanks:
                    continue
                end = min(r.y0 for r in blanks) - 7
                positions = [[r for r in page.search_for(str(n) + ')') if top < r.y0 < end]
                             for n in range(1, 5)]
                if any(len(items) != 1 for items in positions):
                    continue
                start = positions[0][0].y0 - 5
                box = fitz.Rect(72, start, 523, end)
                if not 20 < box.height < 200 or not page.rect.contains(box):
                    continue
                if not all(box.contains(items[0]) for items in positions):
                    continue
                image = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=box).tobytes('png')
            result[key] = {'body': body, 'image': image, 'page': info['page'] + 1}
    return result


def attach_pdf_systems(bundle, systems, answers, dest):
    """Сохраняет условия, собственные ответы и файлы, не меняя исходные объекты."""
    from .ostromogilsky_parser import exam_item_code, is_analog_id
    by_id = {t.external_id: t for t in bundle.tasks}
    prepared = {}
    for key, row in systems.items():
        if key not in SYSTEM_IDS or not answers.get(key):
            continue
        reference = by_id.get(key) or by_id.get('13.3.13')
        if reference is None:
            continue
        draft = deepcopy(reference)
        draft.external_id = draft.source_number = key
        draft.text_latex = row['body']
        draft.subitems = []
        draft.images = ['oge-inequality-options-' + key.replace('.', '-')] if row['image'] else []
        draft.author_answer_latex = answers[key]
        draft.exam_item_codes = [exam_item_code(key)]
        if key not in by_id:
            draft.tags = []
            draft.author_solution_latex = ''
            draft.review_status = 'needs_review'
        warning = 'Система и варианты ответа восстановлены из PDF; требуется сверка'
        draft.warnings = [w for w in draft.warnings if w != warning] + [warning]
        draft.confidence = min(draft.confidence, 0.9)
        prepared[key] = draft
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for key, draft in prepared.items():
        if draft.images:
            (dest / (draft.images[0] + '.png')).write_bytes(systems[key]['image'])
    added = [key for key in prepared if key not in by_id]
    bundle.tasks = [prepared.get(t.external_id, t) for t in bundle.tasks] + [prepared[key] for key in added]
    bundle.diagnostics['pdf_systems_restored'] = list(prepared)
    bundle.diagnostics['pdf_systems_added'] = added
    for field in ['missing_task_ids', 'answers_without_task']:
        bundle.diagnostics[field] = [key for key in bundle.diagnostics.get(field, []) if key not in prepared]
    bundle.diagnostics.update(unique_tasks=len(bundle.tasks),
                              answers_matched=sum(bool(t.author_answer_latex) for t in bundle.tasks),
                              prototype_count=sum(not is_analog_id(t.external_id) for t in bundle.tasks),
                              analog_count=sum(is_analog_id(t.external_id) for t in bundle.tasks),
                              tasks_with_images=sum(bool(t.images) for t in bundle.tasks))
    bundle.diagnostics.setdefault('tasks_by_exam', {})['13'] = sum(t.external_id.startswith('13.') for t in bundle.tasks)
    return list(prepared)

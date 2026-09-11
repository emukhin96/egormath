"""Восстановление склеенных заданий на знаки коэффициентов линейной функции."""
import re
import unicodedata
from copy import deepcopy
from pathlib import Path


LINEAR_IDS = {f'11.1.{n}' for n in [1, 2, 3, 4, 7, 8, 9, 10, 11, 12]}
INTRO = ('На рисунках изображены графики функций вида $y=kx+b$. Установите соответствие '
         'между знаками коэффициентов $k$ и $b$ и графиками функций.')
TABLE = r'''\begin{tabular}{|l|l|l|}
\hline
А & Б & В \\
\hline
 & & \\
\hline
\end{tabular}'''


def linear_body_from_pdf(source):
    """Проверяет полное вводное условие и ровно три пары знаков А, Б, В."""
    source = unicodedata.normalize('NFKC', source)
    source = re.sub(r'^(?:\s|Прототип|Аналоги|Ответ|SIM|DEMO|NEW|OLD)+', '', source)
    introduction, separator, coefficients = source.partition('КОЭФФИЦИЕНТЫ')
    canonical = lambda s: re.sub(r'[\s$]', '', s)
    if not separator or canonical(introduction) != canonical(INTRO):
        return None
    coefficients = re.sub(r'\s+', '', coefficients)
    match = re.fullmatch(r'А\)k([<>])0,b([<>])0;Б\)k([<>])0,b([<>])0;В\)k([<>])0,b([<>])0\.', coefficients)
    if not match:
        return None
    signs = match.groups()
    choices = '\n'.join(label + ') $k' + signs[i * 2] + '0$, $b' + signs[i * 2 + 1] + '0$;' + r'\\'
                        for i, label in enumerate('АБВ'))
    return (INTRO + '\n\n' + choices + '\n\n' + r'\taskpic{1}'
            + '\n\nВ таблице под каждой буквой укажите соответствующий номер.\n\n' + TABLE)


def extract_pdf_linear_graphs(pdf_path):
    """Извлекает графики одной задачи с их исходными номерами и осями."""
    import pymupdf as fitz
    result = {}
    with fitz.open(pdf_path) as doc:
        names = doc.resolve_names()
        for key in sorted(LINEAR_IDS):
            info = names.get('task::' + key)
            if not info:
                continue
            page = doc[info['page']]
            text = page.get_text()
            marker = re.search(r'Аналог\s+' + re.escape(key) + r'\.(?!\d)', text)
            if not marker:
                continue
            source = text[marker.end():].split('ГРАФИКИ', 1)[0]
            body = linear_body_from_pdf(source)
            if body is None:
                continue
            top = page.rect.height - info['to'][1]
            next_top = min((page.rect.height - other['to'][1] for name, other in names.items()
                            if name.startswith('task::') and other['page'] == info['page']
                            and page.rect.height - other['to'][1] > top + 1), default=page.rect.height)
            headers = [r for r in page.search_for('ГРАФИКИ') if top < r.y0 < next_top]
            endings = [r for r in page.search_for('В таблице под каждой буквой') if top < r.y0 < next_top]
            if len(headers) != 1 or len(endings) != 1:
                continue
            header, ending = headers[0], endings[0]
            numbers = [[r for r in page.search_for(f'{n})') if header.y1 < r.y0 < ending.y0]
                       for n in range(1, 4)]
            if any(len(items) != 1 for items in numbers):
                continue
            drawings = [d['rect'] for d in page.get_drawings()
                        if d['rect'].height > 35 and header.y1 < d['rect'].y0
                        and d['rect'].y1 < ending.y0 and d['rect'].x0 >= 72]
            if not drawings:
                continue
            box = fitz.Rect(72, header.y1 + 2, 523, max(r.y1 for r in drawings) + 1)
            if not page.rect.contains(box) or not all(box.contains(items[0]) for items in numbers):
                continue
            result[key] = {'body': body, 'page': info['page'] + 1,
                           'image': page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), clip=box).tobytes('png')}
    return result


def attach_pdf_linear_graphs(bundle, figures, answers, dest):
    """Сохраняет восстановленные карточки и файлы графиков в экспорт."""
    from .ostromogilsky_parser import exam_item_code, is_analog_id
    by_id = {t.external_id: t for t in bundle.tasks}
    prepared = {}
    for key, figure in figures.items():
        if key not in LINEAR_IDS or not answers.get(key):
            continue
        reference = by_id.get(key) or by_id.get('11.1.1')
        if reference is None:
            continue
        draft = deepcopy(reference)
        draft.external_id = draft.source_number = key
        draft.text_latex = figure['body']
        draft.subitems = []
        draft.images = ['oge-numbered-graphs-' + key.replace('.', '-')]
        draft.author_answer_latex = answers[key]
        draft.exam_item_codes = [exam_item_code(key)]
        if key not in by_id:
            draft.tags = []
            draft.author_solution_latex = ''
            draft.review_status = 'needs_review'
        warning = 'Знаки коэффициентов и графики восстановлены из PDF; требуется сверка'
        draft.warnings = [w for w in draft.warnings if w != warning] + [warning]
        draft.confidence = min(draft.confidence, 0.9)
        prepared[key] = draft
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for key, draft in prepared.items():
        (dest / (draft.images[0] + '.png')).write_bytes(figures[key]['image'])
    added = [key for key in prepared if key not in by_id]
    bundle.tasks = [prepared.get(t.external_id, t) for t in bundle.tasks] + [prepared[key] for key in added]
    bundle.diagnostics['pdf_linear_graphs_restored'] = list(prepared)
    bundle.diagnostics['pdf_linear_graphs_added'] = added
    for field in ['missing_task_ids', 'answers_without_task']:
        bundle.diagnostics[field] = [key for key in bundle.diagnostics.get(field, []) if key not in prepared]
    bundle.diagnostics.update(unique_tasks=len(bundle.tasks),
                              answers_matched=sum(bool(t.author_answer_latex) for t in bundle.tasks),
                              prototype_count=sum(not is_analog_id(t.external_id) for t in bundle.tasks),
                              analog_count=sum(is_analog_id(t.external_id) for t in bundle.tasks),
                              tasks_with_images=sum(bool(t.images) for t in bundle.tasks))
    bundle.diagnostics.setdefault('tasks_by_exam', {})['11'] = sum(t.external_id.startswith('11.') for t in bundle.tasks)
    return list(prepared)

"""Восстановление условий, оказавшихся внутри OCR-картинок №17."""
import re
from copy import deepcopy
from pathlib import Path

from .ostromogilsky_splits import extract_pdf_task_contexts


# Для этих страниц проверено положение рисунка справа от условия.
GEOMETRY_IDS = {
    '17.16.3', '17.16.4', '17.16.7', '17.16.8',
    *(f'17.17.{n}' for n in range(1, 8)), '17.25', '17.26',
}


def geometry_body_from_pdf(body):
    """Принимает только целое условие одного из проверенных типов."""
    body = re.sub(r'\s+', ' ', body).strip().replace('∘', '°')
    patterns = [
        r'Сторона ромба равна \d+, а один из углов этого ромба равен \d+°\. Найдите высоту этого ромба\.',
        r'Периметр ромба равен \d+, а один из углов равен \d+°\. Найдите площадь этого ромба\.',
        r'Один из углов равнобедренной трапеции равен \d+°\. Найдите больший угол этой трапеции\. Ответ дайте в градусах\.',
        r'Сумма двух углов равнобедренной трапеции равна \d+°\. Найдите меньший угол этой трапеции\. Ответ дайте в градусах\.',
    ]
    if not any(re.fullmatch(pattern, body) for pattern in patterns):
        return None
    return re.sub(r'\d+°?', lambda m: '$' + m[0].replace('°', r'^{\circ}') + '$', body)


def extract_pdf_geometry(pdf_path):
    """Читает условие и вырезает рисунок до строки ответа того же номера."""
    import pymupdf as fitz
    contexts = extract_pdf_task_contexts(pdf_path)
    result = {}
    with fitz.open(pdf_path) as doc:
        names = doc.resolve_names()
        for row in contexts:
            key = row['id']
            if key not in GEOMETRY_IDS:
                continue
            body = geometry_body_from_pdf(row['body'])
            if body is None:
                continue
            info = names['task::' + key]
            page = doc[info['page']]
            top = page.rect.height - info['to'][1]
            next_top = min((page.rect.height - item['to'][1]
                            for name, item in names.items()
                            if name.startswith('task::') and item['page'] == info['page']
                            and page.rect.height - item['to'][1] > top + 1),
                           default=page.rect.height)
            blanks = [r for r in page.search_for('Ответ:') if top + 30 < r.y0 < next_top]
            if len(blanks) != 1:
                continue
            box = fitz.Rect(365, top + 35, 510, blanks[0].y0 - 7)
            if not 15 < box.height < 200 or not page.rect.contains(box):
                continue
            # Текст условия не должен попасть в кадр; рисунок обязан содержать линии.
            if page.get_textbox(box).strip():
                continue
            if not any(box.intersects(drawing['rect']) for drawing in page.get_drawings()):
                continue
            result[key] = {'body': body, 'page': row['page'],
                           'image': page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=box).tobytes('png')}
    return result


def attach_pdf_geometry(bundle, figures, answers, dest):
    """Добавляет проверенные условия и сохраняет их рисунки в пакет импорта."""
    from .ostromogilsky_parser import exam_item_code, is_analog_id
    by_id = {task.external_id: task for task in bundle.tasks}
    prepared = {}
    for key, figure in figures.items():
        if key not in GEOMETRY_IDS or not answers.get(key):
            continue
        reference = by_id.get(key) or by_id.get('17.16.3' if is_analog_id(key) else '17.25')
        if reference is None:
            continue
        draft = deepcopy(reference)
        stem = 'oge-pdf-' + key.replace('.', '-')
        draft.external_id = draft.source_number = key
        draft.text_latex = figure['body'] + '\n\\taskpic{1}'
        draft.images = [stem]
        draft.subitems = []
        draft.author_answer_latex = answers[key]
        draft.exam_item_codes = [exam_item_code(key)]
        if key not in by_id:
            draft.tags = []
            draft.author_solution_latex = ''
            draft.review_status = 'needs_review'
        draft.warnings = [w for w in draft.warnings if not w.startswith('Условие и рисунок восстановлены из PDF')]
        draft.warnings.append('Условие и рисунок восстановлены из PDF; требуется сверка')
        draft.confidence = min(draft.confidence, 0.9)
        prepared[key] = (draft, stem, figure['image'])
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for draft, stem, image in prepared.values():
        (dest / (stem + '.png')).write_bytes(image)
    bundle.tasks = [prepared[t.external_id][0] if t.external_id in prepared else t for t in bundle.tasks]
    recovered = [key for key in prepared if key not in by_id]
    bundle.tasks.extend(prepared[key][0] for key in recovered)
    bundle.diagnostics['pdf_geometry_restored'] = list(prepared)
    bundle.diagnostics['pdf_geometry_added'] = recovered
    for field in ['missing_task_ids', 'answers_without_task']:
        bundle.diagnostics[field] = [key for key in bundle.diagnostics.get(field, []) if key not in prepared]
    bundle.diagnostics['unique_tasks'] = len(bundle.tasks)
    bundle.diagnostics['answers_matched'] = sum(bool(t.author_answer_latex) for t in bundle.tasks)
    bundle.diagnostics['prototype_count'] = sum(not is_analog_id(t.external_id) for t in bundle.tasks)
    bundle.diagnostics['analog_count'] = sum(is_analog_id(t.external_id) for t in bundle.tasks)
    bundle.diagnostics['tasks_with_images'] = sum(bool(t.images) for t in bundle.tasks)
    counts = bundle.diagnostics.get('tasks_by_exam', {})
    counts['17'] = sum(t.external_id.startswith('17.') for t in bundle.tasks)
    bundle.diagnostics['tasks_by_exam'] = counts
    return list(prepared)

"""Проверенные исключения OCR: участок1.4–5.4 и выражение8.32.

Тексты сверены с PDF12–13/37. Исправление применяется только при точном
совпадении нормализованного источника; план проверяется по байтам PDF.
"""
import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path


PLOT_IDS = [f'{number}.4' for number in range(1, 6)]
PLAN_STEM = 'oge-shared-plot-prototype-4'


def normalize_source(text):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'(?<=[а-яё])-\n(?=[а-яё])', '', text)
    text = re.sub(r'^(?:\s|Прототип|Аналоги|Ответ)+', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def read_repair_spec():
    return json.loads((Path(__file__).parent / 'data' / 'ostromogilsky_pdf_repairs.json').read_text())


def pdf_image_on_white(doc, info):
    """Сохраняет исходный размер изображения и учитывает отдельную PDF-маску."""
    raw = doc.extract_image(info[0])['image']
    if not info[1]:
        return raw
    import pymupdf as fitz
    from io import BytesIO
    from PIL import Image
    combined = fitz.Pixmap(fitz.Pixmap(doc,info[0]),fitz.Pixmap(doc,info[1]))
    rgba = Image.open(BytesIO(combined.tobytes('png'))).convert('RGBA')
    white = Image.new('RGBA',rgba.size,'white')
    white.alpha_composite(rgba)
    stream = BytesIO()
    white.convert('RGB').save(stream,format='PNG')
    return stream.getvalue()


def matching_repairs(sources, common, image, spec, mask=b''):
    """Блок участка восстанавливается целиком; несовпадение отменяет все5 задач."""
    result = {}
    if ('8.32' in sources and normalize_source(sources['8.32']) == spec['tasks']['8.32']['source']):
        result['8.32'] = {'body': spec['tasks']['8.32']['latex'], 'image': None}
    if (normalize_source(common) != spec['shared']['source']
            or hashlib.sha256(image or b'').hexdigest() != spec['shared']['image_sha256']
            or hashlib.sha256(mask).hexdigest() != spec['shared'].get('mask_sha256',hashlib.sha256(b'').hexdigest())
            or any(key not in sources or normalize_source(sources[key]) != spec['tasks'][key]['source'] for key in PLOT_IDS)):
        return result
    for key in PLOT_IDS:
        result[key] = {'body': spec['shared']['latex'] + '\n\n' + spec['tasks'][key]['latex'], 'image': image}
    return result


def extract_pdf_repairs(pdf_path):
    """Читает условия по якорям и оригинальное встроенное изображение участка."""
    import pymupdf
    sources, common, image, rendered, mask = {}, '', None, None, b''
    spec = read_repair_spec()
    with pymupdf.open(pdf_path) as doc:
        names = doc.resolve_names()
        for key in spec['tasks']:
            info = names.get('task::' + key)
            if not info:
                continue
            page = doc[info['page']]
            text = page.get_text()
            marker = re.search(r'(?:Задача|Аналог)\s+' + re.escape(key) + r'\.(?!\d)', text)
            if not marker:
                continue
            tail = text[marker.end():]
            if 'Ответ:' not in tail:
                continue
            sources[key] = tail.split('Ответ:', 1)[0]
            if key == '1.4':
                beginning = text.find('На плане изображён')
                if beginning < 0 or beginning >= marker.start():
                    continue
                common = text[beginning:marker.start()]
                images = page.get_images()
                if len(images) == 1:
                    extracted = doc.extract_image(images[0][0])
                    if extracted['ext'] == 'png':
                        image = extracted['image']
                        mask = doc.extract_image(images[0][1])['image'] if images[0][1] else b''
                        rendered = pdf_image_on_white(doc,images[0])
    result = matching_repairs(sources, common, image, spec, mask)
    for key in PLOT_IDS:
        if key in result:
            result[key]['image'] = rendered
    return result


def attach_pdf_repairs(bundle, repairs, answers, dest):
    """Включает целый блок в исходное место списка и добавляет выражение с корнем."""
    from .ostromogilsky_parser import exam_item_code, is_analog_id
    by_id = {task.external_id: task for task in bundle.tasks}
    prepared = {}
    plot_ready = all(key in repairs and answers.get(key) for key in PLOT_IDS) and '2.4' in by_id
    keys = (PLOT_IDS if plot_ready else []) + (['8.32'] if '8.32' in repairs and answers.get('8.32') else [])
    for key in keys:
        reference = by_id.get(key) or by_id.get('8.31' if key == '8.32' else '2.4')
        if reference is None:
            continue
        draft = deepcopy(reference)
        draft.external_id = draft.source_number = key
        draft.text_latex = repairs[key]['body']
        draft.subitems = []
        draft.images = [PLAN_STEM] if key in PLOT_IDS else []
        draft.author_answer_latex = answers[key]
        draft.exam_item_codes = [exam_item_code(key)]
        if key not in by_id:
            draft.tags = []
            draft.author_solution_latex = ''
            draft.review_status = 'needs_review'
        warning = 'Применено сверенное исправление при совпадении источника PDF; требуется сверка'
        draft.warnings = [w for w in draft.warnings if w != warning] + [warning]
        draft.confidence = min(draft.confidence, 0.9)
        prepared[key] = draft
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if plot_ready:
        (dest / (PLAN_STEM + '.png')).write_bytes(repairs['1.4']['image'])
    tasks, inserted = [], set()
    for task in bundle.tasks:
        key = task.external_id
        if plot_ready and key in PLOT_IDS:
            if '1.4' not in inserted:
                tasks.extend(prepared[item] for item in PLOT_IDS)
                inserted.update(PLOT_IDS)
        elif key in prepared:
            tasks.append(prepared[key])
            inserted.add(key)
        else:
            tasks.append(task)
        if key == '8.31' and '8.32' in prepared and '8.32' not in by_id:
            tasks.append(prepared['8.32'])
            inserted.add('8.32')
    tasks.extend(draft for key, draft in prepared.items() if key not in inserted)
    bundle.tasks = tasks
    bundle.diagnostics['pdf_verified_repairs'] = list(prepared)
    bundle.diagnostics['pdf_verified_repairs_added'] = [key for key in prepared if key not in by_id]
    for field in ['missing_task_ids', 'answers_without_task']:
        bundle.diagnostics[field] = [key for key in bundle.diagnostics.get(field, []) if key not in prepared]
    bundle.diagnostics.update(unique_tasks=len(tasks),
                              answers_matched=sum(bool(t.author_answer_latex) for t in tasks),
                              prototype_count=sum(not is_analog_id(t.external_id) for t in tasks),
                              analog_count=sum(is_analog_id(t.external_id) for t in tasks),
                              tasks_with_images=sum(bool(t.images) for t in tasks))
    counts = bundle.diagnostics.setdefault('tasks_by_exam', {})
    for number in ['1', '2', '3', '4', '5', '8']:
        counts[number] = sum(t.external_id.split('.')[0] == number for t in tasks)
    return list(prepared)

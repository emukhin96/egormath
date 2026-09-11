"""Сверенные общие условия участков и квартир, пропущенные OCR-разметкой."""
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from .ostromogilsky_pdf_repairs import normalize_source, pdf_image_on_white


def shared_repair_specs():
    return json.loads((Path(__file__).parent/'data'/'ostromogilsky_shared_repairs.json').read_text())


def match_shared_repair(spec, common, sources, image, mask=b''):
    """Не восстанавливает часть блока при несовпадении любого исходного вопроса."""
    return (normalize_source(common) == spec['source']
            and hashlib.sha256(image or b'').hexdigest() == spec['image_sha256']
            and hashlib.sha256(mask).hexdigest() == spec.get('mask_sha256',hashlib.sha256(b'').hexdigest())
            and all(key in sources and normalize_source(sources[key]) == row['source']
                    for key,row in spec['questions'].items()))


def extract_shared_repairs(pdf_path):
    """Проверяет общий текст, пять условий и оригинальный встроенный план."""
    import pymupdf as fitz
    result = []
    with fitz.open(pdf_path) as doc:
        names = doc.resolve_names()
        for spec in shared_repair_specs():
            if not 0 <= spec['page']-1 < len(doc):
                continue
            page = doc[spec['page']-1]
            common = page.get_text(clip=fitz.Rect(spec['clip'])).split('Оглавление')[0].strip()
            images = page.get_images()
            if len(images) != 1:
                continue
            image = doc.extract_image(images[0][0])
            if image['ext'] != 'png':
                continue
            sources = {}
            for key in spec['questions']:
                info = names.get('task::'+key)
                if not info:
                    continue
                text = doc[info['page']].get_text()
                marker = re.search(r'(?:Задача|Аналог)\s+'+re.escape(key)+r'\.(?!\d)',text)
                if not marker:
                    continue
                tail = text[marker.end():]
                if 'Ответ:' in tail:
                    sources[key] = tail.split('Ответ:',1)[0]
            mask = doc.extract_image(images[0][1])['image'] if images[0][1] else b''
            if match_shared_repair(spec,common,sources,image['image'],mask):
                result.append({**spec,'image':pdf_image_on_white(doc,images[0])})
    return result


def attach_shared_repairs(bundle, repairs, dest):
    """Возвращает общий контекст всем пяти существующим вопросам целиком."""
    by_id = {t.external_id:t for t in bundle.tasks}
    prepared, groups = {}, {}
    dest = Path(dest)
    dest.mkdir(parents=True,exist_ok=True)
    for repair in repairs:
        keys = sorted(repair['questions'],key=lambda key:int(key.split('.')[0]))
        if len(keys)!=5 or any(key not in by_id for key in keys):
            continue
        if [int(key.split('.')[0]) for key in keys] != [1,2,3,4,5]:
            continue
        if any(key.split('.',1)[1] != repair['suffix'] for key in keys):
            continue
        for key in keys:
            draft = deepcopy(by_id[key])
            draft.text_latex = repair['common_latex']+'\n\n'+repair['questions'][key]['latex']
            draft.images = [repair['image_stem']]
            draft.subitems = []
            warning = 'Общее условие и план восстановлены при совпадении всех пяти вопросов с PDF; требуется сверка'
            draft.warnings = [w for w in draft.warnings if w!=warning]+[warning]
            draft.warnings = list(dict.fromkeys([
                *draft.warnings,*repair['questions'][key].get('warnings',[])]))
            draft.confidence = min(draft.confidence,0.9)
            prepared[key] = draft
            groups[key] = keys
        (dest/(repair['image_stem']+'.png')).write_bytes(repair['image'])
    tasks, inserted = [],set()
    for task in bundle.tasks:
        key = task.external_id
        if key not in prepared:
            tasks.append(task)
        elif key not in inserted:
            keys = groups[key]
            tasks.extend(prepared[item] for item in keys)
            inserted.update(keys)
    bundle.tasks = tasks
    # В OCR начало нового общего условия оказалось хвостом предыдущего
    # вопроса. Убираем его только после полного восстановления нового блока.
    from .ostromogilsky_splits import _canonical
    cleaned = []
    neighbors = {'7.4':'5.7.3', '7.7':'5.7.6'}
    for repair in repairs:
        neighbor = neighbors.get(repair['suffix'])
        if not neighbor or f"1.{repair['suffix']}" not in prepared:
            continue
        for index, task in enumerate(bundle.tasks):
            if task.external_id != neighbor or len(task.images) != 2:
                continue
            start = task.text_latex.rfind('На рисунке изображён')
            if start <= 0:
                continue
            head, tail = task.text_latex[:start],task.text_latex[start:]
            if (re.findall(r'\\taskpic\{(\d+)\}',head) != ['1']
                    or re.findall(r'\\taskpic\{(\d+)\}',tail) != ['2']
                    or _canonical(tail) != _canonical(repair['common_latex'])):
                continue
            draft = deepcopy(task)
            draft.text_latex = re.sub(r'[\s□]+$', '',head)
            draft.images = task.images[:1]
            bundle.tasks[index] = draft
            cleaned.append(neighbor)
    bundle.diagnostics['pdf_shared_blocks_restored'] = sorted({key.split('.',1)[1] for key in prepared})
    bundle.diagnostics['pdf_shared_questions_restored'] = len(prepared)
    bundle.diagnostics['tasks_with_images'] = sum(bool(t.images) for t in tasks)
    bundle.diagnostics['pdf_shared_neighbor_tails_removed'] = cleaned
    # После PDF-восстановления отчёт должен учитывать и новые общие условия,
    # а исходное число OCR-маркеров остаётся отдельной диагностикой.
    from collections import defaultdict
    from .block_text import split_common_condition
    blocks = defaultdict(list)
    for task in bundle.tasks:
        match = re.fullmatch(r'([1-5])\.(\d+(?:\.\d+)?)',task.external_id)
        if match:
            blocks[match[2]].append(task)
    complete = 0
    for rows in blocks.values():
        rows.sort(key=lambda task:int(task.external_id.split('.')[0]))
        if len(rows)==5 and split_common_condition([t.text_latex for t in rows],[t.images for t in rows]):
            complete += 1
    bundle.diagnostics.setdefault('ocr_shared_blocks',bundle.diagnostics.get('shared_blocks',0))
    bundle.diagnostics.setdefault('ocr_tasks_with_shared_stem',bundle.diagnostics.get('tasks_with_shared_stem',0))
    bundle.diagnostics['shared_blocks'] = complete
    bundle.diagnostics['tasks_with_shared_stem'] = complete*5
    return list(prepared)

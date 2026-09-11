"""Повторяемое восстановление графиков №11 и предупреждений об источнике."""
import json
import re
from copy import deepcopy
from pathlib import Path
from .ostromogilsky_pdf_repairs import normalize_source


def graph_repair_specs():
    return json.loads((Path(__file__).parent/'data'/'ostromogilsky_graph_repairs.json').read_text())


def extract_graph_repairs(pdf_path, specs=None):
    """Проверяет полное условие перед извлечением трёх подписанных графиков."""
    import pymupdf as fitz
    result = []
    with fitz.open(pdf_path) as doc:
        names = doc.resolve_names()
        for spec in graph_repair_specs() if specs is None else specs:
            info = names.get('task::'+spec['id'])
            if not info:
                continue
            page = doc[info['page']]
            text = page.get_text()
            marker = re.search(r'(?:Задача|Аналог)\s+'+re.escape(spec['id'])+r'\.(?!\d)',text)
            if not marker:
                continue
            source = re.split(r'(?:Задача|Аналог)\s+\d+\.|Оглавление',text[marker.end():],1)[0]
            if spec.get('end_at_answer'):
                if 'Ответ:' not in source:
                    continue
                source = source.split('Ответ:',1)[0]
            if normalize_source(source) != spec['source']:
                continue
            box = fitz.Rect(spec['clip'])
            if not page.rect.contains(box):
                continue
            correction = spec.get('label_correction')
            corrected_doc = None
            if correction:
                bounds = fitz.Rect(correction['bbox'])
                if page.get_textbox(bounds).strip() != correction['old']:
                    continue
                # Изменение страницы не должно влиять на соседний график,
                # который будет извлечён из неё следующей итерацией.
                corrected_doc = fitz.open()
                corrected_doc.insert_pdf(doc,from_page=info['page'],to_page=info['page'])
                page = corrected_doc[0]
                page.add_redact_annot(bounds,fill=(1,1,1))
                page.apply_redactions(images=0,graphics=0)
                # Латинская B имеет тот же рисунок, что кириллическая В.
                # В PNG остаётся только форма знака; встроенный шрифт
                # устраняет зависимость экспорта от локальной установки CMU.
                page.insert_text(correction['origin'],correction['new'],
                                 fontsize=correction['size'],fontname='tiro')
            scale = spec.get('scale',2.5)
            image = page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=box).tobytes('png')
            if corrected_doc is not None:
                corrected_doc.close()
            result.append({**spec,'image':image})
    return result


def attach_graph_repairs(bundle, repairs, dest, *, diagnostic_key='pdf_graph_repairs',
                         message='Условие и подписанные графики восстановлены по совпавшему тексту PDF; требуется сверка'):
    """Сохраняет исходные ответы/метки и явно переносит замечания к источнику."""
    by_id = {task.external_id:task for task in bundle.tasks}
    prepared = {}
    dest = Path(dest)
    dest.mkdir(parents=True,exist_ok=True)
    for row in repairs:
        if row['id'] not in by_id:
            continue
        draft = deepcopy(by_id[row['id']])
        draft.text_latex = row['latex']
        draft.images = [row['image_stem']]
        draft.subitems = []
        warnings = [message,*row.get('warnings',[])]
        if row.get('label_correction'):
            warnings.append('Исправлена опечатка подписи графика в источнике; порядок вариантов сохранён')
        draft.warnings = list(dict.fromkeys([*draft.warnings,*warnings]))
        draft.confidence = min(draft.confidence,0.9)
        prepared[row['id']] = draft
        (dest/(row['image_stem']+'.png')).write_bytes(row['image'])
    bundle.tasks = [prepared.get(task.external_id,task) for task in bundle.tasks]
    bundle.diagnostics[diagnostic_key] = list(prepared)
    bundle.diagnostics['tasks_with_images'] = sum(bool(task.images) for task in bundle.tasks)
    return list(prepared)

"""Сверенные исключения OCR: бланки, чужие рисунки и нумерация утверждений."""
import json
import re
from pathlib import Path
from .ostromogilsky_pdf_repairs import normalize_source


def apply_final_repairs(bundle, pdf_path, destination):
    """Применяет исправление только при совпадении PDF и прежнего черновика."""
    import pymupdf as fitz
    specs = json.loads((Path(__file__).parent / 'data/ostromogilsky_final_repairs.json').read_text())
    tasks = {t.external_id: t for t in bundle.tasks}
    prepared = []
    with fitz.open(pdf_path) as doc:
        names = doc.resolve_names()
        for row in specs:
            task = tasks.get(row['id'])
            info = names.get('task::' + row['id'])
            if task is None or info is None:
                continue
            if task.text_latex != row['before'] or task.images != row['before_images']:
                continue
            page = doc[info['page']]
            text = page.get_text()
            marker = re.search(r'(?:Задача|Аналог)\s+' + re.escape(row['id']) + r'\.(?!\d)', text)
            if not marker:
                continue
            source = re.split(r'(?:Задача|Аналог)\s+\d+\.|Оглавление', text[marker.end():], 1)[0]
            if normalize_source(source) != row['source']:
                continue
            image = None
            if 'clip' in row:
                clip = fitz.Rect(row['clip'])
                if not page.rect.contains(clip):
                    continue
                image = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip).tobytes('png')
            prepared.append((task, row, image))
    # Общее условие маршрута меняется одновременно у всех пяти вопросов.
    shared_groups = [{f'{n}.1.{suffix}' for n in range(1, 6)} for suffix in [6, 7]]
    prepared_ids = {row['id'] for _, row, _ in prepared}
    incomplete = set().union(*(group for group in shared_groups if not group <= prepared_ids))
    applied = []
    for task, row, image in prepared:
        if row['id'] in incomplete:
            continue
        task.text_latex = row['latex']
        task.images = row['images'][:]
        task.subitems = []
        warning = 'Убраны сверенные по PDF артефакты OCR; сохранены условие, авторский ответ и рисунки задачи'
        task.warnings = list(dict.fromkeys([*task.warnings, warning]))
        if image is not None:
            dest = Path(destination)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / (row['images'][0] + '.png')).write_bytes(image)
        applied.append(row['id'])
    bundle.diagnostics['pdf_final_repairs'] = applied
    return applied


def copy_referenced_images(bundle, source_directory, destination):
    """Собирает только используемые исходные изображения рядом с JSON."""
    import shutil
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    extensions = {'.png', '.jpg', '.jpeg', '.pdf'}
    existing = {p.stem for p in dest.iterdir() if p.suffix.lower() in extensions}
    needed = {stem for task in bundle.tasks for stem in task.images} - existing
    sources = {}
    for path in Path(source_directory).rglob('*'):
        if path.is_file() and path.suffix.lower() in extensions and path.stem in needed:
            sources.setdefault(path.stem, []).append(path)
    missing = sorted(needed - sources.keys())
    ambiguous = sorted(stem for stem, paths in sources.items() if len(paths) != 1)
    if missing or ambiguous:
        raise ValueError(f'Неполный пакет изображений: отсутствуют {missing}; неоднозначны {ambiguous}')
    for paths in sources.values():
        shutil.copyfile(paths[0], dest / paths[0].name)
    bundle.diagnostics['packaged_image_files'] = len(existing | needed)

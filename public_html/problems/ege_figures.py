"""Подготовка рисунков открытого банка ЕГЭ.

OCR иногда захватывает в один JPEG чертёж и расположенный под ним бланк
ответа. Обрезка разрешена лишь после независимого подтверждения координатой
слова «Ответ:» в исходном PDF.
"""

from __future__ import annotations

import re
import shutil
import hashlib
import json
from pathlib import Path


OCR_PAGE_WIDTH = 1985
OCR_PAGE_HEIGHT = 2807
STEM_RE = re.compile(
    r'^(?P<prefix>.+)-(?P<page>\d{3})_(?P<height>\d+)_(?P<width>\d+)'
    r'_(?P<top>\d+)_(?P<left>\d+)$'
)


def _tasks(bundle):
    return getattr(bundle, 'tasks', bundle)


def _image_names(bundle):
    names = set()
    for task in _tasks(bundle):
        names.update(str(name) for name in getattr(task, 'images', []) if name)
        for subitem in getattr(task, 'subitems', []):
            names.update(str(name) for name in getattr(subitem, 'images', []) if name)
    return names


def _image_info(name: str):
    path = Path(name)
    match = STEM_RE.match(path.stem)
    if not match:
        return None
    values = {key: int(value) if key != 'prefix' else value
              for key, value in match.groupdict().items()}
    values['suffix'] = path.suffix or '.jpg'
    values['stem'] = path.stem
    return values


def _grid_bands(image):
    """Широкие горизонтали сетки, сгруппированные в непрерывные полосы."""
    pixels = image.convert('L')
    width, height = pixels.size
    rows = []
    for y in range(height):
        dark = sum(pixels.getpixel((x, y)) < 150 for x in range(width))
        if dark / width >= .85:
            rows.append(y)
    bands = []
    for row in rows:
        if not bands or row > bands[-1][-1] + 1:
            bands.append([row])
        else:
            bands[-1].append(row)
    return [(band[0], band[-1]) for band in bands]


def _answer_grid_top(image):
    """Верхняя полоса сетки ответа или ``None``.

    Сетка имеет верхнюю и нижнюю горизонтали почти на всю ширину JPEG;
    нижняя лежит у нижней кромки, а расстояние между ними соответствует
    высоте клеток. Это отличает её от осей и сторон самого чертежа.
    """
    bands = _grid_bands(image)
    height = image.height
    for upper, lower in zip(bands, bands[1:]):
        gap = lower[0] - upper[1]
        if 20 <= gap <= 110 and height - lower[1] <= 8:
            return upper[0]
    return None


def _answer_y(page, entry, info):
    """Ищет единственный «Ответ:» внутри OCR-bbox и PDF-карточки."""
    page_width, page_height = page.rect.width, page.rect.height
    x0 = info['left'] * page_width / OCR_PAGE_WIDTH
    y0 = info['top'] * page_height / OCR_PAGE_HEIGHT
    x1 = (info['left'] + info['width']) * page_width / OCR_PAGE_WIDTH
    y1 = (info['top'] + info['height']) * page_height / OCR_PAGE_HEIGHT
    task_clip = entry.get('clip') or [0, 0, page_width, page_height]
    labels = []
    for word in page.get_text('words'):
        if word[4] != 'Ответ:':
            continue
        cx = (word[0] + word[2]) / 2
        cy = (word[1] + word[3]) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1 and task_clip[1] <= cy <= task_clip[3]:
            labels.append(cy)
    return labels[0] if len(labels) == 1 else None


def package_ege_images(bundle, source_dir, pdf_path, dest, index):
    """Копирует использованные картинки, удаляя только подтверждённые сетки.

    Возвращаемая диагностика пригодна для JSON и не скрывает сомнительные
    изображения: при отсутствии точного PDF-подтверждения файл копируется
    как есть и попадает в ``needs_review``.
    """
    try:
        import fitz
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError('Для упаковки рисунков нужны PyMuPDF и Pillow.') from exc

    source_dir, dest = Path(source_dir), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    source_files = {}
    for candidate in source_dir.rglob('*'):
        if candidate.is_file() and candidate.suffix.lower() in {'.jpg', '.jpeg', '.png'}:
            source_files.setdefault(candidate.stem, []).append(candidate)
    contexts = (index or {}).get('tasks', index or {})
    by_id = {getattr(task, 'external_id', ''): task for task in _tasks(bundle)}
    owners = {}
    for task in by_id.values():
        for name in getattr(task, 'images', []):
            owners.setdefault(Path(str(name)).stem, getattr(task, 'external_id', ''))
    diagnostics = {'removed_grid': {}, 'copied': [], 'needs_review': {}}
    repair_spec = json.loads((Path(__file__).with_name('data') / 'ege_source_repairs.json').read_text())
    verified_crops = {row['stem']: row for row in repair_spec.get('image_crops', [])}

    doc = fitz.open(pdf_path)
    try:
        for name in sorted(_image_names(bundle)):
            from .ege_cleanup import (PDF_FIGURE_STEM, PDF_SHA256,
                                      PDF_FIGURE_PAGE, PDF_FIGURE_CLIP)
            if name == PDF_FIGURE_STEM:
                if hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest() != PDF_SHA256:
                    raise ValueError('Изменился PDF сверенного рисунка 3.10.3')
                doc[PDF_FIGURE_PAGE - 1].get_pixmap(
                    clip=fitz.Rect(PDF_FIGURE_CLIP), matrix=fitz.Matrix(3, 3)).save(
                        dest / (PDF_FIGURE_STEM + '.png'))
                diagnostics['copied'].append(PDF_FIGURE_STEM)
                continue
            info = _image_info(name)
            stem = Path(name).stem
            matches = source_files.get(stem, [])
            if len(matches) != 1:
                diagnostics['needs_review'][stem] = 'Исходный JPEG не найден'
                continue
            source = matches[0]
            target = dest / source.name
            if stem in verified_crops:
                patch = verified_crops[stem]
                if hashlib.sha256(source.read_bytes()).hexdigest() != patch['sha256']:
                    raise ValueError(f'Изменился сверенный рисунок {stem}')
                with Image.open(source) as image:
                    image.crop((0, 0, image.width, patch['cut_y_pixels'])).save(target)
                diagnostics['removed_grid'][stem] = {
                    'owner': owners.get(stem, ''), **patch}
                continue
            if not info:
                shutil.copy2(source, target)
                diagnostics['copied'].append(stem)
                continue
            owner = owners.get(stem, '')
            entry = contexts.get(owner)
            if not isinstance(entry, dict) or entry.get('page') != info['page']:
                shutil.copy2(source, target)
                diagnostics['needs_review'][stem] = 'Нет совпадающей PDF-карточки на странице OCR; скопирован без обрезки'
                continue
            page = doc[info['page'] - 1]
            answer_y = _answer_y(page, entry, info)
            with Image.open(source) as image:
                relative_y = None if answer_y is None else round(
                    (answer_y - info['top'] * page.rect.height / OCR_PAGE_HEIGHT)
                    * image.height / (info['height'] * page.rect.height / OCR_PAGE_HEIGHT))
                grid_top = _answer_grid_top(image)
                # PDF «Ответ:» подтверждает, что найденная сетка относится к
                # карточке; сама геометрия растра определяет точную границу.
                if relative_y is not None and grid_top is not None:
                    cut = max(1, grid_top)
                    image.crop((0, 0, image.width, cut)).save(target)
                    diagnostics['removed_grid'][stem] = {
                        'owner': owner, 'answer_y_pdf': round(answer_y, 2),
                        'cut_y_pixels': cut, 'grid_top_pixels': grid_top,
                    }
                else:
                    shutil.copy2(source, target)
                    diagnostics['copied'].append(stem)
                    if grid_top is not None:
                        diagnostics['needs_review'][stem] = (
                            'Похожа на сетку ответа, но PDF не подтвердил единственный Ответ:')
    finally:
        doc.close()
    return diagnostics

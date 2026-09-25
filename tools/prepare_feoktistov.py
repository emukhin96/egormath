#!/usr/bin/env python3
"""Готовит JSON и ZIP Феоктистова, восстанавливая рисунок из проверенного PDF."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'public_html'))
from problems.feoktistov_parser import FIGURE_13, SOURCE_SHA256
from problems.textbook_parser import bundle_from_text, write_bundle

PDF_SHA256 = '7c4ae82988a73cfe8cd623b9d379168e8c10ce2c748c7df01c7e39219721af2a'


def prepare(tex, pdf, output):
    """Исходники только читаются; результат требует редакторской сверки."""
    raw = tex.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('Восстановление рисунка рассчитано на проверенный OCR-скан')
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != PDF_SHA256:
        raise ValueError('PDF отличается от проверенного скана: координаты надо сверить')
    try:
        import pymupdf
    except ImportError as exc:
        raise SystemExit('Для подготовки рисунка установите PyMuPDF: '
                         './venv/bin/pip install pymupdf') from exc

    bundle = bundle_from_text('feoktistov', raw.decode('utf-8'), tasks_file=str(tex.resolve()))
    images = output / 'images'
    images.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as document:
        # Печатная с. 107, PDF-страница 108: график без книжной подписи.
        document[107].get_pixmap(matrix=pymupdf.Matrix(3, 3),
                                clip=pymupdf.Rect(278, 76, 384, 240)).save(
                                    str(images / (FIGURE_13 + '.png')))
    names = sorted({name for task in bundle.tasks for name in task.images})
    for name in names:
        if name == FIGURE_13:
            continue
        matches = [p for p in (tex.parent / 'images').iterdir()
                   if p.stem == name and p.suffix.lower() in {'.jpg', '.jpeg', '.png'}]
        if len(matches) != 1:
            raise ValueError(f'Не найден однозначный файл рисунка: {name}')
        shutil.copyfile(matches[0], images / matches[0].name)
    bundle.diagnostics['feoktistov_recovered_figure'] = {
        'name': FIGURE_13, 'pdf_sha256': PDF_SHA256,
        'pdf_page': 108, 'printed_page': 107,
        'clip_points': [278, 76, 384, 240],
    }
    write_bundle(bundle, output)
    with zipfile.ZipFile(output / 'images.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            for path in images.iterdir():
                if path.stem == name:
                    archive.write(path, 'images/' + path.name)
    summary = {key: bundle.diagnostics[key] for key in (
        'unique_tasks', 'tasks_with_subitems', 'tasks_with_images',
        'tasks_with_author_answer', 'feoktistov_test_answer_count',
        'feoktistov_structure_issues', 'feoktistov_missing_answer_count',
        'feoktistov_missing_answers_by_work')}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tex', type=Path, required=True)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.tex, args.pdf, args.output)

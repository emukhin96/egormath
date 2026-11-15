#!/usr/bin/env python3
"""Папка рисунков для ZIP партии Ященко «36 вариантов ЕГЭ-2027».

Копирует картинки Mathpix и вырезает из скана PDF рисунки, которых нет в
выгрузке (``derived_figures`` в ``problems/data/yashchenko_structure.json``:
страница и рамка в пикселях 250 dpi). С ``--boxes`` печатает рамки
номеров заданий по страницам вариантов — по ним сверена привязка
рисунков ``figure_owners``.

    ./venv/bin/python tools/yashchenko_images.py \\
        --tex '/путь/Ященко ЕГЭ-2027 36 вариантов.tex' \\
        --images '/путь/images' --pdf '/путь/книга.pdf' --output tmp/yashchenko

Нужны ``pdftoppm`` (poppler) и Pillow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRUCTURE = ROOT / "public_html" / "problems" / "data" / "yashchenko_structure.json"
DPI = 250


def edition_for(tex: Path) -> dict:
    digest = hashlib.sha256(tex.read_bytes()).hexdigest()
    spec = json.loads(STRUCTURE.read_text(encoding="utf-8"))
    for edition in spec["editions"]:
        if edition["source_sha256"] == digest:
            return edition
    raise SystemExit(f"Нет описания издания для TEX с sha256 {digest}")


def render(pdf: Path, page: int, dpi: int, workdir: Path) -> Path:
    stem = workdir / f"p{page}-{dpi}"
    subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page),
                    "-png", "-singlefile", str(pdf), str(stem)], check=True)
    return stem.with_suffix(".png")


def task_boxes(path: Path, x_lo: int = 20, x_hi: int = 220) -> list[tuple[int, int]]:
    """Рамки номеров заданий на странице 110 dpi: ``(верх, низ)`` в пикселях.

    Скан наклонён, поэтому граница рамки — длинный отрезок в OR двух
    соседних строк, а стенки проверяются в окне ±3 пикселя.
    """
    from PIL import Image
    im = Image.open(path).convert("L")
    width, height = im.size
    px = im.load()
    dark = [[px[x, y] < 180 for x in range(x_lo, x_hi)] for y in range(height)]

    def longest(y):
        row = [a or b for a, b in zip(dark[y], dark[y + 1])]
        best = cur = start = best_start = 0
        for x, on in enumerate(row):
            if on:
                if cur == 0:
                    start = x
                cur += 1
                if cur > best:
                    best, best_start = cur, start
            else:
                cur = 0
        return best, best_start

    borders = []
    for y in range(height - 1):
        length, start = longest(y)
        if 45 <= length <= 80:
            borders.append((y, start, start + length - 1))
    lines: list[list[tuple[int, int, int]]] = []
    for border in borders:
        if lines and border[0] - lines[-1][-1][0] <= 2:
            lines[-1].append(border)
        else:
            lines.append([border])
    edges = [(g[0][0], min(b[1] for b in g), max(b[2] for b in g)) for g in lines]
    found = []
    i = 0
    while i < len(edges) - 1:
        (y, a0, a1), (y2, b0, b1) = edges[i], edges[i + 1]
        if 14 <= y2 - y <= 30 and abs(a0 - b0) <= 6 and abs(a1 - b1) <= 6:
            x0, x1 = min(a0, b0), max(a1, b1)

            def wall(xc):
                rows = range(y + 2, y2 - 1)
                return sum(any(dark[r][max(0, xc - 3):xc + 4]) for r in rows) / max(1, len(rows))
            if wall(x0 + 1) > .8 and wall(x1 - 1) > .8:
                found.append((y, y2))
                i += 2
                continue
        i += 1
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tex", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True,
                        help="папка images выгрузки Mathpix")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--boxes", action="store_true",
                        help="только напечатать рамки номеров по вариантам")
    args = parser.parse_args(argv)
    edition = edition_for(args.tex)
    pdf_digest = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    if pdf_digest != edition["pdf_sha256"]:
        raise SystemExit(f"Другой PDF: sha256 {pdf_digest}")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        if args.boxes:
            for variant in range(1, 37):
                first = 11 + 4 * (variant - 1)
                pages = []
                for page in range(first, first + 4):
                    pages.append((page, task_boxes(render(args.pdf, page, 110, work))))
                count = sum(len(b) for _p, b in pages)
                print(variant, count, json.dumps(pages))
            return 0
        target = args.output / "images"
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        for path in sorted(args.images.iterdir()):
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                shutil.copy2(path, target / path.name)
                copied += 1
        from PIL import Image
        for figure in edition.get("derived_figures", []):
            page = render(args.pdf, figure["page"], DPI, work)
            box = tuple(figure["box"])
            Image.open(page).convert("RGB").crop(box).save(
                target / f"{figure['name']}.jpg", quality=92)
        print(f"Скопировано {copied}, вырезано {len(edition.get('derived_figures', []))}: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

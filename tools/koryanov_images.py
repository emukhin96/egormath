#!/usr/bin/env python3
"""Папка рисунков для партии Корянова: картинки Mathpix плюс вырезки из PDF.

Рисунки «Рис. N» Mathpix вырезал сам (папка ``images`` рядом с TEX), кроме
тех, что он потерял, оставив подпись строкой. Сверенные правки ``crops`` в
``public_html/problems/data/koryanov_repairs.json`` задают страницу PDF и
прямоугольник в пунктах; утилита копирует картинки, на которые ссылаются
задачи пакета, и вырезает недостающие из PDF под именами из правок.

    ./venv/bin/python tools/koryanov_images.py \\
        --tex '/путь/к/Корянов ЕГЭ стереометрия.tex' \\
        --pdf '/путь/к/Корянов ЕГЭ стереометрия C2.pdf' \\
        --bundle tmp/koryanov-parse/import.json --output tmp/koryanov-parse

Затем ``tmp/koryanov-parse/images`` упаковывается в ZIP партии
(``--zip`` делает это сразу).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
REPAIRS = ROOT / "public_html" / "problems" / "data" / "koryanov_repairs.json"
CROP_DPI = 250  # как у вырезок Mathpix этой книги (≈ 2,5 пикселя на пункт × 72)


def edition_for(tex: Path) -> dict:
    digest = hashlib.sha256(tex.read_bytes()).hexdigest()
    data = json.loads(REPAIRS.read_text(encoding="utf-8"))
    for edition in data["editions"]:
        if edition["source_sha256"] == digest:
            return edition
    raise SystemExit(f"Нет сверенных правок для TEX с sha256 {digest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tex", required=True, type=Path)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zip", type=Path, help="Сразу упаковать images в этот ZIP")
    args = parser.parse_args(argv)

    edition = edition_for(args.tex)
    pdf_digest = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    if pdf_digest != edition["pdf_sha256"]:
        raise SystemExit(f"PDF не тот: sha256 {pdf_digest}")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    wanted = sorted({name for task in bundle["tasks"] for name in task.get("images", [])})
    source = args.tex.parent / "images"
    dest = args.output / "images"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    crops = {crop["name"]: crop for crop in edition.get("crops", [])}
    missing = []
    document = pymupdf.open(args.pdf)
    for name in wanted:
        if name in crops:
            crop = crops[name]
            page = document[crop["page"] - 1]
            pix = page.get_pixmap(dpi=CROP_DPI, clip=pymupdf.Rect(*crop["box_pt"]))
            pix.save(dest / f"{name}.png")
            continue
        matches = sorted(source.glob(f"{name}.*"))
        if not matches:
            missing.append(name)
            continue
        shutil.copy2(matches[0], dest / matches[0].name)
    if missing:
        print("Нет файлов: " + ", ".join(missing), file=sys.stderr)
        return 1
    if args.zip:
        args.zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(dest.iterdir()):
                archive.write(path, f"images/{path.name}")
    print(f"Рисунков: {len(wanted)} (вырезок из PDF: {sum(n in crops for n in wanted)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

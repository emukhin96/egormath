#!/usr/bin/env python3
"""ZIP рисунков для партии Смирнова: картинки Mathpix задач пакета.

У каждой задачи книги свой рисунок, Mathpix вырезал их все (папка
``images`` рядом с TEX). Утилита кладёт в ZIP только рисунки, на которые
ссылаются задачи пакета, и затирает белым пометки ручкой со скана —
прямоугольники в пикселях картинки из сверенной правки ``image_cleanups``
в ``public_html/problems/data/smirnov_repairs.json`` (по sha256 TEX).

    ./venv/bin/python tools/smirnov_images.py \\
        --tex '/путь/к/Смирнов стереометрия ЕГЭ.tex' \\
        --bundle tmp/smirnov-parse/import.json --output tmp/smirnov-parse \\
        --zip tmp/smirnov-parse/smirnov-images.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
REPAIRS = ROOT / "public_html" / "problems" / "data" / "smirnov_repairs.json"


def edition_for(tex: Path) -> dict:
    digest = hashlib.sha256(tex.read_bytes()).hexdigest()
    data = json.loads(REPAIRS.read_text(encoding="utf-8"))
    for edition in data["editions"]:
        if edition["source_sha256"] == digest:
            return edition
    raise SystemExit(f"Нет сверенных правок для TEX с sha256 {digest}")


def clean_image(source: Path, dest: Path, boxes: list[list[int]]) -> None:
    """Белые прямоугольники [x0, y0, x1, y1] (включительно) поверх пометок."""
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle(box, fill="white")
    image.save(dest, quality=95)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tex", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zip", type=Path, help="Сразу упаковать images в этот ZIP")
    args = parser.parse_args(argv)

    edition = edition_for(args.tex)
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    wanted = sorted({name for task in bundle["tasks"] for name in task.get("images", [])})
    cleanups = {item["image"]: item for item in edition.get("image_cleanups", [])}
    source = args.tex.resolve().parent / "images"
    dest = args.output / "images"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    missing = []
    for name in wanted:
        matches = sorted(source.glob(f"{name}.*"))
        if not matches:
            missing.append(name)
            continue
        if name in cleanups:
            clean_image(matches[0], dest / matches[0].name, cleanups[name]["boxes"])
        else:
            shutil.copy2(matches[0], dest / matches[0].name)
    if missing:
        print("Нет файлов: " + ", ".join(missing), file=sys.stderr)
        return 1
    if args.zip:
        args.zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(dest.iterdir()):
                archive.write(path, f"images/{path.name}")
    cleaned = sum(name in cleanups for name in wanted)
    print(f"Рисунков: {len(wanted)} (затёрты пометки: {cleaned})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

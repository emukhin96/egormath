#!/usr/bin/env python3
"""Папка рисунков для партии Волчкевича: картинки Mathpix плюс части полос.

Mathpix склеивает соседние рисунки учебника в одну полосу с одной подписью
(«» задача 15» над рисунками задач 14 и 15). Сверенные со сканом правки
``figures`` в ``public_html/problems/data/volchkevich_repairs.json`` называют
полосу и номер части слева направо; эта утилита копирует все картинки Mathpix
и вырезает части по белым столбцам под именами ``<файл>-2of3.jpg`` — их и
ставит в задачи профиль ``volchkevich``.

    ./venv/bin/python tools/volchkevich_images.py \\
        --tex '/путь/к/<uuid>.tex' --images '/путь/к/images' --output tmp/volchkevich-7

Затем ``tmp/volchkevich-7/images`` упаковывается в ZIP партии.
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

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REPAIRS = ROOT / "public_html" / "problems" / "data" / "volchkevich_repairs.json"

INK = 170          # темнее — «чернила»
MIN_INK = 0.004    # доля тёмных пикселей, с которой столбец не пустой
MIN_GAP = 25       # ширина белого промежутка между рисунками
MIN_PART = 40      # части уже — шум (тень с обратной стороны листа)
SCAN_DPI = 150     # разрешение страниц скана для ``pdf_box``


def segments(image: Image.Image, min_gap: int = MIN_GAP) -> list[tuple[int, int]]:
    """Отрезки непустых столбцов, разделённые белыми промежутками."""
    gray = image.convert("L")
    width, height = gray.size
    data = gray.tobytes()
    counts = [0] * width
    for y in range(height):
        row = data[y * width:(y + 1) * width]
        for x, value in enumerate(row):
            if value < INK:
                counts[x] += 1
    result = []
    start = end = None
    gap = 0
    for x, count in enumerate(counts):
        if count / height >= MIN_INK:
            if start is None:
                start = x
            end = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                result.append((start, end))
                start = None
                gap = 0
    if start is not None:
        result.append((start, end))
    return [(a, b) for a, b in result if b - a > MIN_PART]


def cut(image: Image.Image, repair: dict) -> Image.Image:
    """Часть полосы («2», «1-3» из ``of``) или прямоугольник ``box``."""
    if repair.get("box"):
        return image.crop(tuple(int(v) for v in repair["box"]))
    of = int(repair["of"])
    found = segments(image, int(repair.get("gap", MIN_GAP)))
    if len(found) != of:
        raise ValueError(f"ожидалось {of} частей, найдено {len(found)}: {found}")
    first, _, last = str(repair["part"]).partition("-")
    left = found[int(first) - 1][0]
    right = found[int(last or first) - 1][1]
    pad = 8
    return image.crop((max(0, left - pad), 0, min(image.width, right + pad + 1), image.height))


def derived_name(repair: dict) -> str:
    """То же имя, что ставит в задачи профиль (``derived_figure``)."""
    if repair.get("pdf_page"):
        return f"scan-{int(repair['pdf_page']):03d}-" + "_".join(
            str(int(v)) for v in repair["pdf_box"])
    if repair.get("box"):
        return f"{repair['file']}-box" + "_".join(str(int(v)) for v in repair["box"])
    return f"{repair['file']}-{repair['part']}of{repair['of']}"


def page_image(pdf: Path, page: int, cache: dict) -> Image.Image:
    """Страница скана при 150 dpi — в этих координатах записан ``pdf_box``."""
    if page not in cache:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(SCAN_DPI),
                            "-png", str(pdf), f"{tmp}/p"], check=True)
            [path] = Path(tmp).glob("p-*.png")
            with Image.open(path) as image:
                cache[page] = image.copy()
    return cache[page]


def figure_repairs(tex: Path) -> list[dict]:
    digest = hashlib.sha256(tex.read_text(encoding="utf-8").replace("\r\n", "\n")
                            .encode("utf-8")).hexdigest()
    spec = json.loads(REPAIRS.read_text(encoding="utf-8"))
    for edition in spec.get("editions", []):
        if edition.get("source_sha256") == digest:
            return list(edition.get("figures", []))
    raise SystemExit(f"Нет сверенных правок для TEX с sha256 {digest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tex", required=True, type=Path)
    parser.add_argument("--images", required=True, type=Path, help="папка images Mathpix")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pdf", type=Path, help="скан: для рисунков, которых нет у Mathpix")
    args = parser.parse_args(argv)
    pages: dict[int, Image.Image] = {}

    target = args.output / "images"
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for source in sorted(args.images.iterdir()):
        if source.is_file():
            shutil.copy2(source, target / source.name)
            copied += 1
    made = set()
    errors = []
    for repair in figure_repairs(args.tex):
        if not (repair.get("part") or repair.get("box") or repair.get("pdf_page")):
            continue
        name = derived_name(repair) + ".jpg"
        if name in made:
            continue
        if repair.get("pdf_page"):
            if not args.pdf:
                errors.append(f"{name}: нужен --pdf (рисунок вырезается из скана)")
                continue
            try:
                page_image(args.pdf, int(repair["pdf_page"]), pages).crop(
                    tuple(int(v) for v in repair["pdf_box"])).convert("RGB").save(
                        target / name, quality=92)
            except (OSError, subprocess.CalledProcessError) as error:
                errors.append(f"{name}: {error}")
                continue
            made.add(name)
            continue
        source = args.images / f"{repair['file']}.jpg"
        try:
            with Image.open(source) as image:
                cut(image, repair).convert("RGB").save(target / name, quality=92)
        except (OSError, ValueError) as error:
            errors.append(f"{name}: {error}")
            continue
        made.add(name)
    print(f"Скопировано {copied}, вырезано частей {len(made)}")
    for error in errors:
        print("Ошибка:", error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Миниатюры обложек задачников для полок «Подборок» (``Source.cover``).

Обложка — первая (или указанная) страница исходного PDF либо готовая
картинка, уменьшенная до ``COVER_SIZE`` и сохранённая в JPEG. Полка
показывает её в рамке 52×72; храним вчетверо крупнее (плотные экраны,
увеличение), но это всё равно около 20 КБ.

Список «источник → файл» — JSON для команды ``manage.py source_covers``::

    [{"match": "Зив-8", "file": "/…/Зив 8 алгебра.pdf", "page": 1}, …]

``match`` — часть названия источника без учёта регистра, необязательный
``author`` — часть поля «Автор» (у трёх «Геометрий» Волчкевича названия
почти одинаковые). Совпасть должен ровно один источник, иначе строка
пропускается с предупреждением.
"""
import io
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

COVER_SIZE = (208, 288)  # вчетверо больше рамки 52×72 по каждой стороне
JPEG_QUALITY = 82
PDF_SUFFIXES = {'.pdf'}


class CoverError(Exception):
    """Файл не прочитан или в PDF нет такой страницы."""


def _pdf_page_image(path, page):
    import pymupdf

    try:
        with pymupdf.open(path) as doc:
            if not 1 <= page <= doc.page_count:
                raise CoverError(f'в PDF {doc.page_count} стр., страницы {page} нет')
            pdf_page = doc[page - 1]
            # Масштаб — чтобы большая сторона была вдвое больше нужной:
            # потом уменьшаем Pillow с хорошим сглаживанием
            scale = 2 * max(COVER_SIZE[0] / pdf_page.rect.width,
                            COVER_SIZE[1] / pdf_page.rect.height)
            pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return Image.open(io.BytesIO(pixmap.tobytes('png')))
    except CoverError:
        raise
    except Exception as exc:  # pymupdf бросает свои типы на битых файлах
        raise CoverError(f'PDF не открылся: {exc}') from exc


def render_cover(path, page=1):
    """JPEG-байты обложки из PDF (страница ``page``, с 1) или картинки."""
    path = Path(path)
    if path.suffix.lower() in PDF_SUFFIXES:
        image = _pdf_page_image(path, page)
    else:
        try:
            image = Image.open(path)
            image.load()
        except (OSError, ValueError) as exc:
            raise CoverError(f'картинка не открылась: {exc}') from exc
    # MuPDF не декодирует часть сканов (JPX) и молча рисует белый лист
    if max(ImageStat.Stat(image.convert('L')).stddev) < 2:
        raise CoverError(f'страница {page} пустая — картинка не декодировалась?')
    # Ровно в пропорции рамки: срезается то же, что срезал бы object-fit
    image = ImageOps.fit(image.convert('RGB'), COVER_SIZE, Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, 'JPEG', quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def find_source(queryset, match, author=''):
    """Единственный источник, в названии которого есть ``match`` (и в
    авторе — ``author``), либо ``(None, причина)``. Если подходят
    несколько, но название одного из них совпадает целиком, берётся он.
    Сравнение в Python: ``icontains`` в SQLite не складывает регистр
    кириллицы, а источников — десятки."""
    match, author = match.casefold(), author.casefold()
    found = [source for source in queryset
             if match in source.title.casefold()
             and author in (source.author or '').casefold()]
    if len(found) > 1:
        found = [source for source in found if source.title.casefold() == match] or found
    if not found:
        return None, 'нет источника с таким названием'
    if len(found) > 1:
        return None, 'подходит несколько источников — уточните match или author'
    return found[0], ''

"""Клиент LaTeX API и кэш PDF листков.

API — тот же сервер, что у chgkmsu: POST /api/v1/compile-latex,
JSON {"api_key": ..., "tex_files": [{"team_id": ..., "tex_content": ...}]},
ответ {"success": true, "pdf_base64": "..."} либо описание ошибки.
"""

import base64
import hashlib
import logging
import time
from pathlib import Path

import requests
from django.conf import settings
from django.core.files.base import ContentFile

from .latex import EGOR_PACKAGE_RE, tex_hash, worksheet_to_tex
from .models import WorksheetPdf

logger = logging.getLogger(__name__)


class LatexCompileError(Exception):
    """Ошибка компиляции или недоступность LaTeX API."""

    def __init__(self, message, log=''):
        super().__init__(message)
        self.log = log


# Общий latex-api (ADR-003 chemolymp) ограничивает число одновременных
# сборок и сверх лимита отвечает 503 с Retry-After (429 — на всякий случай).
# Короткая очередь дешевле ошибки у учителя: ждём и повторяем, но не дольше
# LATEX_API_RETRY_BUDGET секунд на все попытки и паузы вместе — запрос
# держит поток gunicorn (timeout 180 с).
RETRY_STATUSES = (429, 503)


def _retry_delay(response, attempt):
    try:
        delay = float(response.headers.get('Retry-After', ''))
    except ValueError:
        delay = 2.0 * (attempt + 1)
    return max(0.5, min(delay, settings.LATEX_API_RETRY_MAX_DELAY))


def _post_with_retry(url, payload):
    # spent — время всех попыток и пауз: сам latex-api держит запрос до 30 с
    # в своей очереди, прежде чем ответить 503, и это тоже в счёт бюджета.
    spent = 0.0
    attempt = 0
    while True:
        started = time.monotonic()
        try:
            response = requests.post(
                url, json=payload, timeout=settings.LATEX_API_TIMEOUT)
        except requests.RequestException as exc:
            logger.error('LaTeX API недоступен: %s', exc)
            raise LatexCompileError(f'LaTeX API недоступен: {exc}')
        spent += time.monotonic() - started
        if response.status_code not in RETRY_STATUSES:
            return response
        delay = _retry_delay(response, attempt)
        if (attempt >= settings.LATEX_API_RETRIES
                or spent + delay > settings.LATEX_API_RETRY_BUDGET):
            logger.warning('LaTeX API занят (HTTP %s), попыток: %d',
                           response.status_code, attempt + 1)
            return response
        attempt += 1
        spent += delay
        logger.info('LaTeX API занят (HTTP %s), повтор %d через %.1f с',
                    response.status_code, attempt, delay)
        time.sleep(delay)


def compile_latex(tex_content, doc_id='doc', assets=None):
    """Компилирует .tex через удалённый API, возвращает байты PDF.

    assets — [{'filename': …, 'content_base64': …}] (картинки задач);
    без них payload не меняется (обратная совместимость с API).
    """
    if not settings.LATEX_API_KEY:
        raise LatexCompileError(
            'Не задан ключ LaTeX API (LATEX_API_KEY). '
            'Добавьте его в .secrets/ или переменные окружения.')
    tex_file = {'team_id': doc_id, 'tex_content': tex_content}
    if assets:
        tex_file['assets'] = assets
    payload = {
        'api_key': settings.LATEX_API_KEY,
        'tex_files': [tex_file],
    }
    url = settings.LATEX_API_URL.rstrip('/') + '/api/v1/compile-latex'
    response = _post_with_retry(url, payload)

    if response.status_code in RETRY_STATUSES:
        raise LatexCompileError(
            'LaTeX API занят другими сборками, попробуйте через минуту '
            f'(HTTP {response.status_code}).')
    if response.status_code == 401:
        raise LatexCompileError('LaTeX API отклонил ключ (401).')
    try:
        data = response.json()
    except ValueError:
        raise LatexCompileError(
            f'Неожиданный ответ LaTeX API (HTTP {response.status_code}).',
            log=response.text[:5000])

    if response.status_code != 200 or not data.get('success'):
        log = (data.get('log') or data.get('error')
               or data.get('detail') or response.text)
        raise LatexCompileError('Ошибка компиляции LaTeX.', log=str(log)[:20000])

    return base64.b64decode(data['pdf_base64'])


# Пакеты презентаций лежат в репозитории и уходят asset'ами в каталог сборки
# (API не ищет TEXMFLOCAL для неизвестных sty). Лимит API — 20 файлов.
LATEX_API_ASSET_LIMIT = 20
_BEAMER_TEX_DIR = Path(__file__).resolve().parent / 'tex'
EGORBEAMER_STY = _BEAMER_TEX_DIR / 'egorbeamer.sty'
EGORBEAMER_GRID_STY = _BEAMER_TEX_DIR / 'egorbeamer-grid.sty'
BEAMER_STY_ASSETS = (EGORBEAMER_STY, EGORBEAMER_GRID_STY)
BEAMER_IMAGE_ASSET_LIMIT = LATEX_API_ASSET_LIMIT - len(BEAMER_STY_ASSETS)
INTER_FONT_DIR = _BEAMER_TEX_DIR / 'fonts'
INTER_FONT_FILES = (
    'Inter-Regular.otf',
    'Inter-Bold.otf',
    'Inter-Italic.otf',
    'Inter-BoldItalic.otf',
)
# STIX Two (OFL, из TeX Live stix2-otf): текст + OpenType-математика для
# профиля font=stix пакета egor (fontspec + unicode-math). Имена файлов —
# как в TeX Live, чтобы egor.sty находил их и в сборке, и в texmf.
STIX_FONT_DIR = INTER_FONT_DIR
STIX_FONT_FILES = (
    'STIXTwoText-Regular.otf',
    'STIXTwoText-Italic.otf',
    'STIXTwoText-Bold.otf',
    'STIXTwoText-BoldItalic.otf',
    'STIXTwoMath-Regular.otf',
)
# Локальная копия пакета листков (вне репозитория) — чтобы font=inter/stix
# доезжал до API до обновления TEXMFLOCAL.
_EGOR_STY_CANDIDATES = (
    _BEAMER_TEX_DIR / 'egor.sty',
    Path.home() / 'Library/CloudStorage/Dropbox/code/LaTEX/egormath/egor.sty',
)


def _sty_asset(path):
    return {
        'filename': path.name,
        'content_base64': base64.b64encode(path.read_bytes()).decode(),
    }


def tex_wants_inter(tex):
    """True, если в исходнике выбран профиль font=inter."""
    return 'font=inter' in (tex or '').replace(' ', '')


def collect_inter_font_assets(*, required=False):
    """OTF Inter из worksheets/tex/fonts/.

    required=True — не молчать, если файлов нет: иначе font=inter
    уходит на API без шрифтов и sty тихо остаётся на CMU.
    """
    assets = []
    missing = []
    for name in INTER_FONT_FILES:
        path = INTER_FONT_DIR / name
        if path.is_file():
            assets.append(_sty_asset(path))
        else:
            missing.append(name)
    if required and missing:
        raise LatexCompileError(
            'Для шрифта Inter нужны файлы '
            + ', '.join(INTER_FONT_FILES)
            + ' в worksheets/tex/fonts/.')
    return assets


def _egor_sty_paths():
    """Локальный egor.sty, если он есть (иначе берётся из TEXMFLOCAL API)."""
    for path in _EGOR_STY_CANDIDATES:
        if path.is_file():
            return [path]
    return []


def _egor_sty_assets():
    return [_sty_asset(path) for path in _egor_sty_paths()]


def collect_inter_package_assets():
    """Inter OTF + egor.sty с опцией font=inter."""
    return collect_inter_font_assets() + _egor_sty_assets()


def tex_wants_stix(tex):
    """True, если в \\usepackage[...]{egor} выбран профиль font=stix."""
    match = EGOR_PACKAGE_RE.search(tex or '')
    options = ((match.group(1) if match else '') or '').split(',')
    return 'font=stix' in {opt.strip().replace(' ', '') for opt in options}


def collect_stix_package_assets():
    """OTF STIX Two + egor.sty с опцией font=stix.

    Шрифты обязательны: без них xelatex на API не найдёт STIX Two
    (если на сервере нет пакета stix2-otf) и сборка упадёт с невнятной
    ошибкой fontspec — лучше сказать об этом до отправки.
    """
    assets = []
    missing = []
    for name in STIX_FONT_FILES:
        path = STIX_FONT_DIR / name
        if path.is_file():
            assets.append(_sty_asset(path))
        else:
            missing.append(name)
    if missing:
        raise LatexCompileError(
            'Для шрифта STIX Two нужны файлы '
            + ', '.join(missing)
            + ' в worksheets/tex/fonts/.')
    return assets + _egor_sty_assets()


def collect_font_assets(tex):
    """Шрифты (и egor.sty) для профиля font= пакета egor, если они нужны."""
    if tex_wants_stix(tex):
        return collect_stix_package_assets()
    if tex_wants_inter(tex):
        return collect_inter_package_assets()
    return []


def _worksheet_images(worksheet, exclude_ids=None):
    """Картинки задач листка без повторов имён, только существующие файлы."""
    exclude_ids = set(exclude_ids or ())
    images = []
    seen = set()
    for item in worksheet.ordered_items():
        if item.pk in exclude_ids or not item.task_id:
            continue
        for image in item.task.images.all():
            name = image.filename
            if name in seen or not image.image.storage.exists(image.image.name):
                continue
            seen.add(name)
            images.append(image)
    return images


def font_asset_count(tex):
    """Сколько файлов из лимита API займут шрифты профиля font= (без чтения)."""
    if tex_wants_stix(tex):
        return len(STIX_FONT_FILES) + len(_egor_sty_paths())
    if tex_wants_inter(tex):
        fonts = sum((INTER_FONT_DIR / name).is_file() for name in INTER_FONT_FILES)
        return fonts + len(_egor_sty_paths())
    return 0


def collect_assets(worksheet, exclude_ids=None, tex=''):
    """Файлы картинок задач листка для передачи в LaTeX API.

    exclude_ids — скрытые элементы: их картинки не уходят в сборку,
    чтобы не подменять одноимённые файлы видимых задач и не раздувать запрос.
    tex — исходник сборки: при font=inter/stix добавляются OTF и egor.sty.
    """
    assets = []
    for image in _worksheet_images(worksheet, exclude_ids):
        with image.image.open('rb') as f:
            assets.append({
                'filename': image.filename,
                'content_base64': base64.b64encode(f.read()).decode(),
            })
    extra = collect_font_assets(tex)
    if extra:
        if len(assets) + len(extra) > LATEX_API_ASSET_LIMIT:
            raise LatexCompileError(
                'Слишком много картинок для сборки с выбранным шрифтом '
                f'(лимит {LATEX_API_ASSET_LIMIT - len(extra)} '
                'вместе со шрифтами).')
        assets = extra + assets
    return assets


def collect_beamer_assets(worksheet, exclude_ids=None, tex=''):
    """Картинки листка + sty презентаций для компиляции.

    Два sty занимают слоты из 20 на стороне API. Если картинок больше
    лимита — ошибка до сборки, без молчаливого отбрасывания файлов
    (иначе TeX ссылается на отсутствующие изображения).
    При font=inter дополнительно уходят OTF Inter.
    """
    extra = collect_inter_font_assets(required=True) if tex_wants_inter(tex) else []
    images = collect_assets(worksheet, exclude_ids=exclude_ids)
    limit = BEAMER_IMAGE_ASSET_LIMIT - len(extra)
    if len(images) > limit:
        raise LatexCompileError(
            'Слишком много картинок для презентации '
            f'(лимит {limit} вместе со стилевыми файлами).')
    return [_sty_asset(path) for path in BEAMER_STY_ASSETS] + extra + images


def _pdf_filter_key(exclude_ids):
    """Стабильный ключ набора скрытых элементов; пусто — полный листок."""
    ids = sorted({int(x) for x in (exclude_ids or ())})
    if not ids:
        return ''
    raw = ','.join(str(i) for i in ids).encode()
    return hashlib.sha1(raw).hexdigest()[:16]


def get_worksheet_pdf(worksheet, variant, exclude_ids=None):
    """PDF листка с кэшированием: перегенерация только при изменении .tex.

    exclude_ids — скрытые элементы конкретной ссылки/ученика. Кэш ключуется
    парой (filter_key, content_hash): разные наборы скрытий не вытесняют
    друг друга и полный вариант.
    """
    exclude_ids = set(exclude_ids or ())
    filter_key = _pdf_filter_key(exclude_ids)
    tex = worksheet_to_tex(worksheet, variant, exclude_ids=exclude_ids)
    if variant == WorksheetPdf.VARIANT_STUDENT and worksheet.student_pdf_options:
        from .latex import apply_pdf_options
        tex = apply_pdf_options(tex, worksheet.student_pdf_options)
        # Шрифт выбран, когда картинок было мало; если потом их добавили и
        # вместе со шрифтами они не влезают в лимит API — ученик получает
        # листок на CM, а не ошибку сборки. Решаем до ключа кэша.
        fonts = font_asset_count(tex)
        if fonts and (len(_worksheet_images(worksheet, exclude_ids)) + fonts
                      > LATEX_API_ASSET_LIMIT):
            logger.warning(
                'Листок %s: картинки не влезают в сборку со шрифтом %s, '
                'PDF ученика собирается на CM', worksheet.pk,
                worksheet.student_pdf_options.get('font'))
            tex = apply_pdf_options(tex, {'font': 'cm'})
    content_hash = tex_hash(tex)
    cached = WorksheetPdf.objects.filter(
        worksheet=worksheet, variant=variant,
        filter_key=filter_key, content_hash=content_hash,
    ).first()
    if cached and cached.file and cached.file.storage.exists(cached.file.name):
        return cached

    suffix = f'-{filter_key}' if filter_key else ''
    pdf_bytes = compile_latex(
        tex, doc_id=f'ws{worksheet.pk}-{variant}{suffix}',
        assets=collect_assets(worksheet, exclude_ids=exclude_ids, tex=tex))

    stale = WorksheetPdf.objects.filter(
        worksheet=worksheet, variant=variant, filter_key=filter_key)
    for old in stale:
        old.file.delete(save=False)
        old.delete()

    pdf = WorksheetPdf(
        worksheet=worksheet, variant=variant,
        content_hash=content_hash, filter_key=filter_key)
    pdf.file.save(
        f'worksheet-{worksheet.pk}-{variant}{suffix}.pdf',
        ContentFile(pdf_bytes), save=True)
    return pdf

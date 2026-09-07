"""Клиент LaTeX API и кэш PDF листков.

API — тот же сервер, что у chgkmsu: POST /api/v1/compile-latex,
JSON {"api_key": ..., "tex_files": [{"team_id": ..., "tex_content": ...}]},
ответ {"success": true, "pdf_base64": "..."} либо описание ошибки.
"""

import base64
import hashlib
import logging
from pathlib import Path

import requests
from django.conf import settings
from django.core.files.base import ContentFile

from .latex import tex_hash, worksheet_to_tex
from .models import WorksheetPdf

logger = logging.getLogger(__name__)


class LatexCompileError(Exception):
    """Ошибка компиляции или недоступность LaTeX API."""

    def __init__(self, message, log=''):
        super().__init__(message)
        self.log = log


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
    try:
        response = requests.post(
            url, json=payload, timeout=settings.LATEX_API_TIMEOUT)
    except requests.RequestException as exc:
        logger.error('LaTeX API недоступен: %s', exc)
        raise LatexCompileError(f'LaTeX API недоступен: {exc}')

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
_BEAMER_TEX_DIR = Path(__file__).resolve().parent / 'tex'
EGORBEAMER_STY = _BEAMER_TEX_DIR / 'egorbeamer.sty'
EGORBEAMER_GRID_STY = _BEAMER_TEX_DIR / 'egorbeamer-grid.sty'
BEAMER_STY_ASSETS = (EGORBEAMER_STY, EGORBEAMER_GRID_STY)
BEAMER_IMAGE_ASSET_LIMIT = 20 - len(BEAMER_STY_ASSETS)
INTER_FONT_DIR = _BEAMER_TEX_DIR / 'fonts'
INTER_FONT_FILES = (
    'Inter-Regular.otf',
    'Inter-Bold.otf',
    'Inter-Italic.otf',
    'Inter-BoldItalic.otf',
)
# Локальная копия пакета листков (вне репозитория) — чтобы font=inter
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


def collect_inter_font_assets():
    """Статические OTF Inter из worksheets/tex/fonts/ (если лежат локально)."""
    assets = []
    for name in INTER_FONT_FILES:
        path = INTER_FONT_DIR / name
        if path.is_file():
            assets.append(_sty_asset(path))
    return assets


def collect_inter_package_assets():
    """Inter OTF + egor.sty с опцией font=inter."""
    assets = collect_inter_font_assets()
    for path in _EGOR_STY_CANDIDATES:
        if path.is_file():
            assets.append(_sty_asset(path))
            break
    return assets


def collect_assets(worksheet, exclude_ids=None, tex=''):
    """Файлы картинок задач листка для передачи в LaTeX API.

    exclude_ids — скрытые элементы: их картинки не уходят в сборку,
    чтобы не подменять одноимённые файлы видимых задач и не раздувать запрос.
    tex — исходник черновой сборки: при font=inter добавляются OTF и egor.sty.
    """
    exclude_ids = set(exclude_ids or ())
    assets = []
    seen = set()
    for item in worksheet.ordered_items():
        if item.pk in exclude_ids or not item.task_id:
            continue
        for image in item.task.images.all():
            name = image.filename
            if name in seen or not image.image.storage.exists(image.image.name):
                continue
            seen.add(name)
            with image.image.open('rb') as f:
                assets.append({
                    'filename': name,
                    'content_base64': base64.b64encode(f.read()).decode(),
                })
    if tex_wants_inter(tex):
        extra = collect_inter_package_assets()
        if len(assets) + len(extra) > 20:
            raise LatexCompileError(
                'Слишком много картинок для сборки с Inter '
                f'(лимит {20 - len(extra)} вместе со шрифтами).')
        assets = extra + assets
    return assets


def collect_beamer_assets(worksheet, exclude_ids=None, tex=''):
    """Картинки листка + sty презентаций для компиляции.

    Два sty занимают слоты из 20 на стороне API. Если картинок больше
    лимита — ошибка до сборки, без молчаливого отбрасывания файлов
    (иначе TeX ссылается на отсутствующие изображения).
    При font=inter дополнительно уходят OTF Inter.
    """
    extra = collect_inter_font_assets() if tex_wants_inter(tex) else []
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
        assets=collect_assets(worksheet, exclude_ids=exclude_ids))

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

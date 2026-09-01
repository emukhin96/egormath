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


def collect_assets(worksheet, exclude_ids=None):
    """Файлы картинок задач листка для передачи в LaTeX API.

    exclude_ids — скрытые элементы: их картинки не уходят в сборку,
    чтобы не подменять одноимённые файлы видимых задач и не раздувать запрос.
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
    return assets


# Пакет презентаций лежит в репозитории и уходит asset'ом в каталог сборки
# (API не ищет TEXMFLOCAL для неизвестных sty). Лимит API — 20 файлов.
EGORBEAMER_STY = Path(__file__).resolve().parent / 'tex' / 'egorbeamer.sty'
BEAMER_IMAGE_ASSET_LIMIT = 19


def collect_beamer_assets(worksheet, exclude_ids=None):
    """Картинки листка + egorbeamer.sty для компиляции презентации."""
    sty = EGORBEAMER_STY.read_bytes()
    assets = [{
        'filename': 'egorbeamer.sty',
        'content_base64': base64.b64encode(sty).decode(),
    }]
    assets.extend(collect_assets(worksheet, exclude_ids=exclude_ids)[
        :BEAMER_IMAGE_ASSET_LIMIT])
    return assets


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

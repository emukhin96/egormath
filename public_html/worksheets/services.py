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

from .latex import tex_hash, worksheet_to_tex
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


# Наши пакеты и шрифты (worksheets/tex/) лежат на latex-api: .sty — в
# data/assets/egormath/ (виден через TEXINPUTS), OTF — в data/fonts/egormath/.
# Раскладывает их deploy/vps/deploy.sh, поэтому в запросе остаются только
# картинки задач. Лимит API — 20 файлов на документ.
LATEX_API_ASSET_LIMIT = 20
TEX_DIR = Path(__file__).resolve().parent / 'tex'
WORKSHEET_STY_FILES = ('egor.sty', 'egorweb.sty')
BEAMER_STY_FILES = ('egorbeamer.sty', 'egorbeamer-grid.sty')


def _file_asset(path):
    return {
        'filename': path.name,
        'content_base64': base64.b64encode(path.read_bytes()).decode(),
    }


def _local_sty_assets(names):
    """Пакеты из worksheets/tex/ — только при LATEX_SEND_STY (разработка).

    Так правки .sty видны на localhost до деплоя; на проде пакеты берутся
    с сервера и места в лимите файлов не занимают.
    """
    if not settings.LATEX_SEND_STY:
        return []
    return [_file_asset(TEX_DIR / name) for name in names]


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


def _image_assets(worksheet, exclude_ids, sty_assets):
    """Картинки листка после .sty; сверх лимита API — ошибка до сборки.

    Молча отбрасывать файлы нельзя: TeX сослался бы на отсутствующий рисунок.
    """
    images = _worksheet_images(worksheet, exclude_ids)
    limit = LATEX_API_ASSET_LIMIT - len(sty_assets)
    if len(images) > limit:
        raise LatexCompileError(
            f'Слишком много картинок для одной сборки: {len(images)}, '
            f'лимит LaTeX API — {limit}.')
    assets = list(sty_assets)
    for image in images:
        with image.image.open('rb') as f:
            assets.append({
                'filename': image.filename,
                'content_base64': base64.b64encode(f.read()).decode(),
            })
    return assets


def collect_assets(worksheet, exclude_ids=None):
    """Файлы для сборки листка: картинки задач (и .sty при разработке).

    exclude_ids — скрытые элементы: их картинки не уходят в сборку,
    чтобы не подменять одноимённые файлы видимых задач и не раздувать запрос.
    """
    return _image_assets(
        worksheet, exclude_ids,
        _local_sty_assets(WORKSHEET_STY_FILES))


def collect_beamer_assets(worksheet, exclude_ids=None):
    """Файлы для сборки презентации: картинки (и egorbeamer*.sty при разработке)."""
    return _image_assets(
        worksheet, exclude_ids, _local_sty_assets(BEAMER_STY_FILES))


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

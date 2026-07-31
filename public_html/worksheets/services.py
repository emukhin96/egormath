"""Клиент LaTeX API и кэш PDF листков.

API — тот же сервер, что у chgkmsu: POST /api/v1/compile-latex,
JSON {"api_key": ..., "tex_files": [{"team_id": ..., "tex_content": ...}]},
ответ {"success": true, "pdf_base64": "..."} либо описание ошибки.
"""

import base64
import logging

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


def compile_latex(tex_content, doc_id='doc'):
    """Компилирует .tex через удалённый API, возвращает байты PDF."""
    if not settings.LATEX_API_KEY:
        raise LatexCompileError(
            'Не задан ключ LaTeX API (LATEX_API_KEY). '
            'Добавьте его в .secrets/ или переменные окружения.')
    payload = {
        'api_key': settings.LATEX_API_KEY,
        'tex_files': [{'team_id': doc_id, 'tex_content': tex_content}],
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


def get_worksheet_pdf(worksheet, variant):
    """PDF листка с кэшированием: перегенерация только при изменении .tex."""
    tex = worksheet_to_tex(worksheet, variant)
    content_hash = tex_hash(tex)
    cached = WorksheetPdf.objects.filter(
        worksheet=worksheet, variant=variant, content_hash=content_hash,
    ).first()
    if cached and cached.file and cached.file.storage.exists(cached.file.name):
        return cached

    pdf_bytes = compile_latex(tex, doc_id=f'ws{worksheet.pk}-{variant}')

    # Устаревшие версии этого варианта больше не нужны
    for old in WorksheetPdf.objects.filter(worksheet=worksheet, variant=variant):
        old.file.delete(save=False)
        old.delete()

    pdf = WorksheetPdf(
        worksheet=worksheet, variant=variant, content_hash=content_hash)
    pdf.file.save(
        f'worksheet-{worksheet.pk}-{variant}.pdf',
        ContentFile(pdf_bytes), save=True)
    return pdf

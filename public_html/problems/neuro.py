"""Нейрогенерация ответов и решений задач (Gemini API, REST).

Единая точка — solve_task(): собирает промпт из условия и подпунктов,
запрашивает у модели структурированный JSON и возвращает черновики
ответов/решений. Черновики нигде не сохраняются автоматически — они
попадают в редактируемые поля формы, и в базу уходит только то,
что оператор оставил после проверки.

Ключ — GEMINI_API_KEY из .secrets/ или окружения (как LATEX_API_KEY),
модель — settings.GEMINI_MODEL (по умолчанию gemini-3.5-flash-lite).
"""

import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .latex_utils import (loads_neuro_json, restore_json_eaten_latex,
                          wrap_bare_math)

logger = logging.getLogger(__name__)

GEMINI_URL = ('https://generativelanguage.googleapis.com/v1beta/'
              'models/%s:generateContent')

# Предохранитель от случайной отправки огромных текстов (и большого счёта)
MAX_TASK_CHARS = 8000

_INSTRUCTION = (
    'Ты — учитель математики. Реши задачу и верни JSON с полями:\n'
    '- answer: краткий ответ,\n'
    '- solution: краткое решение (основные шаги, без воды),\n'
    '- subitem_answers, subitem_solutions: массивы по подпунктам.\n'
    'Если в запросе есть блок «Подпункты» — заполняй только массивы '
    '(по одному элементу на каждый, в том же порядке), а answer и '
    'solution оставь пустыми строками. Если блока «Подпункты» нет — '
    'это одна задача: пиши ответ и разбор в answer и solution. '
    'Случаи параметра тоже туда, не выдумывай подпункты '
    '(массивы оставь пустыми).\n'
    'Каждую формулу оборачивай в $…$, даже одну: '
    '$a=\\pm\\frac{4}{5}$, не пиши a = \\pm \\frac{4}{5} без долларов. '
    'Совместимо с amsmath/egor. Текст — по-русски. '
    'Если решить не удаётся, верни пустые строки.'
)

_RESPONSE_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'answer': {'type': 'STRING'},
        'solution': {'type': 'STRING'},
        'subitem_answers': {'type': 'ARRAY', 'items': {'type': 'STRING'}},
        'subitem_solutions': {'type': 'ARRAY', 'items': {'type': 'STRING'}},
    },
    'required': ['answer', 'solution',
                 'subitem_answers', 'subitem_solutions'],
}


class NeuroError(Exception):
    """Ошибка нейрогенерации с сообщением, пригодным для показа учителю."""


class NeuroQuotaError(NeuroError):
    """Превышен лимит частоты или параллелизма."""


def _api_key():
    """Ключ из настроек: GEMINI_API_KEY или запасной GOOGLE_API_KEY."""
    return (getattr(settings, 'GEMINI_API_KEY', '')
            or getattr(settings, 'GOOGLE_API_KEY', '')
            or '')


def acquire_quota(user):
    """Один одновременный запрос и N вызовов в минуту на учителя.

    Возвращает метку in_flight_at — её же передают в release_quota,
    чтобы 429 чужого запроса не снял блокировку текущего.
    """
    from problems.models import NeuroSolveQuota
    now = timezone.now()
    limit = getattr(settings, 'GEMINI_RATE_PER_MINUTE', 20)
    lock_sec = getattr(settings, 'GEMINI_TIMEOUT', 60) + 15
    with transaction.atomic():
        quota, _ = NeuroSolveQuota.objects.select_for_update().get_or_create(
            user=user,
            defaults={'window_started': now, 'window_count': 0})
        if (quota.in_flight_at
                and (now - quota.in_flight_at).total_seconds() < lock_sec):
            raise NeuroQuotaError(
                'Подождите: предыдущая генерация ещё идёт.')
        if now - quota.window_started >= timedelta(minutes=1):
            quota.window_started = now
            quota.window_count = 0
        if quota.window_count >= limit:
            raise NeuroQuotaError(
                'Слишком много запросов к нейросети, подождите минуту.')
        quota.window_count += 1
        quota.in_flight_at = now
        quota.save(update_fields=[
            'window_started', 'window_count', 'in_flight_at'])
        quota.refresh_from_db(fields=['in_flight_at'])
        return quota.in_flight_at


def release_quota(user, started_at):
    """Снять блокировку только того запроса, который её взял."""
    from problems.models import NeuroSolveQuota
    NeuroSolveQuota.objects.filter(
        user=user, in_flight_at=started_at).update(in_flight_at=None)


def _build_prompt(text, subitems):
    lines = [_INSTRUCTION, '', 'Задача:', text.strip()]
    if subitems:
        lines.append('')
        lines.append('Подпункты:')
        for i, sub in enumerate(subitems):
            lines.append('%d) %s' % (i + 1, sub.strip()))
    return '\n'.join(lines)


def solve_task(text, subitems=()):
    """Черновики ответа/решения задачи от нейросети.

    Возвращает {'answer', 'solution', 'subitem_answers',
    'subitem_solutions'} (строки и списки строк). Бросает NeuroError
    при любой проблеме: нет ключа, сбой сети, невалидный ответ модели.
    """
    api_key = _api_key()
    if not api_key:
        raise NeuroError(
            'Нейрогенерация не настроена: нет ключа API '
            '(.secrets/GEMINI_API_KEY или переменная GEMINI_API_KEY / '
            'GOOGLE_API_KEY). Перезапустите сервер после добавления ключа.')
    subitems = [s for s in (subitems or []) if s.strip()]
    total = len(text) + sum(len(s) for s in subitems)
    if not text.strip():
        raise NeuroError('Пустое условие задачи.')
    if total > MAX_TASK_CHARS:
        raise NeuroError('Задача слишком длинная для нейрогенерации.')

    payload = {
        'contents': [{'parts': [{'text': _build_prompt(text, subitems)}]}],
        'generationConfig': {
            'response_mime_type': 'application/json',
            'response_schema': _RESPONSE_SCHEMA,
        },
    }
    try:
        response = requests.post(
            GEMINI_URL % settings.GEMINI_MODEL,
            json=payload,
            headers={'x-goog-api-key': api_key},
            timeout=settings.GEMINI_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('Gemini API недоступен: %s', exc)
        raise NeuroError('Сервис нейрогенерации недоступен, '
                         'попробуйте позже.') from exc
    if response.status_code != 200:
        logger.warning('Gemini API: HTTP %s %s',
                       response.status_code, response.text[:500])
        detail = ''
        try:
            payload = response.json()
            err = payload.get('error') if isinstance(payload, dict) else None
            if isinstance(err, dict):
                detail = err.get('message') or ''
        except (ValueError, AttributeError, TypeError):
            detail = ''
        if not isinstance(detail, str):
            detail = ''
        if response.status_code in (401, 403) or 'API key' in detail:
            raise NeuroError(
                'Ключ Gemini отклонён сервером. Проверьте GEMINI_API_KEY.')
        if response.status_code == 404:
            hint = detail or ('модель %s' % settings.GEMINI_MODEL)
            raise NeuroError(
                'Модель нейросети недоступна: %s. '
                'Проверьте GEMINI_MODEL.' % hint[:240])
        raise NeuroError('Сервис нейрогенерации вернул ошибку '
                         f'(HTTP {response.status_code}).')
    try:
        raw = response.json()['candidates'][0]['content']['parts'][0]['text']
        data = loads_neuro_json(raw)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning('Gemini API: неожиданный формат ответа: %s',
                       response.text[:500])
        raise NeuroError('Не удалось разобрать ответ нейросети.') from exc

    result = _normalize_drafts(data, subitems)
    if not (result['answer'] or result['solution']
            or any(result['subitem_answers'])
            or any(result['subitem_solutions'])):
        raise NeuroError(
            'Нейросеть не вернула ответ. Попробуйте ещё раз.')
    return result


def _s(value):
    if not isinstance(value, str):
        return ''
    return restore_json_eaten_latex(value).strip()


def _lst(value, length):
    items = [_s(v) for v in value] if isinstance(value, list) else []
    # Приводим к числу подпунктов: лишнее отрезаем, недостающее — пустое
    return (items + [''] * length)[:length]


def _normalize_drafts(data, subitems):
    """Собрать черновики. Ложные «подпункты» (случаи параметра) —
    в answer/solution, если у задачи подпунктов нет."""
    if not isinstance(data, dict):
        data = {}
    answer = _s(data.get('answer'))
    solution = _s(data.get('solution'))
    raw_ans = data.get('subitem_answers')
    raw_sol = data.get('subitem_solutions')
    if subitems:
        return {
            'answer': wrap_bare_math(answer),
            'solution': wrap_bare_math(solution),
            'subitem_answers': [wrap_bare_math(v)
                               for v in _lst(raw_ans, len(subitems))],
            'subitem_solutions': [wrap_bare_math(v)
                                 for v in _lst(raw_sol, len(subitems))],
        }
    extra_ans = [_s(v) for v in raw_ans] if isinstance(raw_ans, list) else []
    extra_sol = [_s(v) for v in raw_sol] if isinstance(raw_sol, list) else []
    extra_ans = [v for v in extra_ans if v]
    extra_sol = [v for v in extra_sol if v]
    if not answer and extra_ans:
        answer = '; '.join(extra_ans)
    if not solution and extra_sol:
        solution = '\n\n'.join(extra_sol)
    return {
        'answer': wrap_bare_math(answer),
        'solution': wrap_bare_math(solution),
        'subitem_answers': [],
        'subitem_solutions': [],
    }


def apply_result(task, result, overwrite=False):
    """Записать черновик в рабочие поля задачи.

    Пустые значения модели пропускаем. Непустое поле не затираем, пока
    overwrite=False — чтобы не снести проверенный ответ.
    """
    subs = list(task.subitems.order_by('order', 'pk'))
    answers = result.get('subitem_answers') or []
    solutions = result.get('subitem_solutions') or []
    if subs:
        for i, sub in enumerate(subs):
            fields = []
            ans = answers[i] if i < len(answers) else ''
            sol = solutions[i] if i < len(solutions) else ''
            if ans and (overwrite or not sub.answer_latex.strip()):
                sub.answer_latex = ans
                fields.append('answer_latex')
            if sol and (overwrite or not sub.solution_latex.strip()):
                sub.solution_latex = sol
                fields.append('solution_latex')
            if fields:
                sub.save(update_fields=fields)
        return
    fields = []
    ans = result.get('answer') or ''
    sol = result.get('solution') or ''
    if ans and (overwrite or not task.answer_latex.strip()):
        task.answer_latex = ans
        fields.append('answer_latex')
    if sol and (overwrite or not task.solution_latex.strip()):
        task.solution_latex = sol
        fields.append('solution_latex')
    if fields:
        task.save(update_fields=fields)

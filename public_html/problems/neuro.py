"""Нейрогенерация ответов и решений задач (Gemini API, REST).

Единая точка — solve_task(): собирает промпт из условия и подпунктов,
запрашивает у модели структурированный JSON и возвращает черновики
ответов/решений. Черновики нигде не сохраняются автоматически — они
попадают в редактируемые поля формы, и в базу уходит только то,
что оператор оставил после проверки.

Ключ — GEMINI_API_KEY из .secrets/ или окружения (как LATEX_API_KEY),
модель — settings.GEMINI_MODEL (по умолчанию gemini-2.5-flash-lite,
самый дешёвый разумный вариант: ~0.04 цента на типовую задачу).
"""

import json
import logging

import requests
from django.conf import settings

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
    'Если у задачи есть подпункты — заполняй только массивы (по одному '
    'элементу на каждый подпункт, в том же порядке), а answer и solution '
    'оставь пустыми строками. Если подпунктов нет — заполняй answer и '
    'solution, а массивы оставь пустыми.\n'
    'Формулы — в LaTeX ($…$), совместимом с пакетами amsmath/egor. '
    'Текст — по-русски. Если решить не удаётся, верни пустые строки.'
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
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise NeuroError(
            'Нейрогенерация не настроена: нет ключа GEMINI_API_KEY '
            '(файл .secrets/GEMINI_API_KEY или переменная окружения).')
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
        raise NeuroError('Сервис нейрогенерации вернул ошибку '
                         f'(HTTP {response.status_code}).')
    try:
        raw = response.json()['candidates'][0]['content']['parts'][0]['text']
        data = json.loads(raw)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning('Gemini API: неожиданный формат ответа: %s',
                       response.text[:500])
        raise NeuroError('Не удалось разобрать ответ нейросети.') from exc

    def _s(value):
        return value.strip() if isinstance(value, str) else ''

    def _lst(value, length):
        items = [_s(v) for v in value] if isinstance(value, list) else []
        # Приводим к числу подпунктов: лишнее отрезаем, недостающее — пустое
        return (items + [''] * length)[:length]

    return {
        'answer': _s(data.get('answer')),
        'solution': _s(data.get('solution')),
        'subitem_answers': _lst(data.get('subitem_answers'), len(subitems)),
        'subitem_solutions': _lst(data.get('subitem_solutions'),
                                  len(subitems)),
    }

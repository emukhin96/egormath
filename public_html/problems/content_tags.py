"""Разметка задач фасетом CONTENT («Содержание задачи»).

Каркас этапа 07.11.2026: словарь — ``content_data.py`` (черновик, ждёт
решений Егора), здесь — промпт AI-классификатора пакетами, разбор ответа
и запись значений задаче. Классификатор возвращает только коды из
словаря; всё прочее отбрасывается и попадает в отчёт.

Сеть вызывается через ``call(prompt) -> str``: команда
``label_content`` передаёт вызов Gemini по настройкам сайта, пилот на
слепке прода — свой; тесты — заглушку.
"""

import json
import re

import requests
from django.conf import settings
from django.db import transaction

from .content_data import (CONTENT_FACET_CODE, CONTENT_GROUPS,
                           content_codes)
from .latex_utils import loads_neuro_json

# Сколько символов условия и решения отдаём модели на задачу: длиннее —
# дороже и почти никогда не меняет ответ (конструкции видны в начале).
TEXT_LIMIT = 1500
SOLUTION_LIMIT = 500
BATCH_SIZE = 15

_INSTRUCTION = (
    'Ты — методист по математике. Для каждой задачи ниже выбери из '
    'словаря коды объектов и конструкций, которые в ней есть. Это не '
    'тема задачи, а то, что в ней встречается: модуль в квадратном '
    'уравнении, трапеция в задаче на площадь, выколотая точка на графике.\n'
    'Правила:\n'
    '- ставь код, только если конструкция явно есть в условии или без '
    'неё не решить задачу (решение дано для подсказки);\n'
    '- несколько кодов можно, ни одного — тоже (пустой список);\n'
    '- только коды из словаря, ничего не придумывай;\n'
    '- если у задачи подпункты, объединяй коды всех подпунктов;\n'
    '- модуль и корень: в уравнении — *_EQ, в неравенстве — *_INEQ, '
    'в функции или графике — ABS_GRAPH; ABS_EXPR — только когда нет '
    'ни уравнения, ни неравенства, ни графика;\n'
    '- DOMAIN_KEY — только если без учёта ОДЗ ответ получится неверным '
    '(посторонние корни отсеиваются), а не при любом упоминании ОДЗ;\n'
    '- EQ_ROOT_SELECT — только если условие требует корни из промежутка;\n'
    '- TRIG_ONE_KNOWN — дано значение одной функции угла; другое '
    'соотношение (sin a + cos a = m) — это EXPR_COND_VALUE;\n'
    '- коды ST_* — только пространственные задачи, GEO_COORD_FIG — '
    'только плоскость.\n'
    'Верни JSON: {"items": [{"id": <id>, "codes": ["КОД", …]}, …]} — '
    'по одному элементу на каждую задачу, в том же порядке.'
)

_RESPONSE_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'items': {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'id': {'type': 'INTEGER'},
                    'codes': {'type': 'ARRAY', 'items': {'type': 'STRING'}},
                },
                'required': ['id', 'codes'],
            },
        },
    },
    'required': ['items'],
}


class ContentLabelError(Exception):
    """Сбой классификатора: сеть, формат ответа."""


def vocabulary_text(groups=None):
    """Словарь для промпта: группа, затем «КОД — название: когда ставить»."""
    lines = []
    for _gcode, gname, values in groups or CONTENT_GROUPS:
        lines.append(f'## {gname}')
        for code, name, when, _overlap in values:
            lines.append(f'{code} — {name}: {when}')
    return '\n'.join(lines)


def _clip(text, limit):
    text = re.sub(r'\s+', ' ', text or '').strip()
    return text if len(text) <= limit else text[:limit] + ' …'


def task_block(item):
    """Текст одной задачи для промпта.

    item — словарь: id, text, subitems (список строк), answer, solution.
    """
    parts = [f'### id={item["id"]}', _clip(item.get('text'), TEXT_LIMIT)]
    for i, sub in enumerate(item.get('subitems') or [], start=1):
        if (sub or '').strip():
            parts.append(f'{i}) {_clip(sub, 400)}')
    if (item.get('answer') or '').strip():
        parts.append('Ответ: ' + _clip(item['answer'], 300))
    if (item.get('solution') or '').strip():
        parts.append('Решение: ' + _clip(item['solution'], SOLUTION_LIMIT))
    return '\n'.join(parts)


def build_prompt(items, groups=None):
    return (_INSTRUCTION + '\n\nСЛОВАРЬ\n' + vocabulary_text(groups)
            + '\n\nЗАДАЧИ\n' + '\n\n'.join(task_block(i) for i in items))


def parse_response(raw, ids, valid_codes=None):
    """Ответ модели → ({id: [коды]}, отброшенные коды).

    Неизвестные коды и id вне пакета отбрасываются; задача, которой нет
    в ответе, в результат не попадает (её надо переспросить).
    """
    valid = set(valid_codes or content_codes())
    wanted = set(ids)
    try:
        data = loads_neuro_json(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        raise ContentLabelError('Ответ модели — не JSON.') from exc
    items = data.get('items') if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ContentLabelError('В ответе нет списка items.')
    labels, dropped = {}, []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        try:
            task_id = int(entry.get('id'))
        except (TypeError, ValueError):
            continue
        if task_id not in wanted:
            continue
        codes = []
        for code in entry.get('codes') or []:
            code = str(code).strip().upper()
            if code in valid:
                if code not in codes:
                    codes.append(code)
            else:
                dropped.append(code)
        labels[task_id] = codes
    return labels, dropped


def classify(items, call, groups=None):
    """Один пакет задач → ({id: [коды]}, отброшенные коды)."""
    raw = call(build_prompt(items, groups))
    return parse_response(raw, [i['id'] for i in items])


def gemini_call(prompt, *, model=None, timeout=None):
    """Вызов Gemini по настройкам сайта (ключ, прокси), ответ — JSON-текст."""
    api_key = (getattr(settings, 'GEMINI_API_KEY', '')
               or getattr(settings, 'GOOGLE_API_KEY', ''))
    if not api_key:
        raise ContentLabelError('Нет ключа GEMINI_API_KEY.')
    model = model or settings.GEMINI_MODEL
    base = (settings.GEMINI_API_BASE or
            'https://generativelanguage.googleapis.com').strip().rstrip('/')
    headers = {'x-goog-api-key': api_key}
    if settings.GEMINI_API_BASE and settings.GEMINI_PROXY_SECRET:
        headers['X-Egor-Proxy-Secret'] = settings.GEMINI_PROXY_SECRET
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'response_mime_type': 'application/json',
            'response_schema': _RESPONSE_SCHEMA,
            'maxOutputTokens': 8192,
            'temperature': 0,
        },
    }
    try:
        response = requests.post(
            f'{base}/v1beta/models/{model}:generateContent',
            json=payload, headers=headers,
            timeout=timeout or settings.GEMINI_TIMEOUT * 2)
    except requests.RequestException as exc:
        raise ContentLabelError(f'Сеть: {exc.__class__.__name__}') from exc
    if response.status_code != 200:
        raise ContentLabelError(f'HTTP {response.status_code}')
    try:
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError, ValueError) as exc:
        raise ContentLabelError('Неожиданный формат ответа.') from exc


def task_item(task):
    """Task из базы → словарь для task_block."""
    subitems = list(task.subitems.all())
    return {
        'id': task.pk,
        'text': task.text_latex,
        'subitems': [s.text_latex for s in subitems],
        'answer': task.author_answer_latex or task.answer_latex,
        'solution': task.author_solution_latex or task.solution_latex,
    }


def content_values_by_code():
    from .models import FacetValue
    return {v.code: v for v in FacetValue.objects.filter(
        facet_type__code=CONTENT_FACET_CODE, parent__isnull=False)}


@transaction.atomic
def apply_labels(labels, *, replace=False):
    """Записать значения CONTENT задачам: {task_id: [коды]}.

    Трогает только значения фасета CONTENT: остальные фасеты (уровень,
    метод) не меняются. replace=True снимает прежние значения CONTENT,
    которых нет в новом списке; по умолчанию только добавляет.
    Возвращает счётчики {'tasks', 'added', 'removed', 'unknown'}.
    """
    from .models import Task
    by_code = content_values_by_code()
    content_pks = {v.pk for v in by_code.values()}
    stats = {'tasks': 0, 'added': 0, 'removed': 0, 'unknown': 0}
    tasks = Task.objects.filter(pk__in=list(labels)).prefetch_related(
        'facet_values')
    for task in tasks:
        wanted = []
        for code in labels.get(task.pk) or []:
            value = by_code.get(code)
            if value is None:
                stats['unknown'] += 1
            else:
                wanted.append(value)
        current = {v.pk for v in task.facet_values.all()
                   if v.pk in content_pks}
        add = [v for v in wanted if v.pk not in current]
        if add:
            task.facet_values.add(*add)
            stats['added'] += len(add)
        if replace:
            drop = current - {v.pk for v in wanted}
            if drop:
                task.facet_values.remove(*drop)
                stats['removed'] += len(drop)
        stats['tasks'] += 1
    return stats


def load_labels(path):
    """Файл разметки: {"<id>": ["КОД", …]} или JSONL-строки {"id", "codes"}."""
    with open(path, encoding='utf-8') as fh:
        text = fh.read().strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        data = None              # несколько строк JSONL
    if isinstance(data, dict) and 'id' not in data:
        return {int(k): list(v) for k, v in data.items()}
    labels = {}
    for line in text.splitlines():
        if line.strip():
            row = json.loads(line)
            labels[int(row['id'])] = list(row.get('codes') or [])
    return labels

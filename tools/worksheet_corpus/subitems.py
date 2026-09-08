"""Ответы и решения по подпунктам черновика корпуса."""

from __future__ import annotations

import re

CYRILLIC_LABELS = 'абвгдежзиклмнопрстуфхцчшщэюя'

_LABEL_SPLIT_RE = re.compile(
    r'(?:(?<=^)|(?<=[\n;.])|(?<=\s)|(?<=\\\\)|\\par\b)\s*'
    r'(?:\()?'
    r'(?P<label>[a-zA-Zа-яА-ЯёЁ]|[1-9]\d?)'
    r'\)\s*',
    re.M,
)
_ITEM_SPLIT_RE = re.compile(r'\\item(?:\[[^\]]*\])?\s*')


def subitem_label(index: int) -> str:
    if 0 <= index < len(CYRILLIC_LABELS):
        return CYRILLIC_LABELS[index]
    return str(index + 1)


def pad_list(values, n: int) -> list[str]:
    items = [str(v) if v is not None else '' for v in (values or [])]
    if len(items) < n:
        items.extend([''] * (n - len(items)))
    return items[:n]


def ensure_subitem_fields(el: dict) -> dict:
    if el.get('kind') != 'task':
        return el
    n = len(el.get('subitems') or [])
    el['subitem_answers'] = pad_list(el.get('subitem_answers'), n)
    el['subitem_solutions'] = pad_list(el.get('subitem_solutions'), n)
    return el


def attach_subitem_rows(draft: dict) -> None:
    for el in draft.get('elements') or []:
        ensure_subitem_fields(el)
        if el.get('kind') != 'task':
            continue
        subs = el.get('subitems') or []
        el['subitem_rows'] = [{
            'label': subitem_label(j),
            'text': subs[j],
            'answer': el['subitem_answers'][j],
            'solution': el['subitem_solutions'][j],
        } for j in range(len(subs))]


def _split_top_level(text: str, sep: str) -> list[str]:
    """Режет по sep вне $...$ и {...}."""
    parts = []
    buf = []
    depth = 0
    math = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '\\' and i + 1 < n:
            buf.append(ch)
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == '$':
            math = not math
            buf.append(ch)
            i += 1
            continue
        if not math:
            if ch == '{':
                depth += 1
            elif ch == '}' and depth:
                depth -= 1
            elif depth == 0 and text.startswith(sep, i):
                chunk = ''.join(buf).strip()
                if chunk:
                    parts.append(chunk)
                buf = []
                i += len(sep)
                continue
        buf.append(ch)
        i += 1
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _norm_label(label: str) -> str:
    value = (label or '').lower().replace('ё', 'е')
    aliases = {
        'а': 'a', 'a': 'a',
        'б': 'b', 'b': 'b',
        'в': 'c', 'c': 'c',
        'г': 'd', 'd': 'd',
        'д': 'e',
        'е': 'f', 'e': 'f',
        'ж': 'g',
        'з': 'h',
    }
    return aliases.get(value, value)


def split_labeled(text: str, n: int | None = None) -> list[str] | None:
    raw = (text or '').strip()
    if not raw:
        return None
    matches = list(_LABEL_SPLIT_RE.finditer(raw))
    if len(matches) < 2:
        return None
    if n:
        picked = []
        cursor = -1
        for i in range(n):
            want = _norm_label(subitem_label(i))
            found = None
            for match in matches:
                if match.start() <= cursor:
                    continue
                if _norm_label(match.group('label')) == want:
                    found = match
                    break
            if found is None:
                return None
            picked.append(found)
            cursor = found.start()
        matches = picked
    elif matches[0].start() > 0 and raw[:matches[0].start()].strip():
        return None
    parts = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        chunk = raw[match.end():end].strip().rstrip(';').strip()
        chunk = re.sub(r'^(?:\\\\)+', '', chunk).strip()
        chunk = re.sub(r'^\\par\b\s*', '', chunk).strip()
        parts.append(chunk)
    if any(not p for p in parts):
        return None
    return parts


def split_math_list(text: str, n: int) -> list[str] | None:
    """Список значений внутри одной формулы: $a;\\ b;\\ c$."""
    raw = (text or '').strip()
    if n <= 1 or not raw:
        return None
    inner = raw
    wrapped = False
    if raw.startswith('$') and raw.endswith('$') and raw.count('$') == 2:
        inner = raw[1:-1].strip()
        wrapped = True
    parts = [p.strip() for p in re.split(r';\s*(?:\\\s*)?', inner) if p.strip()]
    if len(parts) != n:
        return None
    if wrapped:
        return ['$%s$' % p.strip() for p in parts]
    return parts


def split_items(text: str) -> list[str] | None:
    raw = (text or '').strip()
    if r'\item' not in raw:
        return None
    parts = [p.strip() for p in _ITEM_SPLIT_RE.split(raw) if p.strip()]
    return parts or None


def split_pile(text: str, n: int) -> list[str] | None:
    """Пытается разрезать общую кучу на n кусков. Иначе None."""
    if n <= 0:
        return None
    raw = (text or '').strip()
    if not raw:
        return None
    if n == 1:
        return [raw]
    labeled = split_labeled(raw, n)
    if labeled and len(labeled) == n:
        return labeled
    math_list = split_math_list(raw, n)
    if math_list:
        return math_list
    items = split_items(raw)
    if items and len(items) == n:
        return items
    for sep in ('; ', ';', '\n\n', r'\\'):
        parts = [p.strip().rstrip(';').strip()
                 for p in _split_top_level(raw, sep) if p.strip()]
        if len(parts) == n:
            return parts
    return None


def join_subitem_answers(el: dict) -> str:
    parts = []
    for i, ans in enumerate(el.get('subitem_answers') or []):
        ans = (ans or '').strip()
        if ans:
            parts.append('%s)~%s' % (subitem_label(i), ans))
    return '; '.join(parts)


def join_subitem_solutions(el: dict) -> str:
    parts = []
    for i, sol in enumerate(el.get('subitem_solutions') or []):
        sol = (sol or '').strip()
        if sol:
            parts.append('%s)~%s' % (subitem_label(i), sol))
    return '\n\n'.join(parts)


def filled_count(values) -> int:
    return sum(1 for v in (values or []) if str(v).strip())


def maybe_split_element(el: dict) -> bool:
    """Раскладывает кучу answer/solution по пунктам, если это однозначно.

    Возвращает True, если что-то разложил.
    """
    if el.get('kind') != 'task':
        return False
    subs = el.get('subitems') or []
    n = len(subs)
    if n == 0:
        return False
    ensure_subitem_fields(el)
    changed = False
    if filled_count(el.get('subitem_answers')) < n:
        split = split_pile(el.get('answer') or '', n)
        if split:
            el['subitem_answers'] = split
            el['answer'] = ''
            changed = True
    if filled_count(el.get('subitem_solutions')) < n:
        split = split_pile(el.get('solution') or '', n)
        if split:
            el['subitem_solutions'] = split
            el['solution'] = ''
            changed = True
    if filled_count(el.get('subitem_answers')) == n and (el.get('answer') or '').strip():
        if split_pile(el.get('answer') or '', n):
            el['answer'] = ''
            changed = True
    if filled_count(el.get('subitem_solutions')) == n and (el.get('solution') or '').strip():
        if split_pile(el.get('solution') or '', n):
            el['solution'] = ''
            changed = True
    return changed


def needs_subitem_regen(el: dict) -> bool:
    if el.get('kind') != 'task' or el.get('skip'):
        return False
    n = len(el.get('subitems') or [])
    if n == 0:
        return False
    ensure_subitem_fields(el)
    return (
        filled_count(el.get('subitem_answers')) < n
        or filled_count(el.get('subitem_solutions')) < n
    )


def apply_subitem_payload(el: dict, answers=None, solutions=None) -> None:
    n = len(el.get('subitems') or [])
    if n == 0:
        return
    if answers is not None:
        el['subitem_answers'] = pad_list(answers, n)
        if filled_count(el['subitem_answers']) == n:
            el['answer'] = ''
    if solutions is not None:
        el['subitem_solutions'] = pad_list(solutions, n)
        if filled_count(el['subitem_solutions']) == n:
            el['solution'] = ''
    if filled_count(el.get('subitem_answers')):
        el['answer_origin'] = el.get('answer_origin') or 'neuro'

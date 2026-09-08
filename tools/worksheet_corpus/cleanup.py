"""Постобработка корпуса: вёрстка, пунктуация подпунктов, ответы."""

from __future__ import annotations

import re

from .latex_scan import strip_layout_space, strip_subitem_punct

PROOF_EXACT_RE = re.compile(
    r'(?is)^\s*(?:\$\\s*)?(?:доказано|доказательство|'
    r'что\s+и\s+требовалось\s+доказать|'
    r'ч\.\s*т\.\s*д\.?|чтд|qed|см\.\s*решение|очевидно)'
    r'\s*\.?\s*(?:\$\s*)?$')
EMPTY_LABEL_RE = re.compile(r'(?i)(?:^|[;]\s*)[а-яa-z]\)\s*(?=[;,]|$)')
SOLVE_EQ_RE = re.compile(
    r'(?i)(?:решите|решить|найдите\s+корн|найдите\s+корень|'
    r'корни\s+уравнен|корень\s+уравнен|уравнен[ияе]\s*[:.]?\s*$)')
NOT_ROOT_RE = re.compile(
    r'(?i)параметр|\bпри\s+каком\b|\bпри\s+каких\b|\bсколько\b|'
    r'произведен\w*\s+корн|сумм[аыуе]\s+корн|'
    r'неравенств|систем[аыу]\s+уравнен')
NO_ROOTS_RE = re.compile(
    r'(?i)^\s*(?:нет\s+(?:корней|решений)|пустое\s+множество|'
    r'\\emptyset|∅|\\varnothing)\s*$')
VAR_PREF = 'xyztnabkmwpq'


def clean_text(text: str) -> str:
    return strip_layout_space(text or '')


def clean_subitem_text(text: str) -> str:
    return strip_subitem_punct(strip_layout_space(text or ''))


def is_nonsense_answer(text: str) -> bool:
    return bool(PROOF_EXACT_RE.match((text or '').strip()))


def clean_answer_junk(text: str) -> str:
    """Убирает «доказано» и аналоги; осмысленный остаток сохраняет."""
    raw = (text or '').strip()
    if not raw:
        return ''
    if is_nonsense_answer(raw):
        return ''
    if not re.search(
            r'(?i)доказано|требовалось доказать|доказательство', raw):
        return raw
    out = re.sub(r'(?i)что\s+и\s+требовалось\s+доказать', ' ', raw)
    out = re.sub(r'(?i)\s*\(?\s*доказано\s*\)?', ' ', out)
    out = re.sub(r'(?i)доказательство', ' ', out)
    out = EMPTY_LABEL_RE.sub(' ', out)
    out = re.sub(r'^[:\s;]+', '', out)
    out = re.sub(r'[:\s;]+$', '', out)
    out = re.sub(r'\s{2,}', ' ', out).strip()
    if is_nonsense_answer(out) or not out:
        return ''
    return out


def _looks_like_equation(text: str) -> bool:
    blob = text or ''
    if NOT_ROOT_RE.search(blob):
        return False
    if SOLVE_EQ_RE.search(blob):
        return True
    stripped = strip_layout_space(blob)
    if stripped.startswith('$') and '=' in stripped and len(stripped) < 220:
        if re.search(r'(?i)найдите|вычислите|упростите|сократите', stripped):
            return False
        return True
    return False


def equation_variable(text: str) -> str:
    """Буква неизвестной из уравнения; по умолчанию x."""
    body = text or ''
    body = re.sub(r'\\[a-zA-Z]+\*?', ' ', body)
    body = re.sub(r'[^A-Za-z]', ' ', body)
    found = [tok.lower() for tok in body.split() if len(tok) == 1]
    if not found:
        return 'x'
    rank = {ch: i for i, ch in enumerate(VAR_PREF)}
    return sorted(set(found), key=lambda c: rank.get(c, 99))[0]


def _unwrap_dollars(text: str) -> tuple[str, bool]:
    raw = (text or '').strip()
    had = '$' in raw
    inner = raw.replace('$$', '$')
    if inner.startswith('$') and inner.endswith('$') and inner.count('$') == 2:
        inner = inner[1:-1].strip()
    else:
        inner = inner.replace('$', '').strip()
    return inner, had


def _split_top_semicolons(text: str) -> list[str]:
    parts = []
    buf = []
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '\\' and i + 1 < n:
            buf.append(ch)
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == '{':
            depth += 1
        elif ch == '}' and depth:
            depth -= 1
        elif ch == ';' and depth == 0:
            chunk = ''.join(buf).strip()
            if chunk:
                parts.append(chunk)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)
    return parts or ([text.strip()] if text.strip() else [])


def _expand_pm(piece: str) -> list[str]:
    text = (piece or '').strip()
    if not text:
        return []
    m = re.match(r'^\\pm\s*(.+)$', text)
    if m:
        body = m.group(1).strip()
        return [body, '-' + body if not body.startswith('-') else body[1:]]
    m = re.match(r'^(.+?)\\pm\s*(.+)$', text)
    if m and '\\frac' not in m.group(1)[-8:]:
        left, right = m.group(1).strip(), m.group(2).strip()
        if left.endswith('+') or left.endswith('-'):
            return [text]
        return [f'{left}+{right}', f'{left}-{right}']
    return [text]


def _already_assigned(piece: str, var: str) -> bool:
    return bool(re.match(rf'(?i)^\$?{re.escape(var)}\s*=', (piece or '').strip()))


def rewrite_equation_answer(prompt: str, answer: str,
                            context: str | None = None) -> str:
    """Числовые корни уравнения — в виде x=…; x=… ."""
    raw = (answer or '').strip()
    if not raw:
        return raw
    if not _looks_like_equation(context or prompt):
        return raw
    if NO_ROOTS_RE.match(raw.replace('$', '').strip()):
        return raw
    inner, had_math = _unwrap_dollars(raw)
    if not inner:
        return raw
    if re.match(r'(?i)[a-z]\\in\b|[a-z]\s*[<>≤≥]', inner):
        return raw
    var = equation_variable(prompt)
    pieces = []
    for part in _split_top_semicolons(inner):
        part = re.sub(r'^(?:\\[ ,]+|\s)+', '', part or '').rstrip(',')
        if not part:
            continue
        if _already_assigned(part, var):
            pieces.append(part)
            continue
        pieces.extend(_expand_pm(part))
    if not pieces:
        return raw
    assigned = []
    for piece in pieces:
        piece = re.sub(r'^(?:\\[ ,]+|\s)+', '', (piece or '').strip())
        if not piece:
            continue
        if _already_assigned(piece, var):
            piece = re.sub(
                rf'(?i)^({re.escape(var)}\s*=)\s*(?:\\[ ,]+)*',
                r'\1', piece)
            assigned.append(piece)
        else:
            assigned.append(f'{var}={piece}')
    joined = '; '.join(assigned)
    if had_math or '\\' in joined:
        return f'${joined}$'
    return joined


def _task_prompt(el: dict, index: int | None = None) -> str:
    stem = el.get('text') or ''
    subs = el.get('subitems') or []
    if index is None:
        return stem + ' ' + ' '.join(subs)
    chunk = subs[index] if index < len(subs) else ''
    # Соседние подпункты («решите уравнение» / «укажите корни на отрезке»)
    # нужны, чтобы ответ «на отрезке» тоже считался корнями уравнения.
    return f'{stem} {chunk} ' + ' '.join(subs)


def clean_task_element(el: dict) -> dict:
    if el.get('kind') == 'text':
        el['text'] = clean_text(el.get('text') or '')
        return el
    if el.get('kind') != 'task':
        return el
    el['text'] = clean_text(el.get('text') or '')
    el['subitems'] = [clean_subitem_text(s) for s in (el.get('subitems') or [])]
    el['choices'] = [clean_text(s) for s in (el.get('choices') or [])]
    junk_cleared = False
    if el.get('subitems'):
        answers = list(el.get('subitem_answers') or [])
        while len(answers) < len(el['subitems']):
            answers.append('')
        new_ans = []
        for i, ans in enumerate(answers[:len(el['subitems'])]):
            cleaned = clean_answer_junk(ans)
            if cleaned != (ans or '').strip():
                junk_cleared = True
            cleaned = rewrite_equation_answer(
                f"{el.get('text') or ''} {el['subitems'][i]}",
                cleaned,
                context=_task_prompt(el, i))
            new_ans.append(cleaned)
        el['subitem_answers'] = new_ans
        if (el.get('answer') or '').strip():
            leftover = clean_answer_junk(el.get('answer') or '')
            # Общий ответ при подпунктах не нужен, если он только «доказано».
            if not leftover or leftover != (el.get('answer') or '').strip():
                if not leftover or is_nonsense_answer(el.get('answer') or ''):
                    el['answer'] = ''
                    junk_cleared = True
    else:
        cleaned = clean_answer_junk(el.get('answer') or '')
        if cleaned != (el.get('answer') or '').strip():
            junk_cleared = True
        cleaned = rewrite_equation_answer(_task_prompt(el), cleaned)
        el['answer'] = cleaned
    if junk_cleared and el.get('answer_origin') == 'neuro' and not (
            el.get('answer') or '').strip() and not any(
                (a or '').strip() for a in (el.get('subitem_answers') or [])):
        el['answer_origin'] = ''
    return el


def clean_draft(draft: dict) -> dict:
    for el in draft.get('elements') or []:
        clean_task_element(el)
    return draft

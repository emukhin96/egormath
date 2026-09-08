"""Дописать пустые пункты leftover, не затирая уже заполненные."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from worksheet_corpus.paths import OUTPUT_DIR
from worksheet_corpus.store import load_draft, save_draft
from worksheet_corpus.subitems import apply_subitem_payload, ensure_subitem_fields, filled_count

LEFTOVER_PATH = OUTPUT_DIR / 'subitem-leftover.json'


def _load_leftover(grades):
    data = json.loads(LEFTOVER_PATH.read_text(encoding='utf-8'))
    return {(row['id'], row['i']): row for row in data if row.get('grade') in grades}


def apply_hole_items(items, *, grades=(6, 7), origin='agent'):
    leftover = _load_leftover(grades)
    by_id = {}
    for row in items:
        by_id.setdefault(row['id'], []).append(row)
    filled = 0
    for did, rows in by_id.items():
        draft = load_draft(did)
        if not draft:
            print(f'MISS draft {did}', file=sys.stderr)
            continue
        if draft.get('status') in ('skipped', 'imported'):
            print(f'SKIP draft {did}', file=sys.stderr)
            continue
        els = draft.get('elements') or []
        for row in rows:
            i = row['i']
            if i >= len(els):
                print(f'BAD index {did}#{i}', file=sys.stderr)
                continue
            el = els[i]
            if el.get('kind') != 'task' or el.get('skip'):
                print(f'SKIP {did}#{i}', file=sys.stderr)
                continue
            ensure_subitem_fields(el)
            n = len(el.get('subitems') or [])
            lo = leftover.get((did, i), {})
            lo_ans = list(lo.get('subitem_answers') or [])
            new_ans = list(row.get('subitem_answers') or [])
            merged_ans = []
            for j in range(n):
                old = lo_ans[j] if j < len(lo_ans) else ''
                if str(old).strip():
                    merged_ans.append(old)
                else:
                    merged_ans.append(new_ans[j] if j < len(new_ans) else '')
            lo_fs = int(lo.get('fs') or 0)
            new_sols = list(row.get('subitem_solutions') or [])
            if lo_fs >= n and n > 0:
                cur = list(el.get('subitem_solutions') or [])
                merged_sols = []
                for j in range(n):
                    old = cur[j] if j < len(cur) else ''
                    if str(old).strip():
                        merged_sols.append(old)
                    else:
                        merged_sols.append(new_sols[j] if j < len(new_sols) else '')
            else:
                merged_sols = new_sols
            apply_subitem_payload(el, answers=merged_ans, solutions=merged_sols)
            el['answer_origin'] = origin
            warn = (row.get('warning') or '').strip()
            if warn:
                warns = list(el.get('warnings') or [])
                if warn not in warns:
                    warns.append(warn)
                el['warnings'] = warns
            filled += 1
        save_draft(draft)
        print(f'SAVED {did} n={len(rows)}')
    print(f'FILLED {filled}')
    return filled

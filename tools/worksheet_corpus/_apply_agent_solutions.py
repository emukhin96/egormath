"""Применить answer/solution к черновикам. Не коммитить."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from worksheet_corpus.store import load_draft, save_draft
from worksheet_corpus.subitems import apply_subitem_payload, ensure_subitem_fields


def apply_solutions(items, *, origin='neuro'):
    """items: list of {id, i, answer, solution, warning?}."""
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
            if row.get('subitem_answers') or row.get('subitem_solutions'):
                apply_subitem_payload(
                    el,
                    answers=row.get('subitem_answers'),
                    solutions=row.get('subitem_solutions'))
                el['answer_origin'] = origin
            else:
                el['answer'] = row['answer']
                el['solution'] = row['solution']
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

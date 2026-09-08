#!/usr/bin/env python3
"""Дописать ответы/решения в JSON-черновики корпуса (не skipped/imported)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'public_html'))

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from problems.neuro import NeuroError
from worksheet_corpus.store import iter_draft_paths, load_json, save_draft
from worksheets.corpus_solve import apply_neuro_to_element


def needs_solve(el):
    if el.get('kind') != 'task' or el.get('skip'):
        return False
    return not ((el.get('answer') or '').strip()
                and (el.get('solution') or '').strip())


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int)
    parser.add_argument('--contains')
    parser.add_argument('--grade', type=int)
    parser.add_argument('--sleep', type=float, default=2.0)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args(argv)
    needle = (args.contains or '').lower()
    budget = args.limit
    filled = 0
    errors = 0
    for path in iter_draft_paths():
        draft = load_json(path)
        if not draft or draft.get('status') in ('skipped', 'imported'):
            continue
        if needle and needle not in (draft.get('id') or '').lower():
            continue
        if args.grade is not None and draft.get('grade') != args.grade:
            continue
        changed = False
        for index, el in enumerate(draft.get('elements') or []):
            if budget is not None and budget <= 0:
                break
            if not needs_solve(el) and not args.overwrite:
                continue
            if args.overwrite and (el.get('kind') != 'task' or el.get('skip')):
                continue
            try:
                apply_neuro_to_element(el, overwrite=args.overwrite)
                filled += 1
                changed = True
                print(f'OK {draft["id"]}#{index}', flush=True)
            except NeuroError as exc:
                errors += 1
                changed = True
                print(f'FAIL {draft["id"]}#{index}: {exc}', file=sys.stderr,
                      flush=True)
            save_draft(draft)
            if budget is not None:
                budget -= 1
            if args.sleep:
                time.sleep(args.sleep)
        if changed:
            save_draft(draft)
        if budget is not None and budget <= 0:
            break
    print(f'Готово: задач {filled}, ошибок {errors}.', flush=True)
    return 1 if errors and not filled else 0


if __name__ == '__main__':
    raise SystemExit(main())

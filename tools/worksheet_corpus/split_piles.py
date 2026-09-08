"""Раскладывает уже записанные кучи ответов по подпунктам."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from worksheet_corpus.store import iter_draft_paths, load_json, save_draft
from worksheet_corpus.subitems import (
    ensure_subitem_fields, maybe_split_element, needs_subitem_regen)


def split_all_drafts():
    split = 0
    leftover = []
    touched = 0
    for path in iter_draft_paths():
        draft = load_json(path)
        if not draft or draft.get('status') in ('skipped', 'imported'):
            continue
        changed = False
        for i, el in enumerate(draft.get('elements') or []):
            if el.get('kind') != 'task' or el.get('skip'):
                continue
            ensure_subitem_fields(el)
            if maybe_split_element(el):
                changed = True
                split += 1
            if needs_subitem_regen(el):
                leftover.append((draft['id'], i, len(el.get('subitems') or [])))
        if changed:
            save_draft(draft)
            touched += 1
    return {'drafts': touched, 'split': split, 'leftover': leftover}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Разложить кучи ответов/решений по подпунктам.')
    parser.parse_args(argv)
    stats = split_all_drafts()
    print(
        f'Разложено задач: {stats["split"]}, '
        f'листков: {stats["drafts"]}, '
        f'осталось без явных пунктов: {len(stats["leftover"])}.')
    for did, index, n in stats['leftover'][:40]:
        print(f'  {did}#{index} ({n} п.)')
    if len(stats['leftover']) > 40:
        print(f'  … ещё {len(stats["leftover"]) - 40}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

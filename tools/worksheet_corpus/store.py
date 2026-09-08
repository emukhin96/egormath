"""Чтение и запись JSON-артефактов. Ручные правки не затираются."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import (OUTPUT_DIR, assets_dir, inventory_json_path, parsed_dir)


def ensure_dirs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parsed_dir().mkdir(parents=True, exist_ok=True)
    assets_dir().mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open(encoding='utf-8') as fh:
        return json.load(fh)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
    tmp.replace(path)


def draft_id(rel_path: str) -> str:
    text = rel_path.replace('\\', '/')
    text = re.sub(r'\.tex$', '', text, flags=re.I)
    return text


def draft_json_path(draft_id_value: str) -> Path:
    safe = draft_id_value.replace('..', '')
    return parsed_dir() / (safe + '.json')


def draft_tex_path(draft_id_value: str) -> Path:
    safe = draft_id_value.replace('..', '')
    return parsed_dir() / (safe + '.egor.tex')


def iter_draft_paths():
    root = parsed_dir()
    if not root.exists():
        return
    for path in sorted(root.rglob('*.json')):
        yield path


def load_draft(draft_id_value: str) -> dict | None:
    path = draft_json_path(draft_id_value)
    return load_json(path)


def save_draft(draft: dict):
    path = draft_json_path(draft['id'])
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json(path, draft)


def merge_inventory(old, new_files):
    """Сохраняет ручной verdict/reason по rel_path."""
    overrides = {}
    if old:
        overrides = old.get('overrides') or {}
        for row in old.get('files') or []:
            rel = row.get('rel_path')
            if rel and row.get('manual'):
                overrides[rel] = {
                    'verdict': row.get('verdict'),
                    'reason': row.get('reason', ''),
                }
    files = []
    for row in new_files:
        rel = row['rel_path']
        if rel in overrides:
            row = dict(row)
            row['verdict'] = overrides[rel].get('verdict', row['verdict'])
            row['reason'] = overrides[rel].get('reason', row.get('reason', ''))
            row['manual'] = True
        files.append(row)
    return {
        'schema_version': 1,
        'overrides': overrides,
        'files': files,
    }


def load_inventory():
    data = load_json(inventory_json_path(), default=None)
    if not data:
        return {'schema_version': 1, 'overrides': {}, 'files': []}
    return data

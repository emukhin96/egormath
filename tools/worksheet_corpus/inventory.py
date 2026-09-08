"""Сканирование семи папок классов → inventory.json и отчёт."""

from __future__ import annotations

from collections import Counter

from .detect import inspect_file
from .paths import (corpus_roots, inventory_json_path, inventory_md_path)
from .store import ensure_dirs, load_inventory, merge_inventory, save_json


def scan_corpus(roots=None):
    roots = list(roots or corpus_roots())
    files = []
    for grade, root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob('*.tex')):
            if path.name.startswith('.'):
                continue
            files.append(inspect_file(path, grade, root))
    return files


def write_inventory(files, old=None):
    ensure_dirs()
    bundle = merge_inventory(old or load_inventory(), files)
    save_json(inventory_json_path(), bundle)
    inventory_md_path().write_text(
        render_inventory_md(bundle['files']), encoding='utf-8')
    return bundle


def render_inventory_md(files):
    by_verdict = Counter(row['verdict'] for row in files)
    by_dialect = Counter(row['dialect'] for row in files)
    by_grade = Counter(row.get('grade') for row in files)
    lines = [
        '# Инвентарь авторских листков',
        '',
        f'Всего файлов: **{len(files)}**.',
        '',
        '## Вердикты',
        '',
    ]
    for key in ('include', 'review', 'skip'):
        lines.append(f'- `{key}`: {by_verdict.get(key, 0)}')
    lines.extend(['', '## Диалекты', ''])
    for dialect, count in by_dialect.most_common():
        lines.append(f'- `{dialect}`: {count}')
    lines.extend(['', '## По классам', ''])
    for grade in sorted(g for g in by_grade if g is not None):
        subset = [r for r in files if r.get('grade') == grade]
        inc = sum(1 for r in subset if r['verdict'] == 'include')
        rev = sum(1 for r in subset if r['verdict'] == 'review')
        sk = sum(1 for r in subset if r['verdict'] == 'skip')
        lines.append(
            f'- {grade} класс: {len(subset)} '
            f'(include {inc}, review {rev}, skip {sk})')
    lines.extend(['', '## К проверке (`review`)', ''])
    reviews = [r for r in files if r['verdict'] == 'review']
    if not reviews:
        lines.append('Нет.')
    else:
        lines.append('| Путь | Диалект | Заголовок | Причина |')
        lines.append('| --- | --- | --- | --- |')
        for row in reviews[:200]:
            title = (row.get('title') or '').replace('|', '/')
            reason = (row.get('reason') or '').replace('|', '/')
            lines.append(
                f'| `{row["rel_path"]}` | {row["dialect"]} | {title} | {reason} |')
        if len(reviews) > 200:
            lines.append(f'| … | | | ещё {len(reviews) - 200} |')
    lines.extend(['', '## Включённые (первые 80)', ''])
    included = [r for r in files if r['verdict'] == 'include']
    lines.append('| Путь | Диалект | Заголовок | task/item |')
    lines.append('| --- | --- | --- | --- |')
    for row in included[:80]:
        title = (row.get('title') or '').replace('|', '/')
        lines.append(
            f'| `{row["rel_path"]}` | {row["dialect"]} | {title} | '
            f'{row.get("n_task", 0)}/{row.get("n_item", 0)} |')
    if len(included) > 80:
        lines.append(f'| … | | | ещё {len(included) - 80} |')
    lines.append('')
    return '\n'.join(lines)


def summarize(files):
    return {
        'total': len(files),
        'include': sum(1 for r in files if r['verdict'] == 'include'),
        'review': sum(1 for r in files if r['verdict'] == 'review'),
        'skip': sum(1 for r in files if r['verdict'] == 'skip'),
        'dialects': dict(Counter(r['dialect'] for r in files)),
        'grades': dict(Counter(r.get('grade') for r in files)),
    }

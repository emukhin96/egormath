"""CLI: inventory / parse / classify / report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .detect import detect_dialect, grade_from_path
from .inventory import scan_corpus, summarize, write_inventory
from .parse import ParseError, parse_and_store
from .paths import PROJECT_ROOT, corpus_roots, inventory_md_path
from .store import draft_id, load_draft, load_inventory


def django_setup():
    public_html = PROJECT_ROOT / 'public_html'
    if str(public_html) not in sys.path:
        sys.path.insert(0, str(public_html))
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    import django
    django.setup()


def cmd_inventory(_args):
    files = scan_corpus()
    bundle = write_inventory(files)
    stats = summarize(bundle['files'])
    print(
        f'Инвентарь: {stats["total"]} файлов, '
        f'include {stats["include"]}, review {stats["review"]}, '
        f'skip {stats["skip"]}.')
    print(f'Отчёт: {inventory_md_path()}')
    return 0


def _selected_inventory_rows(args):
    bundle = load_inventory()
    rows = bundle.get('files') or []
    if args.only:
        rows = [r for r in rows if r.get('verdict') == args.only]
    if args.grade:
        rows = [r for r in rows if r.get('grade') == args.grade]
    if args.contains:
        needle = args.contains.lower()
        rows = [r for r in rows if needle in (r.get('rel_path') or '').lower()]
    return rows


def cmd_parse(args):
    django_setup()
    rows = _selected_inventory_rows(args)
    if args.path:
        extra = []
        for raw in args.path:
            path = Path(raw)
            if not path.is_file():
                print(f'Нет файла: {path}', file=sys.stderr)
                continue
            grade = grade_from_path(path)
            rel = path.name
            extra.append({
                'path': str(path),
                'rel_path': rel,
                'grade': grade,
                'dialect': detect_dialect(path.read_text(encoding='utf-8',
                                                        errors='replace'),
                                          path),
                'verdict': 'include',
            })
        rows = extra + rows
    ok = 0
    failed = 0
    for row in rows:
        if row.get('verdict') == 'skip' and not args.force:
            continue
        existing = load_draft(draft_id(row.get('rel_path') or ''))
        if (existing and existing.get('status') in ('skipped', 'imported')
                and not args.force):
            continue
        path = Path(row['path'])
        try:
            draft = parse_and_store(
                path, rel_path=row['rel_path'], grade=row.get('grade'),
                dialect=row.get('dialect'), force=args.force)
            n_tasks = sum(1 for el in draft['elements'] if el['kind'] == 'task')
            print(f'OK {draft["id"]}: {n_tasks} задач ({draft["dialect"]})')
            ok += 1
        except (ParseError, OSError, ValueError) as exc:
            print(f'FAIL {row.get("rel_path")}: {exc}', file=sys.stderr)
            try:
                from .parse import store_failed_draft
                store_failed_draft(
                    path, rel_path=row.get('rel_path') or path.name,
                    grade=row.get('grade'),
                    dialect=row.get('dialect') or '',
                    error=exc)
            except OSError:
                pass
            failed += 1
    print(f'Разобрано: {ok}, ошибок: {failed}')
    return 1 if failed and not ok else 0


def cmd_classify(args):
    django_setup()
    from .classify import classify_all
    from .paths import classify_report_path
    rows = classify_all(overwrite=args.overwrite, recheck=args.recheck)
    print(f'Классифицировано {len(rows)} черновиков.')
    print(f'Отчёт: {classify_report_path()}')
    return 0


def cmd_solve(args):
    django_setup()
    from worksheets.corpus_solve import fill_draft_solutions
    from .store import iter_draft_paths, load_json, save_draft
    needle = (args.contains or '').lower()
    budget = args.limit
    filled_total = 0
    error_total = 0
    drafts_touched = 0
    for path in iter_draft_paths():
        draft = load_json(path)
        if not draft or draft.get('status') in ('skipped', 'imported'):
            continue
        if needle and needle not in (draft.get('id') or '').lower():
            continue
        if budget is not None and budget <= 0:
            break
        result = fill_draft_solutions(
            draft, overwrite=args.overwrite,
            limit=budget, sleep=args.sleep)
        save_draft(draft)
        filled_total += result['filled']
        error_total += len(result['errors'])
        if result['filled'] or result['errors']:
            drafts_touched += 1
            for index, err in result['errors']:
                print(f'FAIL {draft["id"]}#{index}: {err}', file=sys.stderr)
        if budget is not None:
            budget -= result['filled'] + len(result['errors'])
    print(
        f'Решения: листков {drafts_touched}, '
        f'задач {filled_total}, ошибок {error_total}.')
    return 1 if error_total and not filled_total else 0


def build_parser():
    parser = argparse.ArgumentParser(
        description='Локальный импорт авторских листков 5–11.')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('inventory', help='Сканировать папки классов')
    p_parse = sub.add_parser('parse', help='Разобрать выбранные tex')
    p_parse.add_argument('--only', choices=('include', 'review', 'skip'))
    p_parse.add_argument('--grade', type=int)
    p_parse.add_argument('--contains', help='Подстрока rel_path')
    p_parse.add_argument('--path', action='append', default=[],
                         help='Явный путь к .tex')
    p_parse.add_argument('--force', action='store_true',
                         help='Разбирать даже skip')
    p_cls = sub.add_parser('classify', help='Проставить темы и экзамены')
    p_cls.add_argument('--overwrite', action='store_true')
    p_cls.add_argument(
        '--recheck', action='store_true',
        help='Снять темы ниже барьера уверенности')
    p_solve = sub.add_parser(
        'solve', help='Дописать ответы и решения в черновики')
    p_solve.add_argument('--limit', type=int, help='Максимум задач за запуск')
    p_solve.add_argument('--overwrite', action='store_true')
    p_solve.add_argument('--contains', help='Подстрока id черновика')
    p_solve.add_argument(
        '--sleep', type=float, default=3.0,
        help='Пауза между запросами к нейросети, секунды')
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == 'inventory':
        return cmd_inventory(args)
    if args.cmd == 'parse':
        return cmd_parse(args)
    if args.cmd == 'classify':
        return cmd_classify(args)
    if args.cmd == 'solve':
        return cmd_solve(args)
    parser.error('Неизвестная команда')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

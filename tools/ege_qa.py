#!/usr/bin/env python3
"""Воспроизводимая очередь сверки ЕГЭ: проверки, выборка и компактные пакеты."""
import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'public_html'))
VERSION = 'ege-qa-v1'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def number(key):
    return tuple(map(int, key.split('.')))


def environment_balance_issues(text):
    """Возвращает незакрытые и лишние LaTeX-окружения."""
    issues = []
    stack = []
    pattern = re.compile(r'\\(begin|end)\{([^{}]+)\}')
    for match in pattern.finditer(text):
        action, name = match.groups()
        if action == 'begin':
            stack.append(name)
        elif not stack:
            issues.append(f'unexpected_end:{name}')
        elif stack[-1] != name:
            issues.append(f'mismatched_end:{name}')
            stack.pop()
        else:
            stack.pop()
    issues.extend(f'unclosed_begin:{name}' for name in reversed(stack))
    return issues


def risks(row):
    """Сигналы — очередь сверки, а не доказательство ошибки."""
    flags = []
    parts = [row, *row.get('subitems', [])]
    text = '\n'.join(str(part.get(key, '')) for part in parts
                     for key in ('text_latex', 'author_answer_latex', 'author_solution_latex'))
    answer = '\n'.join(str(p.get('author_answer_latex', '')) for p in parts)
    if row.get('warnings'):
        flags.append('parser_warning')
    if not answer.strip():
        flags.append('missing_answer')
    if re.search(r'\\(?:frac|sqrt|begin|left)|[∞∪∈]|\\(?:cup|infty)', answer):
        flags.append('complex_answer')
    if row.get('subitems'):
        flags.append('subitems')
    if re.search(r'Оглавление|Аналоги|Прототип|Задача\s+\d+\.|\\(?:setcounter|item)\b', text):
        flags.append('ocr_leak')
    if len(re.findall(r'(?<!\\)\$', text)) % 2:
        flags.append('math_delimiters')
    if any(text.count(left) != text.count(right)
           for left, right in [(r'\(', r'\)'), (r'\[', r'\]')]):
        flags.append('math_delimiters')
    stack = []
    for brace in re.findall(r'(?<!\\)[{}]', text):
        if brace == '{':
            stack.append(brace)
        elif stack:
            stack.pop()
        else:
            flags.append('unbalanced_braces')
            break
    if stack:
        flags.append('unbalanced_braces')
    if environment_balance_issues(text):
        flags.append('unbalanced_environments')
    if sum(len(part.get('text_latex', '')) for part in parts) < 15:
        flags.append('short_body')
    if re.search(r'[0-9][а-яА-Я]{2,}', text):
        flags.append('stuck_units')
    return sorted(set(flags))


def selections(rows):
    by_section = {}
    for row in rows:
        by_section.setdefault(number(row['external_id'])[0], []).append(row)
    pilot, clean_sample = set(), set()
    for section, group in sorted(by_section.items()):
        ordered = sorted(group, key=lambda r: digest([VERSION, r['external_id']]))
        pilot.update(r['external_id'] for r in ordered[:2])
        clean = [r for r in ordered if not risks(r)]
        clean_sample.update(r['external_id'] for r in clean[:max(5, math.ceil(len(clean) * .05))])
        if len(group) <= 5:
            clean_sample.update(r['external_id'] for r in group)
    complex_rows = sorted(rows, key=lambda r: (-len(risks(r)), digest([VERSION, r['external_id']])))
    for row in complex_rows:
        if len(pilot) >= min(80, len(rows)):
            break
        pilot.add(row['external_id'])
    return sorted(pilot, key=number), sorted(clean_sample, key=number)


def audit(payload, image_dir):
    rows = payload['tasks']
    counts = Counter(r['external_id'] for r in rows)
    records = {}
    for row in rows:
        key = row['external_id']
        flags = risks(row)
        images = row.get('images', [])
        for stem in images:
            if not any((image_dir / (stem + ext)).is_file() for ext in ('.png', '.jpg', '.jpeg', '.pdf')):
                flags.append('missing_image')
        text = '\n'.join(p.get(field, '') for p in [row, *row.get('subitems', [])]
                         for field in ('text_latex', 'author_answer_latex', 'author_solution_latex'))
        if any(int(n) < 1 or int(n) > len(images) for n in re.findall(r'\\taskpic\{(\d+)\}', text)):
            flags.append('image_reference')
        expected_code = f'EGE_PROFILE_2027_{number(key)[0]:02d}'
        if row.get('exam_item_codes') != [expected_code]:
            flags.append('exam_metadata')
        records[key] = {'input_hash': digest(row), 'risks': sorted(set(flags)),
                        'verification': 'automatic_only'}
    pilot, sample = selections(rows)
    return {'version': VERSION, 'source': payload['source'], 'tasks': records,
            'duplicates': [k for k, n in counts.items() if n != 1],
            'risk_counts': dict(Counter(f for r in records.values() for f in r['risks'])),
            'pilot': pilot, 'clean_sample': sample,
            'review_queue': sorted({*sample, *(k for k, r in records.items() if r['risks']),
                                    *payload.get('diagnostics', {}).get('recovered_tex_marker_ids', [])}, key=number)}


def packets(payload, index, ids, output, pdf_path, size=15):
    """Картинки источника и полные поля только выбранных карточек."""
    import pymupdf
    rows = {r['external_id']: r for r in payload['tasks']}
    instruction = ('Сверь условие, подпункты, числа, знаки, авторский ответ и рисунки с PDF. '
                   'Не решай задачу и не заменяй авторский ответ вычисленным. '
                   'Для каждого номера верни JSON: id, verdict (ok/defect/uncertain), '
                   'issues, proposed_changes, evidence. Не меняй исходники или БД. '
                   'Если вырезка недостаточна, verdict=uncertain. '
                   'Пиши результат в указанный result.json; не пересказывай корректный текст.')
    with pymupdf.open(pdf_path) as doc:
        for start in range(0, len(ids), size):
            selected = ids[start:start + size]
            items = []
            folder = output / f'packet-{start // size + 1:03d}'
            folder.mkdir(parents=True, exist_ok=True)
            for key in selected:
                source = index['tasks'].get(key, {})
                item = {'id': key, 'draft': rows[key], 'source': source, 'risks': risks(rows[key])}
                for kind, page_key, clip_key in [('task', 'page', 'clip'), ('answer', 'answer_page', 'answer_clip')]:
                    if not source.get(page_key) or not source.get(clip_key):
                        continue
                    path = folder / f'{key}-{kind}.png'
                    page = doc[source[page_key] - 1]
                    clip = pymupdf.Rect(source[clip_key]) & page.rect
                    if clip.is_empty:
                        continue
                    page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), clip=clip).save(path)
                    item[kind + '_image'] = str(path.resolve())
                items.append(item)
            content = {'version': VERSION, 'instruction': instruction,
                       'result_file': str((folder / 'result.json').resolve()), 'items': items}
            content['input_hash'] = digest(content)
            write_json(folder / 'input.json', content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--packets', choices=['pilot', 'review_queue', 'clean_sample'])
    parser.add_argument('--index', type=Path)
    args = parser.parse_args()
    payload = json.loads(args.bundle.read_text())
    report = audit(payload, args.bundle.parent / 'images')
    write_json(args.output / 'audit.json', report)
    if args.packets:
        if not args.index:
            parser.error('--packets требует --index')
        index = json.loads(args.index.read_text())
        packets(payload, index, report[args.packets], args.output / args.packets,
                Path(payload['source']['answers_file']))
    print(canonical({'tasks': len(report['tasks']), 'risks': report['risk_counts'],
                     'pilot': len(report['pilot']), 'review_queue': len(report['review_queue'])}))


if __name__ == '__main__':
    main()

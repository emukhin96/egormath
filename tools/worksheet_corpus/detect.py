"""Диалект tex-файла и вердикт include/skip/review."""

from __future__ import annotations

import re
from pathlib import Path

from .latex_scan import document_body, extract_title_guess

SKIP_DIALECTS = {
    'beamer', 'flacards', 'tikz', 'probsoln', 'fragment', 'temp',
}

CHEM_NAME_RE = re.compile(
    r'(?i)(^|[^a-z])(chem|chemege|him)([^a-z]|$)')
PHYS_NAME_RE = re.compile(r'(?i)(^|[^a-z])phys([^a-z]|$)')
UNI_NAME_RE = re.compile(
    r'(?i)(ibmath|^linal|^matan|dvi[-_]|дви)')
TEMP_NAME_RE = re.compile(
    r'(?i)(temp|tikz|frametest|boxtest|annot-test|'
    r'dztemp|samosttemp|ans-temp|^ans1|'
    r'копия|\(\s*2\s\)|\(\s*2\s*\))')
ANS_NAME_RE = re.compile(r'(?i)-ans\.tex$|_ответы')
COPY_NAME_RE = re.compile(r'(?i)(копия|\(\s*[23]\s*\))')
TASK_FRAG_RE = re.compile(r'(?i)-task\d+\.tex$')
SKIP_DIR_RE = re.compile(
    r'(?i)(карточки\s*tex|химия|дви\s*мгу|материалы карпенко|'
    r'работы учеников|журнал|attachments)')

DOCUMENTCLASS_RE = re.compile(
    r'\\documentclass(?:\[[^\]]*\])?\{(?P<cls>[^}]+)\}')
USEPACKAGE_RE = re.compile(
    r'\\usepackage(?:\[[^\]]*\])?\{(?P<pkg>[^}]+)\}')


def read_tex(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ('utf-8', 'utf-8-sig', 'cp1251', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


MATH_GRADE_RE = re.compile(
    r'(?i)(?:^|[^a-z0-9])math(\d{1,2})(?:[-_.]|$)')


def grade_from_path(path: Path, fallback=None):
    """Класс: mathXX- в имени файла важнее папки «N класс»."""
    m = MATH_GRADE_RE.search(path.name)
    if m:
        grade = int(m.group(1))
        if 5 <= grade <= 11:
            return grade
    for part in path.parts:
        m = re.match(r'^(\d+)\s*класс$', part)
        if m:
            return int(m.group(1))
    return fallback


def detect_dialect(source: str, path: Path | None = None) -> str:
    name = path.name if path else ''
    if TEMP_NAME_RE.search(name) and 'math' not in name.lower():
        if re.search(r'(?i)(temp|test|tikz|frame|box|annot)', name):
            if not re.search(r'(?i)(ege|oge|mcko|kr|sr|diagn)', name):
                if re.search(r'(?i)(temp|tikz|frametest|boxtest|annot-test)',
                             name):
                    return 'temp'
    cls_m = DOCUMENTCLASS_RE.search(source)
    cls = (cls_m.group('cls') if cls_m else '').strip()
    packages = {m.group('pkg') for m in USEPACKAGE_RE.finditer(source)}
    if cls == 'beamer':
        return 'beamer'
    if cls == 'flacards' or 'flacards' in packages:
        return 'flacards'
    if cls == 'standalone':
        return 'tikz'
    if cls == 'exam':
        return 'exam'
    if not cls_m:
        if r'\newproblem' in source:
            return 'probsoln'
        if r'\begin{document}' not in source:
            return 'fragment'
    if packages & {'mathneo', 'egormath', 'egor'}:
        return 'egor'
    if 'chem' in packages and r'\task{' in source:
        return 'chem-math'
    zad_hits = len(re.findall(r'\\zad\b', source))
    zad_defs = (source.count(r'\newcommand{\zad}')
                + source.count(r'\renewcommand{\zad}')
                + source.count(r'\def\zad'))
    zad_uses = zad_hits - zad_defs
    if zad_uses >= 2 and re.search(r'\\zad\s+\S', source):
        return 'zad'
    if r'\begin{enumerate}' in source:
        return 'enumerate'
    if zad_uses >= 1 and re.search(r'\\zad\s+\S', source):
        return 'zad'
    if r'\newproblem' in source:
        return 'probsoln'
    if re.search(r'\\task\{', source):
        return 'egor'
    return 'other'


def skip_reason(path: Path, dialect: str, source: str, rel: str) -> str | None:
    name = path.name
    rel_l = rel.replace('\\', '/').lower()
    if SKIP_DIR_RE.search(rel_l):
        return 'служебная или чужая папка'
    if CHEM_NAME_RE.search(name) or '/chem' in rel_l:
        return 'химия'
    if PHYS_NAME_RE.search(name):
        return 'физика'
    if UNI_NAME_RE.search(name) or UNI_NAME_RE.search(rel_l):
        return 'вуз / IB / ДВИ'
    if ANS_NAME_RE.search(name):
        return 'только ответы'
    if COPY_NAME_RE.search(name):
        return 'копия файла'
    if r'\lipsum' in source and not re.search(
            r'\\(?:task|zad|item|question)\b', source):
        return 'заглушка без задач'
    if TEMP_NAME_RE.search(name) and dialect in ('temp', 'tikz', 'other'):
        return 'служебный или тестовый файл'
    if dialect in SKIP_DIALECTS:
        return {
            'beamer': 'презентация Beamer',
            'flacards': 'карточки flacards',
            'tikz': 'одиночный рисунок',
            'probsoln': 'фрагмент probsoln / \\newproblem',
            'fragment': 'файл без преамбулы',
            'temp': 'черновик',
        }.get(dialect, dialect)
    if TASK_FRAG_RE.search(name) and dialect in ('probsoln', 'fragment',
                                                 'other'):
        return 'обрезка -taskN'
    if re.match(r'(?i)8m-', name) and dialect in ('probsoln', 'fragment'):
        return 'фрагмент 8m без преамбулы'
    return None


def decide_verdict(path: Path, dialect: str, source: str, rel: str):
    reason = skip_reason(path, dialect, source, rel)
    if reason:
        return 'skip', reason
    if dialect == 'exam':
        if CHEM_NAME_RE.search(path.name):
            return 'skip', 'химия (exam)'
        return 'review', 'класс exam — проверить, что это математическая КР'
    if dialect == 'other':
        return 'review', 'неизвестный диалект'
    if dialect in ('egor', 'chem-math', 'enumerate', 'zad'):
        return 'include', ''
    return 'review', dialect


def inspect_file(path: Path, grade: int | None, root: Path) -> dict:
    source = read_tex(path)
    dialect = detect_dialect(source, path)
    try:
        rel = str(path.relative_to(root.parent if root.name.endswith('класс')
                                   else root))
    except ValueError:
        rel = str(path)
    # относительный путь от папки «N класс»
    try:
        rel = str(path.relative_to(root))
        rel = f'{root.name}/{rel}'
    except ValueError:
        rel = path.name
    header = extract_title_guess(source)
    body = document_body(source)
    verdict, reason = decide_verdict(path, dialect, source, rel)
    return {
        'path': str(path),
        'rel_path': rel,
        'name': path.name,
        'grade': grade_from_path(path, grade),
        'dialect': dialect,
        'verdict': verdict,
        'reason': reason,
        'title': header.get('title') or '',
        'header': header,
        'n_task': len(re.findall(r'\\task\b', source)),
        'n_item': len(re.findall(r'\\item\b', source)),
        'n_zad': len(re.findall(r'\\zad\b', source)),
        'n_question': len(re.findall(r'\\question\b', source)),
        'n_includegraphics': len(re.findall(r'\\includegraphics\b', source)),
        'n_starredtask': len(re.findall(r'\\starredtask\b', source)),
        'bytes': path.stat().st_size,
        'has_document': r'\begin{document}' in source,
        'body_chars': len(body),
    }

"""Корни корпуса в Dropbox и каталог промежуточных артефактов."""

from pathlib import Path
import os

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]
OUTPUT_DIR = PROJECT_ROOT / 'var' / 'worksheets-import'

_DEFAULT_PARENT = Path(
    '/Users/emukhin96/Library/CloudStorage/Dropbox/Учебное')

GRADE_FOLDERS = {
    5: '5 класс',
    6: '6 класс',
    7: '7 класс',
    8: '8 класс',
    9: '9 класс',
    10: '10 класс',
    11: '11 класс',
}


def corpus_parent():
    raw = os.environ.get('WORKSHEET_CORPUS_ROOT')
    if raw:
        return Path(raw)
    return _DEFAULT_PARENT


def corpus_roots():
    parent = corpus_parent()
    return [
        (grade, parent / folder)
        for grade, folder in GRADE_FOLDERS.items()
        if (parent / folder).is_dir()
    ]


CORPUS_ROOTS = corpus_roots()


def parsed_dir():
    return OUTPUT_DIR / 'parsed'


def assets_dir():
    return OUTPUT_DIR / 'assets'


def draft_assets_root(draft_key: str) -> Path:
    """Каталог рисунков черновика: assets/<id с / → __>/."""
    return assets_dir() / draft_key.replace('/', '__')


def inventory_json_path():
    return OUTPUT_DIR / 'inventory.json'


def inventory_md_path():
    return OUTPUT_DIR / 'inventory.md'


def classify_report_path():
    return OUTPUT_DIR / 'classify-report.md'

"""Сверенные исключения конкретного OCR-издания ЕГЭ, без эвристик по номерам."""
import hashlib
import json
import re
from pathlib import Path


def repair_source(text):
    """Применяет только подтверждённые замены к точной версии источника."""
    spec = json.loads(Path(__file__).with_name('data').joinpath('ege_source_repairs.json').read_text())
    if hashlib.sha256(text.encode()).hexdigest() != spec['source_sha256']:
        return text, []
    removed = {row['stem'] for row in spec['remove_images']}
    image_re = re.compile(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}')
    text = image_re.sub(lambda m: '' if Path(m[1]).stem in removed else m[0], text)
    applied = []
    for patch in spec['patches']:
        if text.count(patch['before']) != 1:
            raise ValueError(f"Неоднозначный сверенный фрагмент {patch['id']}")
        text = text.replace(patch['before'], patch['after'], 1)
        applied.append(patch['id'])
    return text, applied


def repair_drafts(tasks, source_sha256):
    """Восстанавливает утраченные OCR условия с проверкой прежнего текста."""
    spec = json.loads(Path(__file__).with_name('data').joinpath('ege_source_repairs.json').read_text())
    if source_sha256 != spec['source_sha256']:
        return []
    by_id = {task.external_id: task for task in tasks}
    applied = []
    for patch in spec.get('draft_patches', []):
        task = by_id[patch['id']]
        if task.text_latex != patch['before'] or task.images != patch.get('before_images', patch['images']):
            raise ValueError(f"Изменился сверенный черновик {patch['id']}")
        task.text_latex = patch['after']
        task.images = patch['images']
        applied.append({'id': patch['id'], 'page': patch['page'],
                        'verification': patch['verification']})
    return applied


def repair_answers(answers, source_sha256, pdf_sha256):
    """Применяет принятые транскрипции, а не необработанный ответ модели."""
    path = Path(__file__).with_name('data') / 'ege_answer_repairs.json'
    if not path.exists():
        return []
    spec = json.loads(path.read_text())
    if (source_sha256 != spec['source_sha256'] or pdf_sha256 != spec['pdf_sha256']):
        return []
    applied = []
    for patch in spec['items']:
        key = patch['id']
        if answers.get(key) != patch['before']:
            raise ValueError(f'Изменился сверенный исходный ответ {key}')
        answers[key] = patch['answer_latex']
        applied.append(key)
    return applied


def exclude_incomplete_tasks(tasks, source_sha256):
    """Пустая карточка в самой книге остаётся в реестре исключений."""
    spec = json.loads(Path(__file__).with_name('data').joinpath('ege_source_repairs.json').read_text())
    if source_sha256 != spec['source_sha256']:
        return []
    excluded = spec.get('excluded_tasks', [])
    by_id = {task.external_id: task for task in tasks}
    for row in excluded:
        task = by_id[row['id']]
        if task.text_latex != row['before'] or task.subitems or task.images:
            raise ValueError(f"Изменилось условие исключённой задачи {row['id']}")
    tasks[:] = [task for task in tasks if task.external_id not in {r['id'] for r in excluded}]
    return excluded


def remove_trailing_headings(tasks, source_sha256):
    """Заголовок следующего прототипа не относится к предыдущему условию."""
    spec = json.loads(Path(__file__).with_name('data').joinpath('ege_source_repairs.json').read_text())
    if source_sha256 != spec['source_sha256']:
        return []
    headings = set(spec.get('subsection_headings', []))
    removed = []
    for task in tasks:
        target = task.subitems[-1] if task.subitems else task
        lines = target.text_latex.rstrip().split('\n')
        if len(lines) > 1 and lines[-1].strip() in headings:
            removed.append({'id': task.external_id, 'heading': lines[-1].strip()})
            target.text_latex = '\n'.join(lines[:-1]).rstrip()
    return removed

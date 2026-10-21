import os
import re

from django.db import migrations

TASKPIC_NUM_RE = re.compile(r'\\taskpic\{(\d+)\}')
ANSWER_FIELDS = ('author_answer_latex', 'answer_latex')
SOLUTION_FIELDS = ('author_solution_latex', 'solution_latex')


def refs(owner, fields):
    return {int(m.group(1)) - 1 for field in fields
            for m in TASKPIC_NUM_RE.finditer(getattr(owner, field, '') or '')}


def task_state(apps, cache, task_id):
    if task_id not in cache:
        task = apps.get_model('problems', 'Task').objects.filter(pk=task_id).first()
        if task is None:
            cache[task_id] = None
        else:
            images = [os.path.basename(i.image.name) for i in apps.get_model('problems', 'TaskImage').objects.filter(task_id=task_id).order_by('order', 'id')]
            parts = {p.pk: p for p in apps.get_model('problems', 'TaskSubitem').objects.filter(task_id=task_id)}
            material = refs(task, ANSWER_FIELDS + SOLUTION_FIELDS)
            for part in parts.values():
                material |= refs(part, ANSWER_FIELDS + SOLUTION_FIELDS)
            cache[task_id] = (task, images, parts, material)
    return cache[task_id]


def fixed_audiences(apps, cache, source_key, snapshot, sources):
    """Новые адресаты вложений пункта (по порядку ``sources``) или None.

    Повторяет candidate_data после исправления: рисунок без ссылки в
    условии пункта, но со ссылкой в любом поле ответа/решения задачи,
    — не картинка условия. ``sources`` — пары (имя, адресаты) в порядке
    снимка. Номера \\taskpic снимка сопоставляются с текущими картинками
    задачи, поэтому пункт пропускаем, если картинки с выдачи могли
    сдвинуться: имена снимка не идут в текущем порядке или ссылка
    условия указывает не на картинку условия из снимка. Сомнение
    оставляет картинку в условии — так ученик её не теряет.
    """
    if not any('statement' in audiences for _, audiences in sources):
        return None
    match = re.fullmatch(r't(\d+)(?::s(\d+))?', source_key or '')
    state = match and task_state(apps, cache, int(match.group(1)))
    if not state:
        return None
    task, images, parts, material = state
    names = [name for name, _ in sources]
    if any(name not in images for name in names):
        return None
    positions = [images.index(name) for name in names]
    if positions != sorted(set(positions)):
        return None
    statement = {int(m.group(1)) - 1 for m in TASKPIC_NUM_RE.finditer(
        (snapshot.get('common') or '') + (snapshot.get('text') or ''))}
    shown = {name for name, audiences in sources if 'statement' in audiences}
    if any(index >= len(images) or images[index] not in shown for index in statement):
        return None
    owner = parts.get(int(match.group(2))) if match.group(2) else task
    if owner is None:
        return None
    result, changed = [], False
    for (name, audiences), index in zip(sources, positions):
        if 'statement' in audiences and index not in statement and index in material:
            audiences = [kind for kind, fields in (('answer', ANSWER_FIELDS), ('solution', SOLUTION_FIELDS))
                         if index in refs(owner, fields)]
            changed = True
        result.append(audiences)
    return result if changed else None


def forwards(apps, schema_editor):
    Point = apps.get_model('independentworks', 'Point')
    Run = apps.get_model('independentworks', 'Run')
    cache = {}
    for point in Point.objects.filter(assets__isnull=False).distinct().iterator():
        assets = list(point.assets.order_by('pk'))
        audiences = fixed_audiences(apps, cache, point.source_key, point.snapshot, [(a.name, a.audiences) for a in assets])
        for asset, new in zip(assets, audiences or []):
            if new != asset.audiences:
                asset.audiences = new
                asset.save(update_fields=['audiences'])
    # Невыданные предпросмотры выдаются из плана — правим и его.
    for run in Run.objects.filter(issued_at__isnull=True).iterator():
        changed = False
        for variant in (run.plan or {}).get('variants', []):
            for row in variant:
                snapshot = row.get('snapshot', {})
                sources = snapshot.get('assets', [])
                audiences = fixed_audiences(apps, cache, row.get('source_key'), snapshot,
                                            [(s.get('name'), s.get('audiences', [])) for s in sources])
                for source, new in zip(sources, audiences or []):
                    source['audiences'] = new
                    changed = True
        if changed:
            run.save(update_fields=['plan'])


class Migration(migrations.Migration):
    """Рисунки из скрытых версий ответа/решения убираем из условия выданных самостоятельных."""

    dependencies = [
        ('independentworks', '0010_run_clipboard_mode'),
        ('problems', '0033_source_short_title'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

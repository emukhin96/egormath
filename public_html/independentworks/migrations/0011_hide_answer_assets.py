import os
import re

from django.db import migrations

TASKPIC_NUM_RE = re.compile(r'\\taskpic\{(\d+)\}')
ANSWER_FIELDS = ('author_answer_latex', 'answer_latex')
SOLUTION_FIELDS = ('author_solution_latex', 'solution_latex')


def refs(owner, fields):
    return {int(m.group(1)) - 1 for field in fields
            for m in TASKPIC_NUM_RE.finditer(getattr(owner, field, '') or '')}


def fixed_audiences(apps, cache, source_key, snapshot, name, audiences):
    """Новые адресаты вложения или None, если менять нечего.

    Повторяет candidate_data после исправления: рисунок без ссылки в
    условии пункта, но со ссылкой в любом поле ответа/решения задачи,
    — не картинка условия.
    """
    if 'statement' not in audiences:
        return None
    match = re.fullmatch(r't(\d+)(?::s(\d+))?', source_key or '')
    if not match:
        return None
    task_id = int(match.group(1))
    if task_id not in cache:
        Task = apps.get_model('problems', 'Task')
        task = Task.objects.filter(pk=task_id).first()
        if task is None:
            cache[task_id] = None
        else:
            images = [os.path.basename(i.image.name) for i in apps.get_model('problems', 'TaskImage').objects.filter(task_id=task_id).order_by('order', 'id')]
            parts = {p.pk: p for p in apps.get_model('problems', 'TaskSubitem').objects.filter(task_id=task_id)}
            material = refs(task, ANSWER_FIELDS + SOLUTION_FIELDS)
            for part in parts.values():
                material |= refs(part, ANSWER_FIELDS + SOLUTION_FIELDS)
            cache[task_id] = (task, images, parts, material)
    if cache[task_id] is None or name not in cache[task_id][1]:
        return None
    task, images, parts, material = cache[task_id]
    index = images.index(name)
    statement = {int(m.group(1)) - 1 for m in TASKPIC_NUM_RE.finditer(
        (snapshot.get('common') or '') + (snapshot.get('text') or ''))}
    if index in statement or index not in material:
        return None
    owner = parts.get(int(match.group(2))) if match.group(2) else task
    if owner is None:
        return None
    result = []
    if index in refs(owner, ANSWER_FIELDS):
        result.append('answer')
    if index in refs(owner, SOLUTION_FIELDS):
        result.append('solution')
    return result


def forwards(apps, schema_editor):
    Asset = apps.get_model('independentworks', 'Asset')
    Run = apps.get_model('independentworks', 'Run')
    cache = {}
    for asset in Asset.objects.select_related('point').iterator():
        point = asset.point
        audiences = fixed_audiences(apps, cache, point.source_key, point.snapshot, asset.name, asset.audiences)
        if audiences is not None:
            asset.audiences = audiences
            asset.save(update_fields=['audiences'])
    # Невыданные предпросмотры выдаются из плана — правим и его.
    for run in Run.objects.filter(issued_at__isnull=True).iterator():
        changed = False
        for variant in (run.plan or {}).get('variants', []):
            for row in variant:
                snapshot = row.get('snapshot', {})
                for source in snapshot.get('assets', []):
                    audiences = fixed_audiences(apps, cache, row.get('source_key'), snapshot, source.get('name'), source.get('audiences', []))
                    if audiences is not None:
                        source['audiences'] = audiences
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

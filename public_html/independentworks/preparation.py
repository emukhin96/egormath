"""Подготовка независимого шаблона из листка или выбранной пары Зива."""
from collections import OrderedDict
from django.db import transaction
from problems.models import TaskSource
from .analogs import ZIV
from .models import Work, Position, Candidate
from .services import WorkError, digest


def ziv_rows(collection, pair):
    if pair not in (1, 3, 5, 7):
        raise WorkError('Выберите пару вариантов Зива.')
    task_ids = collection.worksheet.ordered_items().values_list('task_id', flat=True)
    refs = TaskSource.objects.filter(source=collection.source, task_id__in=task_ids).select_related('task')
    grouped = OrderedDict()
    for ref in refs.order_by('pk'):
        match = ZIV.fullmatch(ref.locator or '')
        if not match:
            continue
        kind, topic, variant, number = match.groups()
        if int(variant) not in (pair, pair + 1):
            continue
        key = kind, topic, number
        row = grouped.setdefault(key, {'number': number, 'candidates': [], 'variants': set()})
        if int(variant) in row['variants']:
            raise WorkError(f'Неоднозначный исходный номер {number}. Проверьте состав подборки.')
        row['variants'].add(int(variant))
        row['candidates'].append(ref.task)
    rows = list(grouped.values())
    for row in rows:
        row['incomplete'] = len(row['candidates']) < 2
    return rows


def selection_fingerprint(rows):
    return digest([(r['number'], [(t.pk, t.text_latex, list(t.subitems.values_list('pk', flat=True)))
                                 for t in r['candidates']]) for r in rows])


@transaction.atomic
def from_worksheet(sheet, owner, title, rows=None):
    work = Work.objects.create(owner=owner, title=title, source_worksheet=sheet)
    if rows is not None:
        if not rows:
            raise WorkError('В выбранной паре нет импортированных задач.')
        for order, row in enumerate(rows, 1):
            position = Position.objects.create(work=work, order=order)
            for task in row['candidates']:
                Candidate.objects.create(position=position, task=task)
    elif sheet:
        for item in sheet.ordered_items():
            note = '\n'.join(filter(None, [item.rubric, item.rubric_note, item.text_latex]))
            position = Position.objects.create(work=work, order=item.order, text=note)
            if item.task_id:
                Candidate.objects.create(position=position, task=item.task,
                    subitem_ids=[] if item.all_subitems else list(item.subitems.values_list('pk', flat=True)))
    return work

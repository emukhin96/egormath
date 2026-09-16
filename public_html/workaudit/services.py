"""Общая история двух форматов работ без записи нажатий клавиш."""
from copy import deepcopy
from django.db import connection
from django.db.models import F
from .models import AnswerRevision


def answer_snapshot(obj):
    if obj._meta.label_lower == 'independentworks.answer':
        return deepcopy(obj.values)
    return deepcopy({name: getattr(obj, name) for name in (
        'answer_json', 'answer_text', 'answer_number', 'interval_low', 'interval_high')})


def revision_target(obj):
    return {'answer' if obj._meta.label_lower == 'independentworks.answer' else
            'part' if obj._meta.model_name == 'submissionpart' else 'submission': obj}


def record_revision(obj, before):
    """Вызывать внутри транзакции сохранения, после блокировки работы."""
    after = answer_snapshot(obj)
    if after == before:
        return
    target = revision_target(obj)
    if any(before.values()) and not AnswerRevision.objects.filter(**target).exists():
        AnswerRevision.objects.create(**target, snapshot=before, initial=True)
    AnswerRevision.objects.create(**target, snapshot=after)


def visibility_summary(events):
    """Только замкнутые интервалы одной страницы; вкладки считаются отдельно."""
    pages = {}
    for event in events:
        pages.setdefault(str(event.page_id), []).append(event)
    result = []
    for page_id, rows in pages.items():
        hidden = None
        seconds = 0
        unknown = 0
        for row in sorted(rows, key=lambda e: e.sequence):
            if row.kind == 'hidden':
                if hidden is not None:
                    unknown += 1
                hidden = row.elapsed_ms
            elif row.kind == 'visible' and hidden is not None:
                if row.elapsed_ms >= hidden:
                    seconds += (row.elapsed_ms - hidden) / 1000
                else:
                    unknown += 1
                hidden = None
        result.append({'page': page_id[:8], 'seconds': round(seconds),
                       'count': sum(e.kind == 'hidden' for e in rows),
                       'unknown': unknown + int(hidden is not None)})
    return result


def lock_work(model, pk):
    """Блокировка перед чтением: на SQLite предотвращает upgrade deadlock."""
    if connection.vendor == 'sqlite':
        model.objects.filter(pk=pk).update(**{model._meta.pk.name: F('pk')})
    return model.objects.select_for_update().get(pk=pk)

"""Общая история двух форматов работ без записи нажатий клавиш."""
import re
from copy import deepcopy
from django.db import connection
from django.db.models import Count, F
from django.utils.html import escape
from django.utils.safestring import mark_safe
from .clipboard import WHOLE_SHARE
from .models import ActivityEvent, AnswerRevision


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


def whole_copies(kind, works):
    """Сколько раз ученик копировал условие целиком: {pk работы: число}.
    Окно — те же 90 дней, что хранит журнал."""
    rows = (ActivityEvent.objects.filter(**{f'{kind}__in': works}, whole=True)
            .values(kind).annotate(n=Count('pk')).values_list(kind, 'n'))
    return dict(rows)


def lock_work(model, pk):
    """Блокировка перед чтением: на SQLite предотвращает upgrade deadlock."""
    if connection.vendor == 'sqlite':
        model.objects.filter(pk=pk).update(**{model._meta.pk.name: F('pk')})
    return model.objects.select_for_update().get(pk=pk)


SHORT_AWAY_SECONDS = 5


def activity_timeline(events, started_at=None):
    """Лента для учителя: пары «скрыта → вернулся» одной вкладки схлопнуты в
    один уход с длительностью, буфер обмена — отдельные строки, вкладки
    нумеруются по порядку появления. `events` — все события работы за окно,
    в любом порядке; `started_at` — точка отсчёта времени (по умолчанию —
    первое событие). Время события — `client_at` (по часам устройства):
    клиент шлёт события пачками раз в 30 с, а при сбое сети — позже, так
    что серверное `received_at` сплющило бы пачку в одну отметку.
    Возвращает (строки новые сверху, сводка)."""
    by_page = {}
    for event in events:
        by_page.setdefault(str(event.page_id), []).append(event)
    # Номер вкладки — по моменту первого события в ней
    order = sorted(by_page, key=lambda page: min(e.client_at for e in by_page[page]))
    tab_no = {page: i + 1 for i, page in enumerate(order)}
    rows = []
    summary = {'away': 0, 'away_seconds': 0, 'away_max': 0, 'unknown': 0,
               'copy': 0, 'paste': 0, 'drop': 0, 'blocked': 0, 'whole': 0, 'tabs': len(by_page)}
    for page, items in by_page.items():
        hidden = None
        for row in sorted(items, key=lambda e: e.sequence):
            if row.kind == 'hidden':
                if hidden is not None:
                    rows.append(_away(hidden, None, tab_no[page]))
                    summary['away'] += 1; summary['unknown'] += 1
                hidden = row
            elif row.kind == 'visible':
                if hidden is None:
                    continue
                seconds = (row.elapsed_ms - hidden.elapsed_ms) / 1000 if row.elapsed_ms >= hidden.elapsed_ms else None
                rows.append(_away(hidden, seconds, tab_no[page]))
                summary['away'] += 1
                if seconds is None:
                    summary['unknown'] += 1
                else:
                    summary['away_seconds'] += seconds
                    summary['away_max'] = max(summary['away_max'], seconds)
                hidden = None
            else:
                rows.append({'kind': row.kind, 'label': copy_label(row) if row.kind == 'copy' else row.get_kind_display(),
                             'at': row.client_at, 'received': row.received_at, 'blocked': row.blocked,
                             'tab': tab_no[page], 'seconds': None, 'short': False,
                             'text': row.text, 'swapped': row.swapped, 'whole': row.whole})
                summary[row.kind] += 1
                summary['blocked'] += int(row.blocked)
                summary['whole'] += int(row.whole)
        if hidden is not None:
            rows.append(_away(hidden, None, tab_no[page], open_ended=True))
            summary['away'] += 1; summary['unknown'] += 1
    # Отсчёт — от первого события в работе: момент выдачи может быть за дни до
    # того, как ученик сел за работу, и смещения от него нечитаемы
    if started_at is None and rows:
        started_at = min(r['at'] for r in rows)
    for row in rows:
        row['offset'] = (row['at'] - started_at).total_seconds() if started_at else None
    rows.sort(key=lambda r: r['at'], reverse=True)
    summary['away_seconds'] = round(summary['away_seconds'])
    summary['away_max'] = round(summary['away_max'])
    summary['short'] = sum(1 for r in rows if r['short'])
    return rows, summary


def copy_label(event):
    """«скопировал условие задачи 3 целиком», «часть условия задачи 2 (40%)»."""
    whole = [p['label'] for p in event.statements if p['share'] >= WHOLE_SHARE]
    parts = [f"{p['label']} ({p['share']}%)" for p in event.statements if 0 < p['share'] < WHOLE_SHARE]
    if not whole and not parts:
        return 'скопировал текст' if event.text else event.get_kind_display()
    phrases = []
    if whole:
        phrases.append(('условие задачи ' if len(whole) == 1 else 'условия задач ') + ', '.join(whole) + ' целиком')
    if parts:
        phrases.append(('часть условия задачи ' if len(parts) == 1 else 'части условий задач ') + ', '.join(parts))
    return 'скопировал ' + ' и '.join(phrases)


NUMBER = re.compile(r'(\d+(?:[.,]\d+)?)')


def swap_marks(text, swapped):
    """Подменённый текст с выделенными числами, которые отличаются от исходных.
    Подмена меняет только числа, поэтому куски между ними совпадают; если нет
    (старая запись, обрезка) — текст без выделения."""
    before, after = NUMBER.split(text), NUMBER.split(swapped)
    if len(before) != len(after):
        return escape(swapped)
    return mark_safe(''.join(
        f'<mark>{escape(new)}</mark>' if i % 2 and new != old else escape(new)
        for i, (old, new) in enumerate(zip(before, after))))


def _away(hidden, seconds, tab, open_ended=False):
    return {'kind': 'away', 'label': 'ушёл со страницы', 'at': hidden.client_at, 'received': hidden.received_at, 'blocked': False,
            'tab': tab, 'seconds': None if seconds is None else round(seconds), 'open_ended': open_ended,
            'short': seconds is not None and seconds < SHORT_AWAY_SECONDS}


def format_span(seconds):
    """4 мин 12 с / 40 с / 1 ч 05 мин"""
    if seconds is None:
        return ''
    seconds = int(round(seconds))
    if seconds < 60:
        return f'{seconds} с'
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f'{minutes} мин {seconds:02d} с' if seconds else f'{minutes} мин'
    hours, minutes = divmod(minutes, 60)
    return f'{hours} ч {minutes:02d} мин'

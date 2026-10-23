"""Кабинет учителя (макет E_Home, 22.10.2026): что идёт сейчас, что ждёт
проверки, сроки на неделе и сигналы о копировании. Только чтение; видимость —
через Assignment.visible_to / Work.visible_to, как в списке заданий."""
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, F, Max, Min, Q
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment
from workaudit.services import copy_label, copied_words

SIGNAL_DAYS = 7
DEADLINE_DAYS = 7


def _name(user):
    return user.get_full_name() or user.username


def running_works(user, now=None):
    """Самостоятельные, которые решают прямо сейчас: есть начатые и не
    сданные попытки. Для карточки «Идёт сейчас»."""
    if not settings.INDEPENDENT_WORKS_ENABLED:
        return []
    from independentworks.models import Attempt, Run, Work
    now = now or timezone.now()
    live = (Attempt.objects.filter(run__work__in=Work.visible_to(user), started_at__isnull=False,
                                   submitted_at__isnull=True, ends_at__gt=now)
            .values_list('run_id', flat=True).distinct())
    cards = []
    for run in Run.objects.filter(pk__in=list(live)).prefetch_related('attempts').order_by('issued_at'):
        attempts = list(run.attempts.all())
        # активность — по тому же now, что и отбор в SQL: свойство finished
        # берёт свежее время, и попытка, истёкшая между запросами, давала
        # пустой список и 500 на max() (ревью #272)
        active = [a for a in attempts if a.started_at and not a.submitted_at and a.ends_at and a.ends_at > now]
        if not active:
            continue
        ends = max(a.ends_at for a in active)
        started = min(a.started_at for a in active)
        total = run.duration * 60 or 1
        remaining = max(0, int((ends - now).total_seconds()))
        cards.append({
            'run': run,
            'active': len(active),
            'finished': sum(1 for a in attempts if a.started_at and a not in active),
            'unopened': sum(1 for a in attempts if not a.started_at),
            'ends_at': ends,
            'remaining_label': f'{remaining // 60}:{remaining % 60:02}',
            'elapsed_percent': max(0, min(100, round(100 * (now - started).total_seconds() / total))),
            'url': reverse('independentworks:progress', args=[run.pk]),
        })
    return cards


def review_runs(user, now=None):
    """Проведения, где могут быть непроверенные пункты, — дешёвым запросом
    вместо всех самостоятельных учителя за всё время (ревью #272): есть
    завершённая попытка, у которой решённых пунктов (оценка учителя или
    автосверка «верно/неверно») меньше, чем пунктов в варианте. Отбор с
    запасом — точный статус дальше считает attempt_status."""
    from independentworks.models import Attempt, Run, Work
    now = now or timezone.now()
    resolved = ~Q(answers__grade='') | Q(answers__auto_check__in=['ok', 'wrong'])
    open_attempts = (Attempt.objects.filter(run__work__in=Work.visible_to(user), run__issued_at__isnull=False)
                     .filter(Q(submitted_at__isnull=False) | Q(ends_at__lte=now))
                     .annotate(points=Count('variant__points', distinct=True),
                               resolved=Count('answers', filter=resolved, distinct=True))
                     .filter(resolved__lt=F('points')).values('run_id'))
    return list(Run.objects.filter(pk__in=open_attempts).select_related('owner', 'work')
                .prefetch_related('attempts__student', 'attempts__answers', 'attempts__variant__points'))


def review_groups(user):
    """«Ждут проверки» по работам: обычные листки — сданные и не проверенные
    назначения, самостоятельные — сданные попытки с непроверенными пунктами."""
    rows = []
    pending = (Assignment.visible_to(user).filter(status=Assignment.STATUS_SUBMITTED)
               .values('worksheet_id', 'worksheet__title')
               .annotate(n=Count('pk'), last=Max('submitted_at')))
    for row in pending:
        rows.append({'title': row['worksheet__title'], 'kind': 'листок', 'n': row['n'],
                     'what': 'сданные работы', 'last': row['last'],
                     'url': reverse('assignment_review_queue', args=[row['worksheet_id']])})
    if settings.INDEPENDENT_WORKS_ENABLED:
        from independentworks.integration import assignment_groups
        for group in assignment_groups(user, {}, runs=review_runs(user)):
            if group['submitted_total']:
                rows.append({'title': group['worksheet__title'], 'kind': group['kind_label'].lower(),
                             'n': group['submitted_total'], 'what': 'работы с непроверенными пунктами',
                             'last': group['last_assigned'], 'url': group['progress_url']})
    rows.sort(key=lambda r: -r['n'])
    return rows


def week_deadlines(user, now=None):
    """Сроки за неделю назад и вперёд: сколько сдали из скольких."""
    now = now or timezone.now()
    since, until = now - timedelta(days=DEADLINE_DAYS), now + timedelta(days=DEADLINE_DAYS)
    rows = []
    done = Q(status__in=[Assignment.STATUS_SUBMITTED, Assignment.STATUS_REVIEWED])
    # листок, выданный с разными сроками, — отдельная строка на каждый день
    # срока: иначе прошедший срок одной группы «просрочил» бы и остальных
    by_sheet = (Assignment.visible_to(user).filter(due_at__range=(since, until))
                .annotate(due_day=TruncDate('due_at'))
                .values('worksheet_id', 'worksheet__title', 'due_day')
                .annotate(total=Count('pk'), done=Count('pk', filter=done), due=Min('due_at')))
    for row in by_sheet:
        rows.append({'title': row['worksheet__title'], 'due': row['due'], 'total': row['total'],
                     'done': row['done'], 'url': reverse('worksheet_progress', args=[row['worksheet_id']])})
    if settings.INDEPENDENT_WORKS_ENABLED:
        from independentworks.models import Run, Work
        runs = (Run.objects.filter(work__in=Work.visible_to(user), issued_at__isnull=False,
                                   deadline__range=(since, until))
                .prefetch_related('attempts'))
        for run in runs:
            attempts = list(run.attempts.all())
            rows.append({'title': run.title, 'due': run.deadline, 'total': len(attempts),
                         'done': sum(1 for a in attempts if a.finished),
                         'url': reverse('independentworks:progress', args=[run.pk])})
    for row in rows:
        row['passed'] = row['due'] < now
        row['percent'] = round(100 * row['done'] / row['total']) if row['total'] else 0
        row['left'] = row['total'] - row['done']
    rows.sort(key=lambda r: r['due'])
    return rows


def copy_signals(user, now=None, limit=5):
    """Сигналы о копировании за неделю: ученик скопировал из условия больше
    одного слова (та же «•», что в списках учителя). Последнее событие на
    ученика, свежие сверху."""
    from workaudit.models import ActivityEvent
    now = now or timezone.now()
    works = Q(assignment__in=Assignment.visible_to(user))
    if settings.INDEPENDENT_WORKS_ENABLED:
        from independentworks.models import Work
        works |= Q(attempt__run__work__in=Work.visible_to(user))
    events = (ActivityEvent.objects.filter(works, kind='copy', received_at__gte=now - timedelta(days=SIGNAL_DAYS))
              .select_related('assignment__student', 'assignment__worksheet', 'attempt__student', 'attempt__run')
              .order_by('-received_at')[:300])
    seen, rows = set(), []
    for event in events:
        if copied_words(event) < 2:
            continue
        work = event.assignment or event.attempt
        if work.student_id in seen:
            continue
        seen.add(work.student_id)
        title = event.assignment.worksheet.title if event.assignment else event.attempt.run.title
        url = (reverse('review_assignment', args=[event.assignment_id]) if event.assignment
               else reverse('independentworks:attempt', args=[event.attempt_id]))
        rows.append({'name': _name(work.student), 'note': f'{copy_label(event)}, «{title}»',
                     'at': event.received_at, 'url': url})
        if len(rows) >= limit:
            break
    return rows

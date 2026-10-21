"""Изоляция журнала по владельцу работы, серверные лимиты пакетов."""
import json
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from accounts.decorators import teacher_required
from assignments.models import Assignment, Submission, SubmissionPart
from independentworks.models import Attempt, Answer, Run, Work
from .clipboard import TEXT_LIMIT, WHOLE_SHARE, parse_mode
from .models import ActivityEvent, AnswerRevision
from .services import activity_timeline, lock_work


def work_for(user, kind, pk, teacher=False):
    if kind == 'assignment':
        qs = Assignment.visible_to(user) if teacher else Assignment.objects.filter(student=user)
    elif kind == 'attempt' and settings.INDEPENDENT_WORKS_ENABLED:
        qs = Attempt.objects.filter(run__issued_at__isnull=False)
        qs = qs.filter(run__work__in=Work.visible_to(user)) if teacher else qs.filter(student=user)
    else:
        raise Http404
    return get_object_or_404(qs, pk=pk)


def copy_fields(row):
    """Текст выделения, текст после подмены чисел и доли условий. Старые
    клиенты полей не шлют — копирование пишется без текста, как раньше."""
    text, swapped = row.get('text', ''), row.get('swapped', '')
    statements = row.get('statements', [])
    if type(text) is not str or type(swapped) is not str or type(statements) is not list or len(statements) > 50:
        raise ValueError
    parts = []
    for item in statements:
        label, share = item['label'], item['share']
        if type(label) is not str or len(label) > 30 or type(share) is not int or not 0 <= share <= 100:
            raise ValueError
        parts.append({'label': label, 'share': share})
    return {'text': text[:TEXT_LIMIT], 'swapped': swapped[:TEXT_LIMIT], 'statements': parts,
            'whole': any(part['share'] >= WHOLE_SHARE for part in parts)}


@never_cache
@login_required
@require_POST
def events(request, kind, pk):
    work = work_for(request.user, kind, pk)
    now = timezone.now()
    ended = (work.submitted_at if kind == 'assignment' else
             work.submitted_at or work.ends_at)
    active = work.is_editable_by_student if kind == 'assignment' else bool(work.started_at and not work.finished)
    # Поздний пакет при сдаче разрешён две минуты; новые действия после сдачи — нет.
    if not active and (not ended or now > ended + timedelta(minutes=2)):
        return JsonResponse({'error': 'Работа недоступна для событий.'}, status=409)
    # Копирование везёт текст условия (до 2000 символов дважды) — пакет больше.
    if len(request.body) > 131072:
        return JsonResponse({'error': 'Слишком большой пакет.'}, status=413)
    try:
        payload = json.loads(request.body)
        rows = payload['events']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
            raise ValueError
        batch = []
        for row in rows:
            event_id, page_id = uuid.UUID(row['id']), uuid.UUID(row['page'])
            at = parse_datetime(row['at'])
            if not at or timezone.is_naive(at) or abs((at-now).total_seconds()) > 86400:
                raise ValueError
            if row['kind'] not in dict(ActivityEvent._meta.get_field('kind').choices):
                raise ValueError
            if type(row['blocked']) is not bool:
                raise ValueError
            for field, maximum in [('seq', 2147483647), ('elapsed', 86400000)]:
                if type(row[field]) is not int or not 0 <= row[field] <= maximum:
                    raise ValueError
            if not active and at > ended:
                continue
            copied = copy_fields(row) if row['kind'] == 'copy' else {}
            batch.append(ActivityEvent(**{kind: work}, event_id=event_id, page_id=page_id,
                sequence=row['seq'], kind=row['kind'], blocked=row['blocked'],
                client_at=at, elapsed_ms=row['elapsed'], **copied))
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return JsonResponse({'error': 'Некорректный пакет.'}, status=400)
    with transaction.atomic():
        # Счётчик в БД общий для процессов CGI и всех вкладок одной работы.
        lock_work(type(work), work.pk)
        query = ActivityEvent.objects.filter(**{kind: work})
        existing = set(ActivityEvent.objects.filter(event_id__in=[e.event_id for e in batch]).values_list('event_id', flat=True))
        unique = {}
        for event in batch:
            if event.event_id not in existing:
                unique[event.event_id] = event
        if query.filter(received_at__gte=now-timedelta(minutes=1)).count() + len(unique) > 240:
            return JsonResponse({'error': 'Слишком много событий.'}, status=429)
        ActivityEvent.objects.bulk_create(list(unique.values()), ignore_conflicts=True)
    return JsonResponse({'ok': True})


@never_cache
@teacher_required
def activity(request, kind, pk):
    work = work_for(request.user, kind, pk, teacher=True)
    events = ActivityEvent.objects.filter(**{kind: work}, received_at__gte=timezone.now()-timedelta(days=90))
    if request.GET.get('raw'):
        # Сырой список — для спорных случаев: каждое событие отдельной строкой
        return render(request, 'workaudit/activity_raw.html', {
            'page': Paginator(events.order_by('-received_at', '-pk'), 50).get_page(request.GET.get('page'))})
    rows, summary = activity_timeline(events)
    show = request.GET.get('show', '')
    if show == 'away':
        rows = [r for r in rows if r['kind'] == 'away']
    elif show == 'clipboard':
        rows = [r for r in rows if r['kind'] in ('copy', 'paste', 'drop')]
    if request.GET.get('short') != '1':
        rows = [r for r in rows if not r['short']]
    return render(request, 'workaudit/activity.html', {
        'page': Paginator(rows, 50).get_page(request.GET.get('page')),
        'summary': summary, 'show': show, 'short': request.GET.get('short') == '1',
        'query': {'show': show, 'short': request.GET.get('short', '')}})


@never_cache
@teacher_required
def history(request, kind, pk):
    if kind == 'answer' and settings.INDEPENDENT_WORKS_ENABLED:
        obj = get_object_or_404(Answer.objects.filter(attempt__run__work__in=Work.visible_to(request.user)), pk=pk)
    elif kind == 'submission':
        obj = get_object_or_404(Submission.objects.filter(assignment__in=Assignment.visible_to(request.user)), pk=pk)
    elif kind == 'part':
        obj = get_object_or_404(SubmissionPart.objects.filter(submission__assignment__in=Assignment.visible_to(request.user)), pk=pk)
    else:
        raise Http404
    rows = AnswerRevision.objects.filter(**{kind: obj}, created_at__gte=timezone.now()-timedelta(days=90)).order_by('-created_at', '-pk')
    return render(request, 'workaudit/history.html', {'page': Paginator(rows, 50).get_page(request.GET.get('page'))})


@never_cache
@teacher_required
@require_POST
@transaction.atomic
def run_settings(request, pk):
    if not settings.INDEPENDENT_WORKS_ENABLED:
        raise Http404
    run = get_object_or_404(Run.objects.select_for_update().filter(work__in=Work.visible_to(request.user)), pk=pk)
    exemptions = request.POST.getlist('exempt')
    if any(not value.isdigit() for value in exemptions) or not set(map(int, exemptions)) <= set(run.attempts.values_list('pk', flat=True)):
        return JsonResponse({'error': 'Неизвестный ученик.'}, status=400)
    run.clipboard_mode = parse_mode(request.POST.get('clipboard_mode'))
    run.save(update_fields=['clipboard_mode'])
    run.attempts.update(clipboard_exempt=False)
    run.attempts.filter(pk__in=exemptions).update(clipboard_exempt=True)
    messages.success(request, 'Настройки копирования сохранены. В открытой работе применятся после перезагрузки страницы.')
    return redirect('independentworks:progress', pk=pk)

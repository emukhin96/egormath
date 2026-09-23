"""Локальная сверка черновиков листков. В рабочую базу не пишет, пока не commit."""

import re
from pathlib import Path

from django.contrib import messages
from django.db import IntegrityError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from problems.models import ExamItem, Topic
from problems.rubricator import (
    ensure_exam_parent_codes, taxonomy_page_context, taxonomy_state_from_post)

from .corpus import (apply_topic_to_drafts, approve_clean_drafts,
                     commit_approved, commit_draft, draft_topic_codes,
                     find_imported_worksheet, list_drafts, push_draft,
                     set_draft_topic_selection, unpush_worksheet)
from .corpus_solve import (fill_worksheet_solutions, imported_worksheets,
                           tasks_missing_solutions)
from worksheet_corpus.latex_scan import TITLE_PROPOSED_WARNING
from worksheet_corpus.subitems import attach_subitem_rows, ensure_subitem_fields

STATUS_LABELS = {
    'needs_review': 'не проверена',
    'approved': 'одобрена',
    'skipped': 'пропущена',
    'imported': 'загружена',
    'conflict': 'конфликт',
}

EXAM_TYPE_ORDER = (
    ('OGE', 'ОГЭ'),
    ('EGE_PROFILE', 'ЕГЭ профиль'),
    ('EGE_BASE', 'ЕГЭ база'),
    ('MCKO', 'МЦКО'),
)

EXAM_HINT_ABBREV = (
    ('практико-ориентированный комплекс: ', ''),
    ('геометрические ', 'геом. '),
    ('геометрическая ', 'геом. '),
    ('алгебраическая ', 'алг. '),
    ('алгебраические ', 'алг. '),
    ('повышенной сложности', 'пов. сл.'),
    ('высокой сложности', 'выс. сл.'),
    ('с развёрнутым решением', 'развёрн.'),
)


def exam_item_short_label(item):
    prefix = dict(EXAM_TYPE_ORDER).get(
        item.exam_model.exam_type, item.exam_model.get_exam_type_display())
    if item.item_number == 0:
        return prefix
    if (item.exam_model.exam_type == 'MCKO'
            and 'без привязки' in item.name.lower()):
        return prefix
    hint = ''
    matched = re.search(r'\(([^)]+)\)', item.name)
    if matched:
        hint = matched.group(1)
        for old, new in EXAM_HINT_ABBREV:
            hint = hint.replace(old, new)
        hint = hint.strip(' :')
    if hint:
        return f'{prefix} №{item.item_number} ({hint})'
    return f'{prefix} №{item.item_number}'


def exam_groups(selected_codes):
    selected = set(ensure_exam_parent_codes(selected_codes or []))
    groups = []
    for typ, label in EXAM_TYPE_ORDER:
        items = list(ExamItem.objects.filter(
            exam_model__exam_type=typ
        ).select_related('exam_model').order_by('item_number'))
        line = None
        numbered = []
        for item in items:
            is_line = (
                item.item_number == 0
                or (typ == 'MCKO' and 'без привязки' in item.name.lower())
            )
            row = {
                'code': item.code,
                'label': exam_item_short_label(item),
                'checked': item.code in selected,
            }
            if is_line:
                line = row
            else:
                numbered.append(row)
        groups.append({
            'type': typ,
            'label': label,
            'line': line,
            'items': numbered,
        })
    return groups


def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _status_counts():
    counts = {'needs_review': 0, 'approved': 0, 'skipped': 0, 'imported': 0}
    for row in list_drafts():
        st = row.get('status') or 'needs_review'
        if st in counts:
            counts[st] += 1
    return counts


def attach_exam_labels(drafts):
    codes = set()
    for draft in drafts:
        codes.update(draft.get('exam_item_codes') or [])
    labels = {}
    if codes:
        for item in ExamItem.objects.filter(
                code__in=codes).select_related('exam_model'):
            labels[item.code] = exam_item_short_label(item)
    for draft in drafts:
        draft['exam_labels'] = [
            labels.get(code, code)
            for code in draft.get('exam_item_codes') or []
        ]


def _get_draft_or_404(draft_id):
    from worksheet_corpus.store import load_draft
    return load_draft(draft_id)


def _topic_state(draft):
    codes = draft_topic_codes(draft)
    if not codes and draft.get('topic_ids'):
        topics = list(Topic.objects.filter(pk__in=draft['topic_ids']))
        by_pk = {topic.pk: topic for topic in topics}
        codes = [
            by_pk[pk].code for pk in draft['topic_ids']
            if pk in by_pk and by_pk[pk].code]
    topics = list(Topic.objects.filter(code__in=codes))
    by_code = {topic.code: topic for topic in topics}
    ordered_ids = [by_code[code].pk for code in codes if code in by_code]
    primary_code = draft.get('topic_code') or (codes[0] if codes else '')
    primary = by_code.get(primary_code)
    exam_ids = list(ExamItem.objects.filter(
        code__in=draft.get('exam_item_codes') or []
    ).values_list('pk', flat=True))
    return {
        'topics': ordered_ids,
        'primary': primary.pk if primary else (
            ordered_ids[0] if ordered_ids else None),
        'grades': [],
        'facets': [],
        'exams': exam_ids,
        'difficulty': None,
    }


def _apply_taxonomy_post(draft, post):
    state = taxonomy_state_from_post(post)
    if ('topics' in post or 'primary_topic' in post
            or 'topics_submitted' in post):
        set_draft_topic_selection(
            draft, state['topics'], state.get('primary'))
    elif post.get('topic_code') is not None:
        set_draft_topic_selection(
            draft,
            Topic.objects.filter(code=post.get('topic_code') or '')
            .values_list('pk', flat=True),
            None)
    if 'exams_submitted' in post or 'exam_item_codes' in post:
        draft['exam_item_codes'] = ensure_exam_parent_codes(
            [c for c in post.getlist('exam_item_codes') if c])
    elif state['exams']:
        draft['exam_item_codes'] = ensure_exam_parent_codes(list(
            ExamItem.objects.filter(pk__in=state['exams'])
            .values_list('code', flat=True)))


@teacher_required
def corpus_list(request):
    drafts = list_drafts()
    status = request.GET.get('status')
    grade = request.GET.get('grade')
    if status:
        drafts = [d for d in drafts if d.get('status') == status]
    else:
        drafts = [d for d in drafts if d.get('status') != 'skipped']
    if grade:
        try:
            grade_i = int(grade)
        except ValueError:
            grade_i = None
        if grade_i is not None:
            drafts = [d for d in drafts if d.get('grade') == grade_i]
    counts = _status_counts()
    attach_exam_labels(drafts)
    for draft in drafts:
        draft['status_label'] = STATUS_LABELS.get(
            draft.get('status'), draft.get('status') or '')
        draft['topic_label'] = ', '.join(draft_topic_codes(draft)) or '—'
    ctx = {
        'drafts': drafts,
        'counts': counts,
        'filter_status': status or '',
        'filter_grade': grade or '',
        'status_labels': STATUS_LABELS,
    }
    ctx.update(taxonomy_page_context())
    return render(request, 'worksheets/corpus_list.html', ctx)


@teacher_required
def corpus_detail(request, draft_id):
    from worksheet_corpus.store import save_draft
    draft = _get_draft_or_404(draft_id)
    if draft is None:
        messages.error(request, 'Черновик не найден. Сначала разберите tex.')
        return redirect('worksheet_corpus_list')
    if request.method == 'POST':
        action = request.POST.get('action') or 'save'
        new_title = request.POST.get('title', draft.get('title') or '')
        if (new_title != (draft.get('title') or '')
                and draft.get('title_origin') in ('proposed', 'filename')):
            draft['title_origin'] = 'manual'
            draft['warnings'] = [
                w for w in (draft.get('warnings') or [])
                if w != TITLE_PROPOSED_WARNING]
        draft['title'] = new_title
        if draft.get('header') is None:
            draft['header'] = {}
        draft['header']['title'] = draft['title']
        old_topic_codes = draft_topic_codes(draft)
        _apply_taxonomy_post(draft, request.POST)
        if 'topics' in request.POST or 'topics_submitted' in request.POST:
            draft['needs_topic_review'] = not bool(draft_topic_codes(draft))
            from worksheet_corpus.classify import _sync_copied_task_topics
            _sync_copied_task_topics(draft, old_topic_codes)
        for i, el in enumerate(draft.get('elements') or []):
            if el.get('kind') != 'task':
                continue
            el['text'] = request.POST.get(f'text_{i}', el.get('text') or '')
            if f'answer_{i}' in request.POST:
                el['answer'] = request.POST.get(f'answer_{i}') or ''
            if f'solution_{i}' in request.POST:
                el['solution'] = request.POST.get(f'solution_{i}') or ''
            el['stars'] = 0
            if el.get('answer', '').strip() and not el.get('answer_origin'):
                el['answer_origin'] = 'parsed'
            if not (el.get('answer') or '').strip() and not any(
                    (a or '').strip()
                    for a in (el.get('subitem_answers') or [])):
                el['answer_origin'] = ''
            subs = []
            sub_answers = []
            sub_solutions = []
            j = 0
            while (f'sub_{i}_{j}' in request.POST
                   or f'answer_{i}_{j}' in request.POST
                   or f'solution_{i}_{j}' in request.POST):
                if f'sub_{i}_{j}' in request.POST:
                    subs.append(request.POST.get(f'sub_{i}_{j}') or '')
                sub_answers.append(request.POST.get(f'answer_{i}_{j}') or '')
                sub_solutions.append(
                    request.POST.get(f'solution_{i}_{j}') or '')
                j += 1
            if subs:
                el['subitems'] = [s for s in subs if s.strip()]
            if j:
                el['subitem_answers'] = sub_answers
                el['subitem_solutions'] = sub_solutions
                if any((a or '').strip() for a in sub_answers):
                    el['answer'] = ''
                    if not el.get('answer_origin'):
                        el['answer_origin'] = 'parsed'
                if any((s or '').strip() for s in sub_solutions):
                    el['solution'] = ''
            ensure_subitem_fields(el)
        if action == 'approve':
            draft['status'] = 'approved'
        elif action == 'skip':
            draft['status'] = 'skipped'
        elif action == 'review':
            draft['status'] = 'needs_review'
        elif action == 'commit':
            draft['status'] = 'approved'
            save_draft(draft)
            try:
                worksheet, info = commit_draft(draft, request.user)
            except (ValueError, IntegrityError) as exc:
                messages.error(request, str(exc))
                return redirect('worksheet_corpus_detail', draft_id=draft_id)
            messages.success(
                request,
                f'Листок «{worksheet.title}» загружен '
                f'(новых задач: {info["created"]}, из базы: {info["reused"]}).')
            return redirect('worksheet_detail', pk=worksheet.pk)
        save_draft(draft)
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'message': 'Сохранено ✓'})
        messages.success(request, 'Черновик сохранён.')
        return redirect('worksheet_corpus_detail', draft_id=draft_id)
    imported = find_imported_worksheet(
        None if request.user.is_superuser else request.user, draft['id'])
    attach_subitem_rows(draft)
    ctx = {
        'draft': draft,
        'exam_groups': exam_groups(draft.get('exam_item_codes') or []),
        'imported': imported,
        'egor_url': reverse('worksheet_corpus_tex', args=[draft_id]),
        'status_label': STATUS_LABELS.get(
            draft.get('status'), draft.get('status') or ''),
    }
    ctx.update(taxonomy_page_context(_topic_state(draft)))
    return render(request, 'worksheets/corpus_detail.html', ctx)


@teacher_required
@require_POST
def corpus_toggle_skip(request, draft_id):
    from worksheet_corpus.store import save_draft
    draft = _get_draft_or_404(draft_id)
    if draft is None:
        if _is_ajax(request):
            return JsonResponse(
                {'ok': False, 'message': 'Черновик не найден.'}, status=404)
        messages.error(request, 'Черновик не найден.')
        return redirect('worksheet_corpus_list')
    if draft.get('status') == 'imported':
        if _is_ajax(request):
            return JsonResponse(
                {'ok': False, 'message': 'Загруженный листок нельзя пропустить.'},
                status=400)
        messages.error(request, 'Загруженный листок нельзя пропустить.')
        return redirect('worksheet_corpus_list')
    index_raw = request.POST.get('index')
    if index_raw not in (None, ''):
        try:
            index = int(index_raw)
        except (TypeError, ValueError):
            if _is_ajax(request):
                return JsonResponse(
                    {'ok': False, 'message': 'Нет такой задачи.'}, status=400)
            messages.error(request, 'Нет такой задачи.')
            return redirect('worksheet_corpus_detail', draft_id=draft_id)
        elements = draft.get('elements') or []
        if (index < 0 or index >= len(elements)
                or elements[index].get('kind') != 'task'):
            if _is_ajax(request):
                return JsonResponse(
                    {'ok': False, 'message': 'Нет такой задачи.'}, status=400)
            messages.error(request, 'Нет такой задачи.')
            return redirect('worksheet_corpus_detail', draft_id=draft_id)
        skipped = request.POST.get('skip') == '1'
        elements[index]['skip'] = skipped
        save_draft(draft)
        if _is_ajax(request):
            return JsonResponse({
                'ok': True,
                'skipped': skipped,
                'index': index,
            })
        return redirect('worksheet_corpus_detail', draft_id=draft_id)
    if request.POST.get('skip') == '1':
        draft['status'] = 'skipped'
    else:
        draft['status'] = 'needs_review'
    save_draft(draft)
    if _is_ajax(request):
        return JsonResponse({
            'ok': True,
            'status': draft['status'],
            'status_label': STATUS_LABELS.get(draft['status'], ''),
            'skipped': draft['status'] == 'skipped',
            'counts': _status_counts(),
        })
    return redirect('worksheet_corpus_list')


@teacher_required
def corpus_tex(request, draft_id):
    from worksheet_corpus.emit import emit_egor_tex
    draft = _get_draft_or_404(draft_id)
    if draft is None:
        messages.error(request, 'Черновик не найден.')
        return redirect('worksheet_corpus_list')
    from django.http import HttpResponse
    body = emit_egor_tex(draft)
    response = HttpResponse(body, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = (
        f'inline; filename="{draft_id.split("/")[-1]}.egor.tex"')
    return response


@teacher_required
def corpus_asset(request, draft_id, filename):
    from worksheet_corpus.paths import assets_dir
    root = (assets_dir() / draft_id.replace('/', '__')).resolve()
    path = (root / Path(filename).name).resolve()
    if not str(path).startswith(str(root)) or not path.is_file():
        raise Http404('Рисунок не найден')
    return FileResponse(path.open('rb'), filename=path.name)


@teacher_required
@require_POST
def corpus_push(request, draft_id):
    from worksheet_corpus.store import save_draft
    draft = _get_draft_or_404(draft_id)
    if draft is None:
        if _is_ajax(request):
            return JsonResponse(
                {'ok': False, 'message': 'Черновик не найден.'}, status=404)
        messages.error(request, 'Черновик не найден.')
        return redirect('worksheet_corpus_list')
    try:
        worksheet, info = push_draft(draft, request.user)
    except (ValueError, IntegrityError) as exc:
        if _is_ajax(request):
            return JsonResponse({'ok': False, 'message': str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect('worksheet_corpus_list')
    save_draft(draft)
    already = info.get('skipped')
    attached = info.get('attached') or 0
    if already and attached:
        message = (
            f'Листок «{worksheet.title}» уже в каталоге, '
            f'догружено рисунков: {attached}.')
    elif already:
        message = f'Листок «{worksheet.title}» уже в каталоге.'
    elif info.get('collection'):
        message = (f'Листок «{worksheet.title}» загружен в подборки '
                   f'(раздел «{info["collection"].parent.worksheet.title}»).')
    else:
        message = f'Листок «{worksheet.title}» загружен в каталог.'
    worksheet_url = (reverse('collection_detail', args=[info['collection'].pk])
                     if info.get('collection')
                     else reverse('worksheet_detail', args=[worksheet.pk]))
    if _is_ajax(request):
        return JsonResponse({
            'ok': True,
            'message': message,
            'already': already,
            'status': draft.get('status'),
            'status_label': STATUS_LABELS.get(
                draft.get('status'), draft.get('status') or ''),
            'worksheet_url': worksheet_url,
            'counts': _status_counts(),
        })
    messages.success(request, message)
    return redirect('worksheet_corpus_list')


@teacher_required
@require_POST
def corpus_unpush(request, pk):
    worksheet = imported_worksheets(
        None if request.user.is_superuser else request.user).filter(
            pk=pk).first()
    if worksheet is None:
        if _is_ajax(request):
            return JsonResponse(
                {'ok': False, 'message': 'Это не листок из корпуса.'},
                status=400)
        messages.error(request, 'Это не листок из корпуса.')
        return redirect('worksheet_list')
    _key, title, _draft = unpush_worksheet(worksheet)
    message = f'Листок «{title}» убран из каталога, черновик в корпусе.'
    if _is_ajax(request):
        return JsonResponse({'ok': True, 'message': message})
    messages.success(request, message)
    return redirect('worksheet_list')


@teacher_required
@require_POST
def corpus_commit_approved(request):
    results = commit_approved(request.user)
    if not results:
        messages.error(request, 'Нет одобренных черновиков для загрузки.')
        return redirect('worksheet_corpus_list')
    messages.success(
        request, f'Загружено листков: {len(results)}.')
    return redirect('worksheet_corpus_list')


@teacher_required
@require_POST
def corpus_approve_clean(request):
    approved = approve_clean_drafts()
    if approved:
        messages.success(
            request, f'Одобрено без замечаний: {len(approved)}.')
    else:
        messages.error(request, 'Нет черновиков без warnings.')
    return redirect('worksheet_corpus_list')


@teacher_required
@require_POST
def corpus_assign_topic(request):
    state = taxonomy_state_from_post(request.POST)
    pks = state['topics']
    primary = state.get('primary')
    if not pks and request.POST.get('topic_code'):
        topic = Topic.objects.filter(code=request.POST.get('topic_code')).first()
        if topic:
            pks = [topic.pk]
            primary = topic.pk
    code = ''
    if pks:
        topic = Topic.objects.filter(pk=pks[0]).first()
        if primary:
            topic = Topic.objects.filter(pk=primary).first() or topic
        code = topic.code if topic and topic.code else ''
    ids = request.POST.getlist('draft_id')
    updated = apply_topic_to_drafts(code, ids or None)
    messages.success(request, f'Тема назначена листкам: {len(updated)}.')
    return redirect('worksheet_corpus_list')


@teacher_required
def corpus_solutions(request):
    sheets = imported_worksheets(
        None if request.user.is_superuser else request.user)
    rows = []
    for ws in sheets:
        missing = tasks_missing_solutions(ws)
        rows.append({'worksheet': ws, 'missing': missing,
                     'missing_count': len(missing)})
    return render(request, 'worksheets/corpus_solutions.html', {'rows': rows})


@teacher_required
@require_POST
def corpus_solve_worksheet(request, pk):
    worksheet = imported_worksheets(
        None if request.user.is_superuser else request.user).filter(
            pk=pk).first()
    if worksheet is None:
        messages.error(request, 'Листок корпуса не найден.')
        return redirect('worksheet_corpus_solutions')
    result = fill_worksheet_solutions(worksheet)
    if result['filled']:
        messages.success(
            request,
            f'Дописаны решения у {len(result["filled"])} задач. '
            'Проверьте их на странице листка.')
    for task_id, err in result['errors']:
        messages.error(request, f'Задача #{task_id}: {err}')
    if not result['filled'] and not result['errors']:
        messages.success(request, 'У всех задач этого листка уже есть решения.')
    return redirect('worksheet_detail', pk=worksheet.pk)

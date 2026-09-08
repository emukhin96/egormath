"""Загрузка одобренных черновиков листков из var/worksheets-import/."""

from __future__ import annotations

import sys
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction

from problems.models import ExamItem, Source, Task, TaskImage, TaskSource, Topic
from problems.rubricator import (GRADE_LEVEL_TO_CODE, set_grade_bands,
                                 set_task_exams, set_task_topics)

from .import_tex import find_existing_task
from .models import Worksheet, WorksheetItem

TOOLS = Path(__file__).resolve().parents[2] / 'tools'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from worksheet_corpus.store import (  # noqa: E402
    iter_draft_paths, load_json, save_draft)
from worksheet_corpus.subitems import ensure_subitem_fields  # noqa: E402

SOURCE_TITLE = 'Авторские листки'
CORPUS_MARK = 'corpus:'


def corpus_mark(key):
    return f'{CORPUS_MARK}{key}'


def draft_topic_codes(draft, el=None):
    """Коды тем: список плюс основная. У задачи — свои, иначе с листка."""
    source = el if el is not None else draft
    codes = []
    seen = set()
    for code in list((source or {}).get('topic_codes') or []):
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    primary = (source or {}).get('topic_code') or ''
    if primary and primary not in seen:
        codes.insert(0, primary)
    if el is not None and not codes:
        return draft_topic_codes(draft)
    return codes


def set_draft_topic_selection(draft, topic_pks, primary_id=None):
    """Пишет набор тем листка. Пустой список снимает назначение."""
    from problems.rubricator import parse_int_ids
    pks = parse_int_ids(topic_pks)
    topics = list(Topic.objects.filter(pk__in=pks))
    by_pk = {topic.pk: topic for topic in topics}
    ordered = [by_pk[pk] for pk in pks if pk in by_pk]
    if primary_id not in (None, ''):
        try:
            primary_id = int(primary_id)
        except (TypeError, ValueError):
            primary_id = None
    else:
        primary_id = None
    if primary_id not in by_pk:
        primary_id = ordered[0].pk if ordered else None
    if primary_id:
        ordered = (
            [by_pk[primary_id]]
            + [topic for topic in ordered if topic.pk != primary_id])
    codes = [topic.code for topic in ordered if topic.code]
    draft['topic_ids'] = [topic.pk for topic in ordered]
    draft['topic_codes'] = codes
    draft['topic_code'] = codes[0] if codes else ''
    return codes


def find_imported_worksheet(owner, key):
    queryset = Worksheet.objects.filter(
        comment__startswith=corpus_mark(key))
    if owner is not None:
        queryset = queryset.filter(owner=owner)
    return queryset.first()


def list_drafts():
    drafts = []
    for path in iter_draft_paths():
        data = load_json(path)
        if data:
            drafts.append(data)
    drafts.sort(key=lambda d: (d.get('grade') or 99, d.get('id') or ''))
    return drafts


def ensure_source():
    source, _ = Source.objects.get_or_create(
        title=SOURCE_TITLE, defaults={'author': 'Е.А. Мухин'})
    return source


def _attach_images(task, stored_paths):
    existing = {img.filename for img in task.images.all()}
    for index, raw in enumerate(stored_paths or [], start=1):
        path = Path(raw)
        if not path.is_file() or path.name in existing:
            continue
        image = TaskImage(task=task, order=index * 10)
        image.image.save(path.name, ContentFile(path.read_bytes()), save=True)
        existing.add(path.name)


def _fill_task_answers(task, answer, solution, sub_answers, sub_solutions):
    """Дописывает пустые ответы у уже существующей задачи."""
    updates = []
    if answer and not (task.answer_latex or '').strip():
        task.answer_latex = answer
        updates.append('answer_latex')
    if solution and not (task.solution_latex or '').strip():
        task.solution_latex = solution
        updates.append('solution_latex')
    if updates:
        task.save(update_fields=updates)
    for j, sub in enumerate(task.subitems.all()):
        sub_updates = []
        if (j < len(sub_answers) and (sub_answers[j] or '').strip()
                and not (sub.answer_latex or '').strip()):
            sub.answer_latex = sub_answers[j]
            sub_updates.append('answer_latex')
        if (j < len(sub_solutions) and (sub_solutions[j] or '').strip()
                and not (sub.solution_latex or '').strip()):
            sub.solution_latex = sub_solutions[j]
            sub_updates.append('solution_latex')
        if sub_updates:
            sub.save(update_fields=sub_updates)


def _apply_taxonomy(task, draft, owner_grade, el=None):
    grade = draft.get('grade') or owner_grade
    if grade == 11:
        grade = 10
    code = GRADE_LEVEL_TO_CODE.get(grade)
    if code:
        set_grade_bands(task, [code], sync_legacy=True)
    codes = draft_topic_codes(draft, el)
    topics = list(Topic.objects.filter(code__in=codes))
    by_code = {topic.code: topic for topic in topics}
    ids = [by_code[item].pk for item in codes if item in by_code]
    primary_code = ''
    if el and el.get('topic_code'):
        primary_code = el['topic_code']
    if not primary_code:
        primary_code = draft.get('topic_code') or (codes[0] if codes else '')
    primary = by_code.get(primary_code)
    if ids:
        set_task_topics(task, ids, primary.pk if primary else ids[0])
    exam_codes = draft.get('exam_item_codes') or []
    if exam_codes:
        exam_ids = list(ExamItem.objects.filter(code__in=exam_codes)
                        .values_list('pk', flat=True))
        if exam_ids:
            set_task_exams(task, exam_ids)
    return [by_code[item] for item in codes if item in by_code]


@transaction.atomic
def commit_draft(draft, owner, *, force=False):
    """Создаёт Worksheet + Task. Повтор с тем же id не дублирует листок."""
    key = draft['id']
    existing = find_imported_worksheet(owner, key)
    if existing and not force:
        return existing, {'created': 0, 'reused': 0, 'skipped': True}
    if draft.get('status') not in ('approved', 'imported') and not force:
        raise ValueError('Черновик ещё не одобрен.')
    header = draft.get('header') or {}
    grade = draft.get('grade')
    if grade == 11:
        grade_opt = 10
    else:
        grade_opt = grade
    worksheet = Worksheet.objects.create(
        title=header.get('title') or draft.get('title') or 'Листок',
        grade_label=header.get('left') or (
            f'{grade} класс' if grade else ''),
        author_name=header.get('right') or '',
        subtitle=header.get('subtitle') or '',
        grade=grade_opt,
        owner=owner,
        comment=corpus_mark(key),
    )
    grade_code = GRADE_LEVEL_TO_CODE.get(grade_opt)
    if grade_code:
        set_grade_bands(worksheet, [grade_code], sync_legacy=False)
    source = ensure_source()
    created = 0
    reused = 0
    worksheet_topics = set()
    order = 0
    for el in draft.get('elements') or []:
        order += 10
        kind = el.get('kind')
        if kind == 'rubric':
            rubric = (el.get('rubric') or '').strip()
            note = el.get('note') or ''
            if not rubric and not note.strip():
                continue
            WorksheetItem.objects.create(
                worksheet=worksheet, order=order,
                rubric=rubric or ' ',
                rubric_note=note)
            continue
        if kind == 'text':
            text = el.get('text') or ''
            if not text.strip():
                continue
            WorksheetItem.objects.create(
                worksheet=worksheet, order=order,
                text_latex=text,
                text_style=el.get('style') or 'plain')
            continue
        if kind != 'task' or el.get('skip'):
            continue
        if el.get('status') == 'skipped':
            continue
        text = el.get('text') or ''
        subitems = el.get('subitems') or []
        ensure_subitem_fields(el)
        sub_answers = el.get('subitem_answers') or []
        sub_solutions = el.get('subitem_solutions') or []
        has_sub_answers = any((a or '').strip() for a in sub_answers)
        has_sub_solutions = any((s or '').strip() for s in sub_solutions)
        task_answer = '' if has_sub_answers else (el.get('answer') or '')
        task_solution = '' if has_sub_solutions else (el.get('solution') or '')
        task_pk = find_existing_task(text, subitems)
        if task_pk:
            task = Task.objects.get(pk=task_pk)
            reused += 1
            _fill_task_answers(
                task, task_answer, task_solution, sub_answers, sub_solutions)
        else:
            task = Task.objects.create(
                text_latex=text,
                stars=0,
                columns=int(el.get('columns') or 0),
                answer_latex=task_answer,
                solution_latex=task_solution,
                grade_level=grade_opt,
                created_by=owner)
            for j, chunk in enumerate(subitems):
                task.subitems.create(
                    order=(j + 1) * 10, text_latex=chunk,
                    answer_latex=sub_answers[j] if j < len(sub_answers) else '',
                    solution_latex=(
                        sub_solutions[j] if j < len(sub_solutions) else ''))
            created += 1
        applied = _apply_taxonomy(task, draft, grade_opt, el)
        for topic in applied:
            worksheet_topics.add(topic.pk)
        _attach_images(task, el.get('image_files') or [])
        locator = f'{key}#{order}'
        if not TaskSource.objects.filter(source=source, locator=locator).exists():
            if not TaskSource.objects.filter(task=task, source=source).exists():
                TaskSource.objects.create(
                    task=task, source=source,
                    number=str(order // 10),
                    locator=locator,
                    source_path=[draft.get('rel_path') or key])
        WorksheetItem.objects.create(
            worksheet=worksheet, task=task, order=order)
    if worksheet_topics:
        worksheet.topics.add(*Topic.objects.filter(pk__in=worksheet_topics))
    draft['status'] = 'imported'
    draft['imported_worksheet_id'] = worksheet.pk
    save_draft(draft)
    return worksheet, {'created': created, 'reused': reused, 'skipped': False}


def commit_approved(owner, *, force=False):
    results = []
    for draft in list_drafts():
        if draft.get('status') != 'approved' and not force:
            continue
        worksheet, info = commit_draft(draft, owner, force=force)
        results.append((draft['id'], worksheet, info))
    return results


def approve_clean_drafts():
    """Одобряет черновики без warnings и с хотя бы одной задачей."""
    approved = []
    for draft in list_drafts():
        if draft.get('status') != 'needs_review':
            continue
        if draft.get('warnings'):
            continue
        if not any(el.get('kind') == 'task' for el in draft.get('elements') or []):
            continue
        draft['status'] = 'approved'
        save_draft(draft)
        approved.append(draft['id'])
    return approved


def corpus_key_from_comment(comment):
    text = (comment or '').strip()
    if not text.startswith(CORPUS_MARK):
        return ''
    return text[len(CORPUS_MARK):].splitlines()[0].strip()


def push_draft(draft, owner):
    """Одна кнопка: черновик корпуса → листок в каталоге."""
    if draft.get('status') == 'skipped':
        raise ValueError('Пропущенный листок нельзя загрузить в каталог.')
    existing = find_imported_worksheet(owner, draft['id'])
    if existing:
        return existing, {'created': 0, 'reused': 0, 'skipped': True}
    return commit_draft(draft, owner, force=True)


def unpush_worksheet(worksheet):
    """Убирает листок из каталога и возвращает черновик на сверку."""
    key = corpus_key_from_comment(worksheet.comment)
    title = worksheet.title
    worksheet.delete()
    draft = None
    if key:
        from worksheet_corpus.store import load_draft, save_draft
        draft = load_draft(key)
        if draft:
            draft['status'] = 'needs_review'
            draft.pop('imported_worksheet_id', None)
            save_draft(draft)
    return key, title, draft


def apply_topic_to_drafts(topic_code, draft_ids=None):
    """Массовая тема: всем указанным (или всем непроверенным) листкам."""
    wanted = set(draft_ids or [])
    updated = []
    for draft in list_drafts():
        if wanted and draft['id'] not in wanted:
            continue
        if not wanted and draft.get('status') != 'needs_review':
            continue
        draft['topic_code'] = topic_code or ''
        draft['topic_codes'] = [topic_code] if topic_code else []
        if topic_code:
            topic = Topic.objects.filter(code=topic_code).first()
            draft['topic_ids'] = [topic.pk] if topic else []
        else:
            draft['topic_ids'] = []
        save_draft(draft)
        updated.append(draft['id'])
    return updated

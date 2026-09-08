"""Пакетная дописка решений для листков, загруженных из корпуса."""

import re

from problems.neuro import NeuroError, solve_task
from worksheet_corpus.subitems import (
    apply_subitem_payload, filled_count, needs_subitem_regen)

from .corpus import CORPUS_MARK
from .models import Worksheet

_ANSWER_MISMATCH_WARNING = 'Ответ и решение расходятся'


def imported_worksheets(owner=None):
    qs = Worksheet.objects.filter(comment__startswith=CORPUS_MARK)
    if owner is not None:
        qs = qs.filter(owner=owner)
    return qs.order_by('grade', 'title', 'pk')


def tasks_missing_solutions(worksheet):
    tasks = []
    for item in worksheet.ordered_items():
        task = item.task
        if task is None:
            continue
        subs = list(task.subitems.all())
        if subs:
            if any(not s.effective_solution_latex for s in subs):
                tasks.append(task)
        elif not task.effective_solution_latex:
            tasks.append(task)
    return tasks


def apply_neuro_solution(task):
    """Пишет черновик нейросети в solution_latex, не трогая author_*."""
    payload = solve_task(task.text_latex, [
        sub.text_latex for sub in task.subitems.all()])
    subs = list(task.subitems.all())
    if subs:
        answers = payload.get('subitem_answers') or []
        solutions = payload.get('subitem_solutions') or []
        for i, sub in enumerate(subs):
            if i < len(answers) and answers[i] and not sub.answer_latex:
                sub.answer_latex = answers[i]
            if i < len(solutions) and solutions[i] and not sub.solution_latex:
                sub.solution_latex = solutions[i]
            sub.save()
    else:
        if payload.get('answer') and not task.answer_latex:
            task.answer_latex = payload['answer']
        if payload.get('solution') and not task.solution_latex:
            task.solution_latex = payload['solution']
        task.save(update_fields=['answer_latex', 'solution_latex', 'updated_at'])
    return payload


def fill_worksheet_solutions(worksheet, *, limit=None):
    filled = []
    errors = []
    tasks = tasks_missing_solutions(worksheet)
    if limit is not None:
        tasks = tasks[:limit]
    for task in tasks:
        try:
            apply_neuro_solution(task)
            filled.append(task.pk)
        except NeuroError as exc:
            errors.append((task.pk, str(exc)))
    return {'filled': filled, 'errors': errors, 'left': (
        len(tasks_missing_solutions(worksheet)))}


def _norm_math(text):
    text = (text or '').lower()
    text = text.replace('\\,', '').replace('\\;', '').replace('\\!', '')
    text = re.sub(r'[\s$]+', '', text)
    return text


def answers_match_solution(answer, solution):
    """Грубая сверка: краткий ответ должен читаться в финале решения."""
    ans = _norm_math(answer)
    sol = _norm_math(solution)
    if not ans or not sol:
        return True
    if ans in sol:
        return True
    compact = ans.replace('\\', '')
    if compact and compact in sol.replace('\\', ''):
        return True
    return False


def _join_payload(payload, key_single, key_list):
    parts = [p for p in (payload.get(key_list) or []) if (p or '').strip()]
    if parts:
        sep = '; ' if key_single == 'answer' else '\n\n'
        return sep.join(parts)
    return (payload.get(key_single) or '').strip()


def apply_neuro_to_element(el, *, overwrite=False):
    """Пишет answer/solution в элемент черновика. Пропущенные не трогает."""
    if el.get('kind') != 'task' or el.get('skip'):
        return None
    had_answer = bool((el.get('answer') or '').strip()) or bool(
        filled_count(el.get('subitem_answers')))
    had_solution = bool((el.get('solution') or '').strip()) or bool(
        filled_count(el.get('subitem_solutions')))
    if el.get('subitems') and not needs_subitem_regen(el) and not overwrite:
        return None
    if had_answer and had_solution and not overwrite:
        return None
    text = el.get('text') or ''
    subitems = list(el.get('subitems') or [])
    payload = solve_task(text, subitems)
    if subitems:
        apply_subitem_payload(
            el,
            answers=payload.get('subitem_answers'),
            solutions=payload.get('subitem_solutions'))
        if filled_count(el.get('subitem_answers')):
            el['answer_origin'] = 'neuro'
        return payload
    new_answer = _join_payload(payload, 'answer', 'subitem_answers')
    new_solution = _join_payload(payload, 'solution', 'subitem_solutions')
    parsed_answer = (el.get('answer') or '').strip()
    keep_parsed = (
        had_answer and el.get('answer_origin') != 'neuro' and not overwrite)
    if keep_parsed:
        answer = parsed_answer
        origin = 'parsed'
    else:
        answer = new_answer or parsed_answer
        origin = 'neuro' if new_answer else (el.get('answer_origin') or '')
    solution = new_solution or (el.get('solution') or '')
    if keep_parsed and new_solution and not answers_match_solution(
            answer, new_solution):
        check = solve_task(
            text + '\n\nРанее предложенный ответ: ' + answer
            + '\nРанее предложенное решение:\n' + new_solution
            + '\nОтвет и финал решения должны совпадать. '
            'Сохрани данный ответ, если он верный.',
            subitems)
        fix_sol = _join_payload(check, 'solution', 'subitem_solutions')
        if fix_sol:
            solution = fix_sol
    elif (not keep_parsed and answer and solution
          and not answers_match_solution(answer, solution)):
        check = solve_task(
            text + '\n\nЧерновик ответа: ' + answer
            + '\nЧерновик решения:\n' + solution
            + '\nОтвет и финал решения расходятся. '
            'Верни согласованные answer и solution.',
            subitems)
        fix_ans = _join_payload(check, 'answer', 'subitem_answers')
        fix_sol = _join_payload(check, 'solution', 'subitem_solutions')
        if fix_ans:
            answer = fix_ans
            origin = 'neuro'
        if fix_sol:
            solution = fix_sol
    if answer and (overwrite or not had_answer or not keep_parsed):
        el['answer'] = answer
        el['answer_origin'] = origin or ('neuro' if answer else '')
    elif keep_parsed:
        el['answer_origin'] = 'parsed'
    if solution and (overwrite or not had_solution):
        el['solution'] = solution
    if (el.get('answer') and el.get('solution')
            and not answers_match_solution(el['answer'], el['solution'])):
        warns = list(el.get('warnings') or [])
        if _ANSWER_MISMATCH_WARNING not in warns:
            warns.append(_ANSWER_MISMATCH_WARNING)
        el['warnings'] = warns
    return payload


def fill_draft_solutions(draft, *, overwrite=False, limit=None, sleep=0):
    import time
    filled = 0
    errors = []
    seen = 0
    for index, el in enumerate(draft.get('elements') or []):
        if el.get('kind') != 'task' or el.get('skip'):
            continue
        has_answer = bool((el.get('answer') or '').strip()) or bool(
            filled_count(el.get('subitem_answers')))
        has_solution = bool((el.get('solution') or '').strip()) or bool(
            filled_count(el.get('subitem_solutions')))
        if el.get('subitems') and not needs_subitem_regen(el) and not overwrite:
            continue
        if has_answer and has_solution and not overwrite:
            continue
        if limit is not None and seen >= limit:
            break
        seen += 1
        try:
            apply_neuro_to_element(el, overwrite=overwrite)
            filled += 1
        except NeuroError as exc:
            errors.append((index, str(exc)))
        if sleep:
            time.sleep(sleep)
    return {'filled': filled, 'errors': errors}

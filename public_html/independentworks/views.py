"""Интерфейсы самостоятельных с проверкой прав на каждом маршруте."""
import io
import json
import uuid
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Max
from django.http import FileResponse, Http404, JsonResponse, HttpResponse, HttpResponseNotModified
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from assignments.checks import parse_mask, collect_values, render_fragments
from assignments.models import Review, SubmissionPhoto
from accounts.decorators import get_role, teacher_required
from accounts.models import Profile
from problems.models import Task, TaskSubitem
from worksheets.models import Worksheet, Collection
from .forms import WorkForm, RunForm
from .models import Work, Position, Candidate, Family, Run, Attempt, Answer, Photo, Asset, Point
from . import services as svc


def enabled(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not settings.INDEPENDENT_WORKS_ENABLED:
            raise Http404
        try:
            response = view(request, *args, **kwargs)
        except svc.WorkError as error:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                response = JsonResponse({'message': str(error)}, status=error.status)
            else:
                response = render(request, 'independentworks/error.html', {'error': str(error)}, status=error.status)
        response['Cache-Control'] = 'no-store, private'
        return response
    return wrapped


def preparation_query(request):
    params = request.GET.copy()
    for key in list(params):
        if key not in ('resume', 'parent', 'kind'):
            params.pop(key)
    return params.urlencode()


def teacher_run(request, pk):
    return get_object_or_404(Run.objects.select_related('work', 'parent'), pk=pk, work__in=Work.visible_to(request.user))


def own_attempt(request, pk, teacher=False):
    qs = Attempt.objects.select_related('run', 'variant', 'root', 'parent').prefetch_related('variant__points__assets', 'answers__photos')
    if teacher:
        qs = qs.filter(run__work__in=Work.visible_to(request.user))
    else:
        qs = qs.filter(student=request.user)
    return get_object_or_404(qs, pk=pk, run__issued_at__isnull=False)


@enabled
def catalog(request):
    return redirect(reverse('assignment_list') + '?kind=independent') if get_role(request.user) == 'teacher' else redirect(reverse('dashboard') + '?kind=independent')


@enabled
@teacher_required
def create(request):
    form = WorkForm(request.POST or None)
    sheets = Worksheet.visible_to(request.user).order_by('-updated_at')
    collections = Collection.objects.select_related('worksheet').filter(is_published=True).order_by('source_id', 'order')
    selected_sheet = request.GET.get('worksheet', '')
    if request.method == 'POST' and form.is_valid():
        from .preparation import ziv_rows, selection_fingerprint, from_worksheet
        sheet_id = request.POST.get('worksheet')
        collection_id = request.POST.get('collection')
        sheet = get_object_or_404(sheets, pk=sheet_id) if sheet_id else None
        rows = None
        if collection_id:
            collection = get_object_or_404(collections, pk=collection_id)
            sheet = collection.worksheet
            from .analogs import ZIV
            from problems.models import TaskSource
            is_ziv = any(ZIV.fullmatch(r or '') for r in TaskSource.objects.filter(
                source=collection.source, task_id__in=sheet.ordered_items().values('task_id')).values_list('locator', flat=True))
            if is_ziv:
                try:
                    pair = int(request.POST.get('pair', '1'))
                except ValueError:
                    raise svc.WorkError('Выберите пару вариантов.')
                rows = ziv_rows(collection, pair)
                fingerprint = selection_fingerprint(rows)
                if not rows:
                    raise svc.WorkError('В выбранной паре нет импортированных задач.')
                if request.POST.get('selection') != fingerprint:
                    return render(request, 'independentworks/source_preview.html', {
                        'form': form, 'collection': collection, 'pair': pair,
                        'source_rows': rows, 'selection': fingerprint})
        work = from_worksheet(sheet, request.user, form.cleaned_data['title'], rows)
        return redirect('independentworks:edit', pk=work.pk)
    return render(request, 'independentworks/create.html', {'form': form, 'worksheets': sheets[:150], 'collections': collections, 'selected_sheet': selected_sheet})


@enabled
@teacher_required
def edit(request, pk):
    work = get_object_or_404(Work.visible_to(request.user), pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action')
        with transaction.atomic():
            work = Work.objects.select_for_update().get(pk=pk)
            if action == 'title':
                form = WorkForm(request.POST, instance=work)
                if not form.is_valid():
                    raise svc.WorkError('Введите название до 190 символов.')
                form.save()
            elif action == 'add':
                order = (work.positions.aggregate(n=Max('order'))['n'] or 0) + 1
                Position.objects.create(work=work, order=order, text=request.POST.get('text', ''))
            elif action == 'remove':
                get_object_or_404(work.positions, pk=request.POST.get('position')).delete()
            elif action == 'candidate_remove':
                candidate = get_object_or_404(Candidate, pk=request.POST.get('candidate'), position__work=work)
                position = candidate.position
                candidate.delete()
                position.mismatch_confirmed = False
                position.save()
            elif action == 'confirm':
                position = get_object_or_404(work.positions, pk=request.POST.get('position'))
                position.mismatch_confirmed = True
                position.confirmed_composition = svc.composition(position)
                position.save()
            elif action == 'text':
                position = get_object_or_404(work.positions, pk=request.POST.get('position'))
                position.text = request.POST.get('text', '')
                position.save(update_fields=['text'])
            elif action == 'move':
                positions = list(work.positions.all())
                position = get_object_or_404(work.positions, pk=request.POST.get('position'))
                index = next(i for i, p in enumerate(positions) if p.pk == position.pk)
                target = index + (-1 if request.POST.get('direction') == 'up' else 1)
                if 0 <= target < len(positions):
                    positions[index], positions[target] = positions[target], positions[index]
                    for i, p in enumerate(positions, 1):
                        p.order = i
                        p.save(update_fields=['order'])
            else:
                raise svc.WorkError('Неизвестное действие.')
            work.save(update_fields=['updated_at'])
        messages.success(request, 'Сохранено')
        return redirect(request.get_full_path())
    positions = list(work.positions.prefetch_related('candidates__task__subitems'))
    number = 0
    for p in positions:
        p.rows = list(p.candidates.all())
        if p.rows or not p.text:
            number += 1
        p.number = number
        p.mismatch = len({len(svc.selected(c)) or 1 for c in p.rows}) > 1
        p.mismatch_confirmed = p.mismatch_confirmed and p.confirmed_composition == svc.composition(p)
        for candidate in p.rows:
            candidate.selected = svc.selected(candidate)
            candidate.point_count = len(candidate.selected) or 1
            candidate.mask_count = 0 if candidate.task.full_answer_only else sum(o.has_mask for o in (candidate.selected or [candidate.task]))
    return render(request, 'independentworks/edit.html', {'work': work, 'positions': positions, 'preparation_query': preparation_query(request)})


@enabled
@teacher_required
@require_POST
def copy_work(request, pk):
    old = get_object_or_404(Work.visible_to(request.user), pk=pk)
    with transaction.atomic():
        work = Work.objects.create(owner=request.user, title=(old.title + ' (копия)')[:190], source_worksheet=old.source_worksheet)
        for p in old.positions.prefetch_related('candidates'):
            new = Position.objects.create(work=work, order=p.order, text=p.text)
            for c in p.candidates.all():
                Candidate.objects.create(position=new, task=c.task, subitem_ids=c.subitem_ids)
    return redirect('independentworks:edit', pk=work.pk)


@enabled
@teacher_required
def pick(request, pk):
    position = get_object_or_404(Position, pk=pk, work__in=Work.visible_to(request.user))
    base = position.candidates.select_related('task').first()
    from problems.views import filter_tasks
    from problems.rubricator import taxonomy_page_context, filter_state_from_params
    query = request.GET.get('q', '')
    params = request.GET.copy()
    if query.isdigit():
        params.pop('q', None)
    tasks = filter_tasks(params).prefetch_related('analog_families', 'familymember_set__family')
    if query.isdigit():
        tasks = tasks.filter(pk=int(query))
    recommended = tasks.none()
    if base:
        family_ids = set(base.task.analog_families.values_list('pk', flat=True))
        if base.task.variant_of_id:
            family_ids.update(base.task.variant_of.analog_families.values_list('pk', flat=True))
        recommended = Task.objects.filter(variant_of__isnull=True, analog_families__in=family_ids).exclude(pk=base.task_id).distinct().prefetch_related('subitems', 'images', 'familymember_set__family')
    if request.method == 'POST':
        task = get_object_or_404(Task, pk=request.POST.get('task'), variant_of__isnull=True)
        try:
            ids = sorted(set(int(i) for i in request.POST.getlist('parts')))
        except ValueError:
            raise svc.WorkError('Неверный подпункт.')
        if task.subitems.filter(pk__in=ids).count() != len(ids):
            raise svc.WorkError('Подпункт не принадлежит задаче.')
        if request.POST.get('parts_mode') == 'all':
            ids = []
        elif request.POST.get('parts_mode') == 'selected' and not ids:
            raise svc.WorkError('Выберите хотя бы один подпункт или всю задачу.')
        if request.POST.get('candidate'):
            candidate = get_object_or_404(position.candidates, pk=request.POST['candidate'], task=task)
            with transaction.atomic():
                Work.objects.select_for_update().get(pk=position.work_id)
                candidate.subitem_ids = ids
                candidate.save(update_fields=['subitem_ids'])
                position.mismatch_confirmed = False
                position.save(update_fields=['mismatch_confirmed'])
                position.work.save(update_fields=['updated_at'])
            messages.success(request, 'Подпункты сохранены')
        else:
            svc.add_candidate(position, task, ids)
            messages.success(request, 'Кандидат добавлен')
        return redirect(request.get_full_path())
    from django.core.paginator import Paginator
    page = Paginator(tasks.order_by('-pk'), 15).get_page(request.GET.get('page'))
    context = taxonomy_page_context(filter_state_from_params(request.GET))
    context.update({'position': position, 'base': base, 'recommended': recommended[:30], 'page': page, 'q': query,
                    'params': request.GET, 'preparation_query': preparation_query(request), 'grade_choices': Task.GRADE_CHOICES,
                    'selected_candidates': position.candidates.select_related('task').prefetch_related('task__subitems', 'task__images')})
    return render(request, 'independentworks/pick.html', context)


@enabled
@teacher_required
@require_POST
def create_analog(request, pk, task_id):
    position = get_object_or_404(Position, pk=pk, work__in=Work.visible_to(request.user))
    task = get_object_or_404(Task.objects.select_related('variant_of'), pk=task_id)
    if task.variant_of_id and not position.candidates.filter(task=task).exists():
        raise Http404
    with transaction.atomic():
        copy = task.make_variant(request.user, standalone=True)
        family = task.analog_families.first()
        if not family and task.variant_of_id:
            family = task.variant_of.analog_families.first()
        if not family:
            family = Family.objects.create(key='manual:' + uuid.uuid4().hex, title='Аналоги задачи ' + str(task.pk))
            family.tasks.add(task)
        # Связь и пул дополняются после сохранения в обычном редакторе.
        request.session[f'iw_analog_{position.pk}_{copy.pk}'] = family.pk
    return redirect(reverse('task_detail', args=[copy.pk]) + '?iw_position=' + str(position.pk))


@enabled
@teacher_required
@require_POST
def finish_analog(request, pk, task_id):
    position = get_object_or_404(Position, pk=pk, work__in=Work.visible_to(request.user))
    family_id = request.session.get(f'iw_analog_{pk}_{task_id}')
    if not family_id:
        raise Http404
    task = get_object_or_404(Task, pk=task_id, created_by=request.user)
    with transaction.atomic():
        get_object_or_404(Family, pk=family_id).tasks.add(task)
        svc.add_candidate(position, task)
    del request.session[f'iw_analog_{pk}_{task_id}']
    return redirect('independentworks:pick', pk=position.pk)


@enabled
@teacher_required
def prepare_run(request, pk):
    work = get_object_or_404(Work.visible_to(request.user), pk=pk)
    if request.method == 'GET' and request.resolver_match.namespace == 'independentworks':
        params = request.GET.copy()
        params['mode'] = 'independent'
        params['work'] = str(pk)
        return redirect(reverse('assignment_create') + '?' + params.urlencode())
    parent = None
    if request.GET.get('parent'):
        parent = own_attempt(request, request.GET['parent'], teacher=True)
        if parent.run.work_id != work.pk:
            raise Http404
    kind = request.GET.get('kind', 'initial')
    if kind not in ('initial', 'correction', 'retake') or (kind == 'initial') != (parent is None):
        raise svc.WorkError('Неизвестный вид повторной попытки.')
    initial = {}
    previous = None
    if request.GET.get('resume'):
        previous = teacher_run(request, request.GET['resume'])
        if previous.work_id != work.pk or previous.parent_id != (parent.pk if parent else None) or previous.kind != kind:
            raise Http404
        initial = {key: getattr(previous, key) for key in ('duration', 'deadline', 'max_variants', 'allow_photos', 'release_mode', 'release_flags')}
        initial['students'] = list(previous.plan['students'])
    form = RunForm(request.POST or None, teacher=request.user, initial=initial)
    if request.method == 'POST' and form.is_valid():
        data = dict(form.cleaned_data)
        students = [parent.student_id] if parent else form.recipients(request.user)
        data.pop('students'); data.pop('groups')
        run = svc.prepare(work, request.user, students, parent=parent, kind=kind, previous=previous, **data)
        return redirect('independentworks:preview', pk=run.pk)
    return render(request, 'assignments/assignment_create.html', {'independent': True, 'work': work, 'form': form, 'parent': parent, 'kind': kind, 'timezone': timezone.get_current_timezone_name()})


def preview_context(run):
    names = {str(u.pk): u.get_full_name() or u.username for u in Profile.student_users_for(run.owner).filter(pk__in=run.plan['students'])}
    variants = []
    for vi, points in enumerate(run.plan['variants'], 1):
        visited, rows = set(), []
        for pi, point in enumerate(points, 1):
            snapshot = point['snapshot']
            rows.append({'point': point, 'common': snapshot.get('common', ''), 'text': snapshot['text'],
                'notes': [n['text'] for n in run.plan['notes'] if n['before'] == point['position']] if point['position'] not in visited else [],
                'content_images': [{'url': reverse('independentworks:preview_asset', args=[run.pk, vi, pi, ai]),
                                    'filename': asset['name'], 'is_pdf': asset['name'].lower().endswith('.pdf')}
                                   for ai, asset in enumerate(snapshot.get('assets', []), 1) if 'statement' in asset['audiences']],
                'reference': snapshot['answer'], 'solution': snapshot['solution'],
                'fragments': render_fragments(parse_mask(snapshot['mask']), f'preview{vi}p{pi}', {}, {}, seed=f'{vi}-{pi}') if parse_mask(snapshot['mask']).is_valid else None})
            rows[-1]['reference_images'] = [{'url': reverse('independentworks:preview_asset', args=[run.pk, vi, pi, ai]), 'filename': asset['name'], 'is_pdf': asset['name'].lower().endswith('.pdf')} for ai, asset in enumerate(snapshot.get('assets', []), 1) if set(asset['audiences']) & {'answer', 'solution'}]
            rows[-1]['repeated'] = point['source_key'] in run.plan['repeats']
            visited.add(point['position'])
        variants.append({'number': vi, 'rows': rows,
            'tail_notes': [n['text'] for n in run.plan['notes'] if n['before'] > max(visited, default=0)]})
    return {'run': run, 'variants': variants, 'recipients': [(pk, names.get(pk, pk), num) for pk, num in run.plan['students'].items()]}


@enabled
@teacher_required
def preview(request, pk):
    run = teacher_run(request, pk)
    if run.issued_at:
        return redirect('independentworks:progress', pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            run = Run.objects.select_for_update().get(pk=pk)
            if run.issued_at:
                raise svc.WorkError('Работа уже выдана.', 409)
            for student in run.plan['students']:
                value = request.POST.get('student_' + student)
                if not value or not value.isdigit() or not 1 <= int(value) <= len(run.plan['variants']):
                    raise svc.WorkError('Выберите существующий вариант каждому ученику.')
                run.plan['students'][student] = int(value)
            run.save(update_fields=['plan'])
        messages.success(request, 'Распределение сохранено')
        return redirect('independentworks:preview', pk=pk)
    return render(request, 'independentworks/preview.html', preview_context(run))


@enabled
@teacher_required
def preview_asset(request, pk, variant, point, asset):
    run = teacher_run(request, pk)
    try:
        source = run.plan['variants'][variant - 1][point - 1]['snapshot']['assets'][asset - 1]
        if min(variant, point, asset) < 1:
            raise IndexError
    except (IndexError, KeyError):
        raise Http404
    if 'asset_id' in source:
        file = get_object_or_404(Asset, pk=source['asset_id']).file.open('rb')
    else:
        from django.core.files.storage import default_storage
        file = default_storage.open(source['path'], 'rb')
    return FileResponse(file, filename=source['name'])


@enabled
@teacher_required
@require_POST
def issue_run(request, pk):
    run = teacher_run(request, pk)
    recipients = set(map(int, run.plan['students']))
    if set(Profile.student_users_for(request.user).filter(pk__in=recipients).values_list('pk', flat=True)) != recipients:
        raise svc.WorkError('Состав доступных учеников изменился.')
    svc.issue(pk, request.POST.get('confirm') == 'on')
    return redirect('independentworks:progress', pk=pk)


def point_rows(attempt, teacher=False):
    disclosure = svc.FLAGS if teacher else attempt.disclosure
    answers = {a.point_id: a for a in attempt.answers.all()}
    rows = []
    visited = set()
    for point in attempt.variant.points.all():
        answer = answers.get(point.pk)
        spec = parse_mask(point.snapshot['mask'])
        prefix = f'p{point.pk}'
        rows.append({'point': point, 'answer': answer, 'prefix': prefix,
                     'notes': [note['text'] for note in attempt.variant.notes if note['before'] == point.position] if point.position not in visited else [],
                     'common': point.snapshot.get('common', ''), 'text': point.snapshot['text'],
                     'fragments': render_fragments(spec, prefix, answer.values if answer else {}, answer.checks if answer and 'checks' in disclosure else {}, seed=prefix) if spec.is_valid else None,
                     'display': svc.answer_display(point, answer),
                     'reference': point.snapshot['answer'] if 'answer' in disclosure else '',
                     'solution': point.snapshot['solution'] if 'solution' in disclosure else '',
                     'comment': answer.comment if answer and 'comment' in disclosure else '',
                     'grade': (Review.SYMBOLS.get(answer.grade, answer.grade) + ' · ' + answer.get_grade_display()) if answer and answer.grade and 'checks' in disclosure else '',
                     'grade_symbol': Review.SYMBOLS.get(answer.grade, answer.grade) if answer and 'checks' in disclosure else '',
                     'grade_url': reverse('independentworks:review', args=[attempt.pk, point.pk]) if teacher else '',
                     'comment_name': f'p{point.pk}_comment',
                     'auto': answer.auto_check if answer and 'checks' in disclosure else '',
                     'pending': (answer.pending if answer else not spec.is_valid),
                     'assets': [a for a in point.assets.all() if 'statement' in a.audiences or set(a.audiences) & disclosure]})
        rows[-1]['content_images'] = [{'url': reverse('independentworks:asset', args=[attempt.pk, a.pk]), 'filename': a.name, 'is_pdf': a.name.lower().endswith('.pdf')} for a in rows[-1]['assets']]
        visited.add(point.position)
    return rows


@enabled
@teacher_required
def point_detail(request, pk, point_id):
    attempt = own_attempt(request, pk, teacher=True)
    svc.finish_expired(attempt)
    row = next((r for r in point_rows(attempt, teacher=True) if r['point'].pk == point_id), None)
    if row is None:
        raise Http404
    return render(request, 'independentworks/_point_review.html', {'attempt': attempt, 'row': row, 'grades': [('', 'По автосверке', '↺')] + Review.grade_options()})


@enabled
def attempt_page(request, pk):
    teacher = get_role(request.user) == 'teacher'
    attempt = own_attempt(request, pk, teacher=teacher)
    svc.finish_expired(attempt)
    accessible = teacher or bool(attempt.started_at)
    return render(request, 'independentworks/attempt.html', {
        'attempt': attempt, 'teacher_view': teacher, 'rows': point_rows(attempt, teacher) if accessible else [],
        'editable': not teacher and bool(attempt.started_at) and not attempt.finished,
        'can_start': not attempt.started_at and not (attempt.run.deadline and timezone.now() >= attempt.run.deadline),
        'accessible': accessible, 'show_checks': teacher or 'checks' in attempt.disclosure,
        'tail_notes': [n['text'] for n in attempt.variant.notes if n['before'] > max((p.position for p in attempt.variant.points.all()), default=0)] if accessible else [],
        'result': svc.result(attempt) if teacher or 'checks' in attempt.disclosure else None,
        'grades': [('', 'По автосверке', '↺')] + Review.grade_options(), 'now': timezone.now().isoformat(),
        'cumulative': svc.cumulative(attempt, student_view=not teacher) if teacher or 'checks' in attempt.disclosure else None})


@enabled
@require_POST
def start_attempt(request, pk):
    attempt = own_attempt(request, pk)
    svc.start(attempt.pk)
    return redirect('independentworks:attempt', pk=pk)


@enabled
@require_POST
def save(request, pk, point_id):
    attempt = own_attempt(request, pk)
    point = get_object_or_404(Point, pk=point_id, variant=attempt.variant)
    try:
        version = int(request.POST.get('version', '-1'))
    except ValueError:
        raise svc.WorkError('Неверная версия ответа.')
    values = collect_values(request.POST, f'p{point.pk}', parse_mask(point.snapshot['mask']))
    answer = svc.save_answer(pk, point_id, version, values)
    return JsonResponse({'version': answer.version, 'saved_at': answer.updated_at.isoformat(),
                         'state': 'saved', 'attempt_state': answer.attempt.state})


@enabled
@require_POST
def submit_attempt(request, pk):
    attempt = own_attempt(request, pk)
    svc.submit(attempt.pk)
    return redirect('independentworks:attempt', pk=pk)


@enabled
@teacher_required
@require_POST
def review(request, pk, point_id):
    attempt = own_attempt(request, pk, teacher=True)
    point = get_object_or_404(Point, pk=point_id, variant=attempt.variant)
    if not attempt.finished:
        raise svc.WorkError('Ручная проверка доступна после сдачи.')
    grade = request.POST.get('grade', '')
    if grade not in dict(Review.GRADE_CHOICES) and grade != '':
        raise svc.WorkError('Неизвестная оценка.')
    with transaction.atomic():
        Attempt.objects.select_for_update().get(pk=pk)
        answer, _ = Answer.objects.get_or_create(attempt=attempt, point=point)
        if 'grade' in request.POST:
            answer.grade = grade
        comment_key = f'p{point.pk}_comment'
        if 'comment' in request.POST or comment_key in request.POST:
            answer.comment = request.POST.get(comment_key, request.POST.get('comment', ''))[:20000]
        answer.save(update_fields=['grade', 'comment', 'updated_at'])
    if request.headers.get('Accept') == 'application/json':
        # own_attempt заранее загрузил ответы; после проверки нужен свежий итог.
        attempt._prefetched_objects_cache.pop('answers', None)
        feedback = (Review.SYMBOLS.get(answer.grade, answer.grade) + ' · ' + answer.get_grade_display()) if answer.grade else ('На проверке' if answer.pending else {'ok': 'Верно', 'wrong': 'Неверно'}.get(answer.auto_check, 'Ответ не введён'))
        return JsonResponse({'grade': answer.grade, 'feedback': feedback, 'result': svc.result(attempt), 'cumulative': svc.cumulative(attempt)})
    messages.success(request, 'Проверка сохранена')
    return redirect('independentworks:attempt', pk=pk)


@enabled
@teacher_required
@require_POST
def publish(request, pk):
    run = teacher_run(request, pk)
    ids = request.POST.getlist('attempts')
    flags = sorted(set(request.POST.getlist('flags')) & svc.FLAGS)
    if not flags:
        raise svc.WorkError('Выберите хотя бы одну категорию для публикации.')
    with transaction.atomic():
        selected_attempts = run.attempts.select_for_update().select_related('run')
        if ids:
            selected_attempts = selected_attempts.filter(pk__in=ids)
        for attempt in selected_attempts:
            if attempt.finished:
                combined = sorted(attempt.disclosure | set(flags))
                Attempt.objects.filter(pk=attempt.pk).update(published_at=timezone.now(), release_flags=combined)
    messages.success(request, 'Разрешения публикации сохранены')
    return redirect('independentworks:progress', pk=pk)


@enabled
@teacher_required
@require_POST
def recipients(request, pk):
    run = teacher_run(request, pk)
    try:
        students = {int(value) for value in request.POST.getlist('students')}
        choices = {student: int(request.POST.get(f'variant_{student}', '')) for student in students}
    except ValueError:
        raise svc.WorkError('Выберите учеников и варианты.')
    svc.update_recipients(run.pk, students, choices)
    messages.success(request, 'Получатели самостоятельной сохранены')
    return redirect(reverse('assignment_list') + ('?' + request.GET.urlencode() if request.GET else ''))


@enabled
@teacher_required
@require_POST
def reassign(request, pk):
    attempt = own_attempt(request, pk, teacher=True)
    variant = get_object_or_404(attempt.run.variants, pk=request.POST.get('variant'))
    changed = Attempt.objects.filter(pk=pk, started_at__isnull=True).update(variant=variant)
    if not changed:
        raise svc.WorkError('Ученик уже начал работу.', 409)
    return redirect('independentworks:progress', pk=attempt.run_id)


@enabled
@teacher_required
@require_POST
def repeat(request, pk):
    attempt = own_attempt(request, pk, teacher=True)
    kind = request.POST.get('kind')
    if kind not in ('correction', 'retake'):
        raise svc.WorkError('Неизвестный вид попытки.')
    return redirect(reverse('independentworks:prepare', args=[attempt.run.work_id]) + f'?parent={pk}&kind={kind}')


@enabled
@require_POST
def upload_photo(request, pk, point_id):
    attempt = own_attempt(request, pk)
    point = get_object_or_404(Point, pk=point_id, variant=attempt.variant)
    if not attempt.run.allow_photos:
        raise PermissionDenied
    uploaded = request.FILES.get('photo')
    if not uploaded or uploaded.size > settings.SUBMISSION_PHOTO_MAX_SIZE_MB * 1024 * 1024:
        raise svc.WorkError('Выберите фотографию допустимого размера.')
    try:
        content = SubmissionPhoto._compress(uploaded)
    except Exception:
        raise svc.WorkError('Не удалось прочитать фотографию.')
    with transaction.atomic():
        locked = Attempt.objects.select_for_update().get(pk=pk)
        svc.editable(locked)
        answer, _ = Answer.objects.get_or_create(attempt=attempt, point=point)
        if answer.photos.count() >= settings.SUBMISSION_PHOTO_MAX_COUNT:
            raise svc.WorkError('Достигнуто ограничение числа фотографий.')
        photo = Photo(answer=answer)
        photo.file.save(uuid.uuid4().hex + '.jpg', content, save=True)
    return redirect('independentworks:attempt', pk=pk)


@enabled
@require_POST
def delete_photo(request, pk):
    photo = get_object_or_404(Photo.objects.select_related('answer__attempt'), pk=pk, answer__attempt__student=request.user)
    with transaction.atomic():
        attempt = Attempt.objects.select_for_update().get(pk=photo.answer.attempt_id)
        svc.editable(attempt)
        photo.delete()
    return redirect('independentworks:attempt', pk=attempt.pk)


@enabled
def asset_file(request, pk, asset_id):
    teacher = get_role(request.user) == 'teacher'
    attempt = own_attempt(request, pk, teacher=teacher)
    asset = get_object_or_404(Asset, pk=asset_id, point__variant=attempt.variant)
    if not teacher and (not attempt.started_at or ('statement' not in asset.audiences and not set(asset.audiences) & attempt.disclosure)):
        raise Http404
    return FileResponse(asset.file.open('rb'), filename=asset.name)


@enabled
def photo_file(request, pk):
    photo = get_object_or_404(Photo.objects.select_related('answer__attempt__run'), pk=pk)
    own_attempt(request, photo.answer.attempt_id, teacher=get_role(request.user) == 'teacher')
    return FileResponse(photo.file.open('rb'), filename='solution.jpg')


def progress_context(run):
    attempts = list(run.attempts.select_related('student', 'run', 'variant', 'root').prefetch_related('variant__points__assets', 'answers__photos', 'answers__point', 'corrections__answers__point', 'root__variant__points', 'root__answers__point', 'root__corrections__answers__point'))
    numbers = sorted(set(p.position for a in attempts for p in a.variant.points.all()))
    people = []
    stats = {}
    for a in attempts:
        svc.finish_expired(a)
        rows = point_rows(a, teacher=True)
        cells = []
        for number in numbers:
            points = []
            for row in rows:
                if row['point'].position != number:
                    continue
                status = 'ok' if row['auto'] == 'ok' else 'wrong' if row['auto'] == 'wrong' else 'draft' if row['answer'] else 'empty'
                if row['answer'] and row['answer'].grade:
                    status = 'ok' if row['answer'].credit == 1 else 'draft' if row['answer'].credit else 'wrong'
                points.append({'detail_url': reverse('independentworks:point_detail', args=[a.pk, row['point'].pk]), 'label': row['point'].label, 'status': status, 'status_label': row['grade'] or ('На проверке' if row['pending'] else {'ok': 'Верно', 'wrong': 'Неверно'}.get(row['auto'], 'Ответ не введён')), 'mark': row['grade_symbol'], 'attempt_count': 0})
            cells.append({'item': {'pk': number}, 'owner': {'pk': number}, 'points': points, 'hidden': not points})
        remaining = max(0, int((a.ends_at - timezone.now()).total_seconds())) if a.ends_at else 0
        people.append({'attempt': a, 'assignment': a, 'review_url': reverse('independentworks:attempt', args=[a.pk]), 'cells': cells, 'result': svc.result(a), 'cumulative': svc.cumulative(a), 'show_cumulative': bool(a.root_id or any(c.started_at for c in a.corrections.all())),
                       'remaining': f'{remaining // 60}:{remaining % 60:02}'})
        if a.started_at:
            for row in rows:
                key = row['point'].candidate_key
                stat = stats.setdefault(key, {'key': key, 'students': set(), 'variants': set(), 'positions': set(), 'points': 0, 'done': 0})
                stat['students'].add(a.student_id)
                stat['variants'].add(a.variant.number)
                stat['positions'].add(row['point'].position)
                stat['points'] += 1
                stat['done'] += row['answer'].credit if row['answer'] else 0
    for stat in stats.values():
        stat['count'] = len(stat.pop('students'))
        stat['label'] = '№' + ', '.join(map(str, sorted(stat.pop('positions')))) + ' · варианты ' + ', '.join(map(str, sorted(stat.pop('variants'))))
        stat['percent'] = round(100 * stat['done'] / stat['points'])
    return {'independent': True, 'point_groups': [{'item': {'pk': n}, 'number': n, 'columns': [{'owner': {'pk': n}, 'label': 'Пункты'}]} for n in numbers], 'run': run, 'people': people, 'numbers': numbers, 'stats': list(stats.values()), 'variants': run.variants.all()}


@enabled
@teacher_required
def progress(request, pk):
    run = teacher_run(request, pk)
    context = progress_context(run)
    if request.GET.get('fragment'):
        from django.template.loader import render_to_string
        html = render_to_string('independentworks/_progress.html', context, request=request)
        etag = '"' + svc.digest(html) + '"'
        response = HttpResponseNotModified() if request.headers.get('If-None-Match') == etag else HttpResponse(html)
        response['ETag'] = etag
        return response
    return render(request, 'independentworks/progress.html', context)


@enabled
@teacher_required
def export(request, pk):
    from openpyxl import Workbook
    run = teacher_run(request, pk)
    book = Workbook()
    summary = book.active
    summary.title = 'Сводка'
    detail = book.create_sheet('Пункты')
    summary.append(['Ученик', 'Попытка', 'Вариант', 'Статус', 'Зачтено', 'Всего', 'Процент', 'На проверке', 'С учётом исправлений'])
    detail.append(['Ученик', 'Попытка', 'Пункт', 'Ответ', 'Автосверка', 'Знак', 'Комментарий', 'Зачтено'])
    for item in progress_context(run)['people']:
        a, result = item['attempt'], item['result']
        name = a.student.get_full_name() or a.student.username
        summary.append([name, a.pk, a.variant.number, a.state, result['done'], result['total'], result['percent'], result['pending'], item['cumulative']['percent'] if a.started_at else None])
        for row in point_rows(a, teacher=True):
            answer = row['answer']
            detail.append([name, a.pk, row['point'].label, row['display'], row['auto'] or 'На проверке', answer.grade if answer else '', row['comment'], answer.credit if answer else None])
    for sheet in book:
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 22
    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)
    return FileResponse(stream, as_attachment=True, filename=f'independent-work-{pk}.xlsx')

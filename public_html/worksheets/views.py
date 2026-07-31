from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import get_role, teacher_required
from accounts.models import Profile
from problems.models import Task
from problems.views import filter_tasks

from .forms import WorksheetForm
from .latex import worksheet_to_tex
from .models import ShareLink, Worksheet, WorksheetItem, WorksheetPdf
from .services import LatexCompileError, get_worksheet_pdf


def _own_worksheet(request, pk):
    return get_object_or_404(Worksheet, pk=pk, owner=request.user)


@teacher_required
def worksheet_list(request):
    worksheets = Worksheet.objects.filter(owner=request.user)
    return render(request, 'worksheets/worksheet_list.html', {
        'worksheets': worksheets,
    })


@teacher_required
def worksheet_create(request):
    if request.method == 'POST':
        form = WorksheetForm(request.POST)
        if form.is_valid():
            worksheet = form.save(commit=False)
            worksheet.owner = request.user
            worksheet.save()
            messages.success(request, 'Листок создан. Добавьте в него задачи.')
            return redirect('worksheet_detail', pk=worksheet.pk)
    else:
        form = WorksheetForm()
    return render(request, 'worksheets/worksheet_form.html', {'form': form})


@teacher_required
def worksheet_edit(request, pk):
    worksheet = _own_worksheet(request, pk)
    if request.method == 'POST':
        form = WorksheetForm(request.POST, instance=worksheet)
        if form.is_valid():
            form.save()
            messages.success(request, 'Листок сохранён.')
            return redirect('worksheet_detail', pk=worksheet.pk)
    else:
        form = WorksheetForm(instance=worksheet)
    return render(request, 'worksheets/worksheet_form.html', {
        'form': form, 'worksheet': worksheet,
    })


@teacher_required
def worksheet_detail(request, pk):
    """Конструктор листка: задачи, поиск по базе, назначение, ссылки."""
    worksheet = _own_worksheet(request, pk)
    items = worksheet.ordered_items()
    task_ids = [item.task_id for item in items]

    # Поиск задач для добавления (правая часть страницы)
    search_active = any(request.GET.get(k) for k in ('q', 'topic', 'grade', 'tag'))
    found_tasks = []
    if search_active:
        found_tasks = filter_tasks(request.GET).exclude(pk__in=task_ids)[:15]

    student_profiles = (Profile.objects
                        .filter(teacher=request.user, role=Profile.ROLE_STUDENT)
                        .select_related('user')
                        .order_by('user__last_name'))
    assigned_ids = set(
        worksheet.assignments.values_list('student_id', flat=True))

    return render(request, 'worksheets/worksheet_detail.html', {
        'worksheet': worksheet,
        'items': items,
        'found_tasks': found_tasks,
        'search_active': search_active,
        'params': request.GET,
        'student_profiles': student_profiles,
        'assigned_ids': assigned_ids,
        'share_links': worksheet.share_links.order_by('-created_at'),
        'assignments': worksheet.assignments.select_related('student'),
    })


def add_task_to_worksheet(request, worksheet_id, task):
    """Добавляет задачу в конец листка (используется и из создания задачи)."""
    worksheet = get_object_or_404(
        Worksheet, pk=worksheet_id, owner=request.user)
    last = worksheet.items.aggregate(m=models.Max('order'))['m'] or 0
    WorksheetItem.objects.create(
        worksheet=worksheet, task=task, order=last + 10)
    messages.success(request, f'Задача #{task.pk} добавлена в «{worksheet.title}».')
    return redirect('worksheet_detail', pk=worksheet.pk)


@teacher_required
@require_POST
def worksheet_add_task(request, pk):
    task = get_object_or_404(Task, pk=request.POST.get('task_id'))
    return add_task_to_worksheet(request, pk, task)


@teacher_required
@require_POST
def worksheet_remove_item(request, pk, item_id):
    worksheet = _own_worksheet(request, pk)
    item = get_object_or_404(WorksheetItem, pk=item_id, worksheet=worksheet)
    item.delete()
    messages.success(request, 'Задача убрана из листка.')
    return redirect('worksheet_detail', pk=pk)


@teacher_required
@require_POST
def worksheet_move_item(request, pk, item_id, direction):
    worksheet = _own_worksheet(request, pk)
    items = list(worksheet.ordered_items())
    idx = next((i for i, it in enumerate(items) if it.pk == item_id), None)
    if idx is None:
        raise Http404
    other = idx - 1 if direction == 'up' else idx + 1
    if 0 <= other < len(items):
        items[idx].order, items[other].order = items[other].order, items[idx].order
        # Совпадающие order (например, все 0) — перенумеруем целиком
        if items[idx].order == items[other].order:
            items[idx], items[other] = items[other], items[idx]
            for i, it in enumerate(items):
                it.order = (i + 1) * 10
            WorksheetItem.objects.bulk_update(items, ['order'])
        else:
            WorksheetItem.objects.bulk_update(
                [items[idx], items[other]], ['order'])
    return redirect('worksheet_detail', pk=pk)


@teacher_required
@require_POST
def worksheet_set_rubric(request, pk, item_id):
    worksheet = _own_worksheet(request, pk)
    item = get_object_or_404(WorksheetItem, pk=item_id, worksheet=worksheet)
    item.rubric = request.POST.get('rubric', '').strip()
    item.rubric_note = request.POST.get('rubric_note', '').strip()
    item.save()
    return redirect('worksheet_detail', pk=pk)


def _worksheet_pdf_response(worksheet, variant):
    pdf = get_worksheet_pdf(worksheet, variant)
    return FileResponse(
        pdf.file.open('rb'), content_type='application/pdf',
        filename=f'{worksheet.title}-{variant}.pdf'.replace(' ', '_'))


def worksheet_pdf(request, pk):
    """PDF листка. Учитель-владелец — любой вариант, назначенный ученик — без ответов."""
    if not request.user.is_authenticated:
        raise PermissionDenied
    worksheet = get_object_or_404(Worksheet, pk=pk)
    variant = request.GET.get('variant', WorksheetPdf.VARIANT_STUDENT)
    if variant not in dict(WorksheetPdf.VARIANT_CHOICES):
        raise Http404

    role = get_role(request.user)
    is_owner = worksheet.owner_id == request.user.pk
    is_assigned_student = (
        role == Profile.ROLE_STUDENT
        and worksheet.assignments.filter(student=request.user).exists())
    if not (is_owner or (is_assigned_student
                         and variant == WorksheetPdf.VARIANT_STUDENT)):
        raise PermissionDenied

    try:
        return _worksheet_pdf_response(worksheet, variant)
    except LatexCompileError as exc:
        if not is_owner:
            raise Http404
        return render(request, 'worksheets/latex_error.html', {
            'worksheet': worksheet,
            'error': exc,
            'tex': worksheet_to_tex(worksheet, variant),
        }, status=502)


@teacher_required
def worksheet_tex(request, pk):
    """Показ .tex-исходника (для отладки ошибок компиляции)."""
    worksheet = _own_worksheet(request, pk)
    variant = request.GET.get('variant', WorksheetPdf.VARIANT_STUDENT)
    if variant not in dict(WorksheetPdf.VARIANT_CHOICES):
        raise Http404
    tex = worksheet_to_tex(worksheet, variant)
    return render(request, 'worksheets/tex_source.html', {
        'worksheet': worksheet, 'tex': tex, 'variant': variant,
    })


@teacher_required
@require_POST
def share_create(request, pk):
    worksheet = _own_worksheet(request, pk)
    ShareLink.objects.create(worksheet=worksheet)
    messages.success(request, 'Публичная ссылка создана.')
    return redirect('worksheet_detail', pk=pk)


@teacher_required
@require_POST
def share_toggle(request, pk, link_id):
    worksheet = _own_worksheet(request, pk)
    link = get_object_or_404(ShareLink, pk=link_id, worksheet=worksheet)
    link.is_active = not link.is_active
    link.save()
    return redirect('worksheet_detail', pk=pk)


# --- Публичные страницы (без входа) ---

def _shared_worksheet(token):
    link = ShareLink.objects.filter(token=token, is_active=True).first()
    if link is None:
        raise Http404
    return link.worksheet


def public_worksheet(request, token):
    worksheet = _shared_worksheet(token)
    return render(request, 'worksheets/public.html', {
        'worksheet': worksheet,
        'items': worksheet.ordered_items(),
        'token': token,
    })


def public_worksheet_pdf(request, token):
    worksheet = _shared_worksheet(token)
    try:
        return _worksheet_pdf_response(worksheet, WorksheetPdf.VARIANT_STUDENT)
    except LatexCompileError:
        raise Http404

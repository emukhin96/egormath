from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import teacher_required

from .forms import TaskForm, TaskSourceFormSet
from .models import Tag, Task, Topic


def filter_tasks(params):
    """Каталог задач по GET-параметрам: q, topic, grade, tag."""
    tasks = (Task.objects.all()
             .prefetch_related('topics', 'tags', 'source_refs__source')
             .select_related('created_by'))
    q = params.get('q', '').strip()
    if q:
        tasks = tasks.filter(
            Q(text_plain__icontains=q) | Q(text_latex__icontains=q))
    topic_id = params.get('topic')
    if topic_id:
        try:
            topic = Topic.objects.get(pk=topic_id)
            tasks = tasks.filter(topics__in=topic.descendants_ids()).distinct()
        except (Topic.DoesNotExist, ValueError):
            pass
    grade = params.get('grade')
    if grade:
        tasks = tasks.filter(grade_level=grade)
    tag = params.get('tag')
    if tag:
        tasks = tasks.filter(tags__name=tag)
    return tasks


@teacher_required
def task_list(request):
    tasks = filter_tasks(request.GET)
    paginator = Paginator(tasks, 25)
    page = paginator.get_page(request.GET.get('page'))
    topics = Topic.objects.filter(parent=None).prefetch_related('children')
    current_topic = None
    if request.GET.get('topic'):
        current_topic = Topic.objects.filter(pk=request.GET['topic']).first()
    return render(request, 'problems/task_list.html', {
        'page': page,
        'topics': topics,
        'tags': Tag.objects.all(),
        'current_topic': current_topic,
        'params': request.GET,
        'grade_choices': Task.GRADE_CHOICES,
    })


@teacher_required
def task_detail(request, pk):
    task = get_object_or_404(
        Task.objects.prefetch_related('topics', 'tags', 'source_refs__source'),
        pk=pk)
    return render(request, 'problems/task_detail.html', {'task': task})


@teacher_required
def task_create(request):
    return _task_form(request, task=None)


@teacher_required
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk)
    return _task_form(request, task=task)


def _task_form(request, task):
    if request.method == 'POST':
        form = TaskForm(request.POST, instance=task)
        formset = TaskSourceFormSet(request.POST, instance=task or form.instance)
        if form.is_valid():
            obj = form.save(commit=False)
            if task is None:
                obj.created_by = request.user
            obj.save()
            form.save_m2m()
            formset = TaskSourceFormSet(request.POST, instance=obj)
            if formset.is_valid():
                formset.save()
                messages.success(request, 'Задача сохранена.')
                # Из конструктора листка: добавить задачу и вернуться в него
                worksheet_id = request.GET.get('worksheet')
                if worksheet_id:
                    from worksheets.views import add_task_to_worksheet
                    return add_task_to_worksheet(request, worksheet_id, obj)
                return redirect('task_detail', pk=obj.pk)
    else:
        form = TaskForm(instance=task)
        formset = TaskSourceFormSet(instance=task)
    return render(request, 'problems/task_form.html', {
        'form': form,
        'formset': formset,
        'task': task,
    })

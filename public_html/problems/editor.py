"""Единый редактор: формы блоков, маски и локальные копии листка."""
import json

from django import forms
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import inlineformset_factory
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse

from accounts.decorators import teacher_required
from assignments.checks import HELP, KINDS, PRESETS
from .forms import TaskForm, TaskImageFormSet, TaskSourceFormSet, clean_mask_text
from .models import Task, TaskSubitem, Tag
from .rubricator import (apply_task_taxonomy, taxonomy_page_context,
                         task_taxonomy_state)


BLOCKS = {
    'condition': ['text_latex'],
    'answer': ['author_answer_latex', 'answer_latex'],
    'solution': ['author_solution_latex', 'solution_latex'],
    'metadata': ['stars', 'columns'],
    'mask': ['answer_mask'],
}
StructureFormSet = inlineformset_factory(
    Task, TaskSubitem, fields=['order', 'text_latex'], extra=1, can_delete=True,
    widgets={'text_latex': forms.Textarea(attrs={'rows': 2})})


def block_form(block, obj, data=None):
    """ModelForm ограничена полями одного блока, соседние правки не затирает."""
    cls = forms.modelform_factory(type(obj), form=TaskForm,
                                 fields=BLOCKS[block])
    form = cls(data, instance=obj, auto_id=f'id_{block}_{obj.pk}_%s')
    return form


def worksheet_context(request, task):
    """Контекст правки разрешён только владельцу листка или администратору."""
    from worksheets.models import WorksheetItem
    item_id = request.GET.get('item') or request.POST.get('item')
    worksheet_id = request.GET.get('worksheet') or request.POST.get('worksheet')
    if not item_id and not worksheet_id:
        return None
    item = get_object_or_404(WorksheetItem.objects.select_related('worksheet'),
                             pk=item_id, worksheet_id=worksheet_id, task=task)
    if item.worksheet.owner_id != request.user.pk and not request.user.is_superuser:
        raise PermissionDenied
    return item


def context(request, task):
    item = worksheet_context(request, task)
    ctx = taxonomy_page_context(task_taxonomy_state(task))
    ctx.update(task=task, item=item, worksheet=item.worksheet if item else None,
               tags_value=', '.join(task.tags.values_list('name', flat=True)),
               mask_help=HELP, mask_kinds={**KINDS, **{k: k for k in PRESETS}},
               condition_form=block_form('condition', task),
               answer_form=block_form('answer', task),
               solution_form=block_form('solution', task),
               metadata_form=block_form('metadata', task),
               structure_formset=StructureFormSet(instance=task),
               image_formset=TaskImageFormSet(instance=task),
               source_formset=TaskSourceFormSet(instance=task),
               subrows=[dict(sub=s, answer_form=block_form('answer', s),
                             solution_form=block_form('solution', s))
                        for s in task.subitems.all()])
    return ctx


def mask_data(task, item=None, include_preview=False):
    positions = {pk: n + 1 for n, pk in enumerate(task.subitems.values_list('pk', flat=True))}
    subs = list(item.selected_subitems() if item else task.subitems.all())
    owners = subs or ([] if task.subitems.exists() else [task])
    answers = [{'id': o.pk if isinstance(o, TaskSubitem) else None,
             'label': f'Подпункт {positions[o.pk]}' if isinstance(o, TaskSubitem) else 'Ответ',
             'text': o.text_latex,
             'condition': task.text_latex + ('\n' + o.text_latex if isinstance(o, TaskSubitem) else ''),
             'author': o.author_answer_latex,
             'editor': o.answer_latex, 'mask': o.answer_mask}
            for o in owners]
    if include_preview:
        from assignments.checks import render_fragments, parse_mask
        for answer in answers:
            spec = parse_mask(answer['mask'])
            answer['preview_html'] = render_to_string('assignments/_mask.html', {
                'fragments': render_fragments(spec, f'inline_{item.pk if item else 0}_{task.pk}_{answer["id"] or 0}',
                    values={slot.name: ('|'.join(str(i) for i in range(len(slot.items)))
                            if slot.kind == 'order' else slot.reference) for slot in spec.slots}),
                'editable': True, 'show_checks': False}) if spec.is_valid else ''
    return answers


def local_copy(task, item, user):
    """Переносит ровно выбранные подпункты на копию, не расширяя листок."""
    chosen = list(item.subitems.values_list('pk', flat=True))
    copy, mappings = task.make_variant(user, with_mapping=True)
    mapping = mappings['subitems']
    item.task = copy
    item.save(update_fields=['task'])
    if not set(chosen).issubset(mapping):
        raise forms.ValidationError('Не удалось перенести выбранные подпункты')
    item.subitems.set([mapping[pk] for pk in chosen])
    return copy, mappings


@teacher_required
def manage(request, pk):
    task = get_object_or_404(Task, pk=pk)
    item = worksheet_context(request, task)
    selected_only = request.GET.get('view') != 'task'
    if request.method == 'GET':
        return JsonResponse({'ok': True, 'answers': mask_data(task, item if selected_only else None, include_preview=request.GET.get('preview') == '1')})
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=pk)
        block = request.POST.get('block')
        if block not in {*BLOCKS, 'subitems', 'images', 'sources', 'masks'}:
            return JsonResponse({'ok': False, 'errors': {'__all__': ['Неизвестный блок']}}, status=400)
        scope = request.POST.get('scope', 'global' if item is None else '')
        if scope not in ('global', 'local') or (scope == 'local' and item is None):
            return JsonResponse({'ok': False, 'errors': {'__all__': ['Выберите область сохранения']}}, status=400)
        data = request.POST.copy()
        subid = data.get('subitem')
        owner = get_object_or_404(TaskSubitem, pk=subid, task=task) if subid else task
        if subid and block not in ('answer', 'solution', 'mask'):
            return JsonResponse({'ok': False}, status=400)
        # Проверяем всё до создания копии; ошибка откатывает любые изменения.
        formsets = {'subitems': StructureFormSet, 'images': TaskImageFormSet,
                    'sources': TaskSourceFormSet}
        factory = formsets.get(block)
        if factory:
            form = factory(data, request.FILES, instance=task)
        elif block != 'masks':
            form = block_form(block, owner, data)
        else:
            form = None
        if form is not None and not form.is_valid():
            errors = (form.errors if not factory else
                      {'__all__': [str(e) for e in form.non_form_errors()] +
                       [f'Строка {i+1}: {e}' for i, e in enumerate(form.errors) if e]})
            return JsonResponse({'ok': False, 'errors': errors}, status=400)
        if factory:
            allowed_ids = set(form.get_queryset().values_list('pk', flat=True))
            if any(f.cleaned_data.get('id') and f.cleaned_data['id'].pk not in allowed_ids
                   for f in form.forms):
                return JsonResponse({'ok': False, 'errors': {'__all__': ['Строка относится к другой задаче']}}, status=400)
        changes = []
        if block == 'masks':
            try:
                submitted = json.loads(data.get('masks', '[]'))
                allowed = {o['id']: o for o in mask_data(task, item if selected_only else None)}
                if not isinstance(submitted, list) or not submitted:
                    raise ValueError('Нет масок для сохранения')
                seen = set()
                for row in submitted:
                    if not isinstance(row, dict) or not isinstance(row.get('mask'), str):
                        raise ValueError('Маска должна быть текстом')
                    key = row['id']
                    if key not in allowed or key in seen:
                        raise ValueError('Подпункт не выбран или указан повторно')
                    seen.add(key)
                    changes.append((key, clean_mask_text(row['mask'])))
            except (ValueError, TypeError, KeyError, forms.ValidationError) as exc:
                return JsonResponse({'ok': False, 'errors': {'__all__': [str(exc)]}}, status=400)
        if block == 'metadata':
            names = [s.strip() for s in data.get('tags', '').split(',') if s.strip()]
            if any(len(s) > Tag._meta.get_field('name').max_length for s in names):
                return JsonResponse({'ok': False, 'errors': {'tags': ['Слишком длинный тег']}}, status=400)
        if scope == 'local':
            # is_valid() меняет instance в памяти: копировать нужно исходник из БД.
            try:
                task, mappings = local_copy(Task.objects.get(pk=pk), item, request.user)
            except forms.ValidationError as exc:
                transaction.set_rollback(True)
                return JsonResponse({'ok': False, 'errors': {'__all__': exc.messages}}, status=400)
            mapping = mappings['subitems']
            if factory:
                related = {'subitems': 'subitems', 'images': 'images', 'sources': 'source_refs'}[block]
                id_map = mappings[related]
                for field in data:
                    if field.startswith(form.prefix + '-') and field.endswith('-id') and data[field]:
                        new_id = id_map.get(int(data[field])) if data[field].isdigit() else None
                        if new_id is None:
                            transaction.set_rollback(True)
                            return JsonResponse({'ok': False, 'errors': {'__all__': ['Не удалось перенести строку формы']}}, status=400)
                        data[field] = str(new_id)
                form = factory(data, request.FILES, instance=task)
            elif form:
                owner = task.subitems.get(pk=mapping[int(subid)]) if subid else task
                form = block_form(block, owner, data)
            changes = [(mapping[key] if key else None, mask) for key, mask in changes]
            if form is not None and not form.is_valid():
                transaction.set_rollback(True)
                return JsonResponse({'ok': False, 'errors': {'__all__': ['Не удалось перенести форму']}}, status=400)
        if form is not None:
            form.save()
        for key, mask in changes:
            obj = task.subitems.get(pk=key) if key else task
            if data.get('missing_only') and obj.answer_mask.strip():
                continue
            obj.answer_mask = mask
            obj.save(update_fields=['answer_mask'])
        if block == 'metadata':
            apply_task_taxonomy(task, data)
            task.tags.set([Tag.objects.get_or_create(name=name)[0] for name in names])
        # Подпункты и формсеты тоже меняют дату задачи для повторной проверки масок.
        from django.utils import timezone
        Task.objects.filter(pk=task.pk).update(updated_at=timezone.now())
        task.refresh_from_db()
        url = reverse('task_detail', args=[task.pk])
        if item:
            url += f'?worksheet={item.worksheet_id}&item={item.pk}'
        # Контекст обновлённой копии отличается от исходного URL запроса.
        if scope == 'local':
            request.GET = request.GET.copy()
            request.GET['worksheet'] = str(item.worksheet_id)
            request.GET['item'] = str(item.pk)
        html = render_to_string('problems/_editor.html', context(request, task), request=request)
        return JsonResponse({'ok': True, 'html': html, 'url': url,
                             'task_id': task.pk, 'answers': mask_data(task, item if selected_only else None),
                             'sidebar': render_to_string('includes/sidebar/task_detail.html', {'task': task}, request=request)})

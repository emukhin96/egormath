"""Несохранённый аналог в общей форме создания задачи."""
from django.contrib import messages
from django.db import transaction
from django.forms.models import model_to_dict
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from problems.forms import TaskForm, TaskSourceFormSet, TaskSubitemFormSet, TaskImageFormSet
from problems.models import Task
from problems.rubricator import apply_task_taxonomy, task_taxonomy_state, taxonomy_state_from_post, taxonomy_page_context
from assignments.checks import HELP
from .models import Position, Work, Family
from . import services as svc


def draft(request, pk, token):
    key = 'iw_analog_draft_' + token
    state = request.session.get(key)
    if not state or state['position'] != pk:
        raise Http404
    position = get_object_or_404(Position, pk=pk, work__in=Work.visible_to(request.user))
    back = reverse('independentworks:pick', args=[pk])
    if state.get('saved'):
        return redirect(back)
    source = get_object_or_404(Task, pk=state['source'])
    posted = request.method == 'POST'
    form = TaskForm(request.POST if posted else None,
        initial=model_to_dict(source, fields=TaskForm.Meta.fields))
    source_initial = [model_to_dict(ref, fields=['source', 'number']) for ref in source.source_refs.all()]
    sub_initial = [model_to_dict(part, fields=[f for f in TaskSubitemFormSet.form.Meta.fields if f != 'task']) for part in source.subitems.all()]
    source_fs = TaskSourceFormSet(request.POST if posted else None, instance=form.instance, initial=source_initial if not posted else None)
    sub_fs = TaskSubitemFormSet(request.POST if posted else None, instance=form.instance, initial=sub_initial if not posted else None)
    image_fs = TaskImageFormSet(request.POST if posted else None, request.FILES if posted else None, instance=form.instance)
    if not posted:
        source_fs.extra = max(1, len(source_initial))
        sub_fs.extra = max(1, len(sub_initial))
    if posted and all([form.is_valid(), source_fs.is_valid(), sub_fs.is_valid(), image_fs.is_valid()]):
        with transaction.atomic():
            Work.objects.select_for_update().get(pk=position.work_id)
            copy = source.make_variant(request.user, standalone=True)
            for field, value in form.cleaned_data.items():
                setattr(copy, field, value)
            copy.save()
            apply_task_taxonomy(copy, request.POST)
            # Структуру подпунктов задаёт общая форма. Унаследованные
            # картинки сохраняются; новые файлы добавляет её image formset.
            copy.subitems.all().delete()
            copy.source_refs.all().delete()
            source_fs.instance = sub_fs.instance = image_fs.instance = copy
            source_fs.save()
            originals = {(ref.source_id, ref.number): ref for ref in source.source_refs.all()}
            for ref in copy.source_refs.all():
                original = originals.get((ref.source_id, ref.number))
                if original:
                    ref.source_path, ref.page = original.source_path, original.page
                    ref.save(update_fields=['source_path', 'page'])
            sub_fs.save()
            image_fs.save()
            Family.link_analog(source, copy, token)
            svc.add_candidate(position, copy)
        state['saved'] = copy.pk
        request.session[key] = state
        messages.success(request, 'Аналог сохранён и добавлен в пул')
        return redirect(back)
    ctx = taxonomy_page_context(taxonomy_state_from_post(request.POST) if posted else task_taxonomy_state(source))
    ctx.update(form=form, formset=source_fs, subitem_formset=sub_fs, image_formset=image_fs,
        task=None, mask_help=HELP, analog_source=source, analog_back=back)
    return render(request, 'problems/task_form.html', ctx)

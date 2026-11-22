"""Сохранённые настройки листка: шапка и префикс имени PDF.

«Свойства листка» (worksheet_form.html): список «Настройки листка»
подставляет сохранённые значения в макет шапки, «Сохранить настройки»
запоминает текущие под именем (то же имя — перезапись). Настройки с
галочкой «для новых листков» сразу заполняют форму нового листка;
?preset=<id> — новый листок по выбранным настройкам.
"""
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required

from .filenames import clean_prefix
from .filenames import prefix_too_long
from .models import WorksheetPreset

NAME_MAX = WorksheetPreset._meta.get_field('name').max_length


def presets_for(user):
    return list(WorksheetPreset.objects.filter(owner=user))


def presets_json(presets):
    """Значения настроек для worksheet_form.js (подстановка без запроса;
    в шаблоне — json_script)."""
    return [{'id': p.pk, 'name': p.name, 'is_default': p.is_default,
             'values': p.values()} for p in presets]


def initial_preset(user, params, presets=None):
    """Настройки для нового листка: ?preset=<id> или «для новых листков»."""
    presets = presets_for(user) if presets is None else presets
    raw = params.get('preset', '')
    if raw.isdigit():
        return next((p for p in presets if p.pk == int(raw)), None)
    return next((p for p in presets if p.is_default), None)


def _field(request, name):
    limit = WorksheetPreset._meta.get_field(name).max_length
    return request.POST.get(name, '').strip()[:limit]


@teacher_required
@require_POST
@transaction.atomic
def preset_save(request):
    name = request.POST.get('name', '').strip()
    if not name:
        return JsonResponse({'ok': False, 'message': 'Назовите настройки'}, status=400)
    if len(name) > NAME_MAX:
        return JsonResponse(
            {'ok': False, 'message': f'Название — не длиннее {NAME_MAX} символов'}, status=400)
    values = {field: _field(request, field)
              for field in WorksheetPreset.FIELDS if field != 'pdf_prefix'}
    # Префикс — по длине после транслита («щ» → sch), а не до него
    values['pdf_prefix'] = clean_prefix(request.POST.get('pdf_prefix', ''))
    prefix_limit = WorksheetPreset._meta.get_field('pdf_prefix').max_length
    if len(values['pdf_prefix']) > prefix_limit:
        return JsonResponse(
            {'ok': False, 'message': prefix_too_long(prefix_limit)}, status=400)
    is_default = request.POST.get('is_default') == '1'
    if is_default:
        # «Для новых листков» — одни настройки
        WorksheetPreset.objects.filter(owner=request.user, is_default=True).update(is_default=False)
    preset, created = WorksheetPreset.objects.update_or_create(
        owner=request.user, name=name, defaults={**values, 'is_default': is_default})
    return JsonResponse({
        'ok': True,
        'message': f'Настройки «{preset.name}» {"сохранены" if created else "обновлены"}',
        'preset': {'id': preset.pk, 'name': preset.name, 'is_default': preset.is_default,
                   'values': preset.values()},
    })


@teacher_required
@require_POST
def preset_delete(request, pk):
    preset = get_object_or_404(WorksheetPreset, pk=pk, owner=request.user)
    name = preset.name
    preset.delete()
    return JsonResponse({'ok': True, 'message': f'Настройки «{name}» удалены'})

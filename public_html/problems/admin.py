from django.contrib import admin
from django import forms

from .forms import clean_mask_text

from .models import (ExamItem, ExamModel, FacetType, FacetValue, GradeBand,
                     Source, Tag, Task, TaskImage, TaskProposal, TaskSource,
                     TaskSubitem, TextbookImportAsset, TextbookImportBatch,
                     TextbookTaskDraft, Topic)


class MaskAdminForm(forms.ModelForm):
    """Админка проверяет эталон так же, как основной редактор задачи."""

    def clean_answer_mask(self):
        return clean_mask_text(self.cleaned_data.get('answer_mask'))


class DraftMaskAdminForm(MaskAdminForm):
    def clean_subitems(self):
        from .textbook_import import normalize_answer_mask, TextbookImportError
        items = self.cleaned_data.get('subitems') or []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise forms.ValidationError('Подпункты должны быть списком объектов.')
        for index, item in enumerate(items, 1):
            try:
                normalize_answer_mask(item.get('answer_mask'), key=f'подпункт {index}')
            except TextbookImportError as error:
                raise forms.ValidationError(str(error)) from error
        return items


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'parent', 'order')
    list_filter = ('parent',)
    search_fields = ('name', 'code')
    ordering = ('order', 'code')


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    search_fields = ('name',)


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'year')
    search_fields = ('title', 'author')


class TaskSourceInline(admin.TabularInline):
    model = TaskSource
    extra = 1
    autocomplete_fields = ('source',)


class TaskSubitemInline(admin.TabularInline):
    model = TaskSubitem
    form = MaskAdminForm
    extra = 0


class TextbookTaskDraftInline(admin.TabularInline):
    model = TextbookTaskDraft
    extra = 0
    fields = ('external_id', 'source_number', 'status', 'confidence')
    readonly_fields = fields
    show_change_link = True


class TaskImageInline(admin.TabularInline):
    model = TaskImage
    extra = 0


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    form = MaskAdminForm
    list_display = ('__str__', 'grade_level', 'stars',
                    'variant_of', 'created_by', 'created_at')
    list_filter = ('grade_level', 'stars',  'grade_bands')
    search_fields = ('text_plain', 'text_latex')
    filter_horizontal = ('grade_bands', 'facet_values', 'exam_items', 'tags')
    inlines = [TaskSubitemInline, TaskImageInline, TaskSourceInline]
    readonly_fields = ('text_plain', 'created_at', 'updated_at')
    autocomplete_fields = ('created_by', 'variant_of')

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        from .rubricator import set_task_exams
        set_task_exams(
            form.instance,
            form.instance.exam_items.values_list('pk', flat=True))


@admin.register(GradeBand)
class GradeBandAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'order')


@admin.register(FacetType)
class FacetTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'selection_mode', 'order')


@admin.register(FacetValue)
class FacetValueAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'facet_type', 'order')
    list_filter = ('facet_type',)
    search_fields = ('code', 'name')


@admin.register(ExamModel)
class ExamModelAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'exam_type', 'exam_year')


@admin.register(ExamItem)
class ExamItemAdmin(admin.ModelAdmin):
    list_display = ('code', 'item_number', 'name', 'exam_model')
    list_filter = ('exam_model',)
    search_fields = ('code', 'name')


@admin.register(TextbookImportBatch)
class TextbookImportBatchAdmin(admin.ModelAdmin):
    list_display = ('title', 'source', 'profile', 'status', 'created_at')
    list_filter = ('status', 'profile')
    inlines = [TextbookTaskDraftInline]


@admin.register(TextbookTaskDraft)
class TextbookTaskDraftAdmin(admin.ModelAdmin):
    form = DraftMaskAdminForm
    list_display = ('external_id', 'batch', 'status', 'confidence', 'topic')
    list_filter = ('status', 'batch')
    search_fields = ('external_id', 'source_number', 'text_latex')


@admin.register(TextbookImportAsset)
class TextbookImportAssetAdmin(admin.ModelAdmin):
    list_display = ('original_name', 'stem', 'batch')
    search_fields = ('original_name', 'stem')


@admin.register(TaskProposal)
class TaskProposalAdmin(admin.ModelAdmin):
    """Очередь предложений: решения принимаются на сайте
    (/problems/proposals/), здесь — просмотр и разбор снимков."""
    list_display = ('__str__', 'kind', 'status', 'author', 'created_at',
                    'resolved_by', 'resolved_at')
    list_filter = ('status', 'kind')
    search_fields = ('message', 'resolution_note', 'author__username',
                     'task__text_plain')
    raw_id_fields = ('task', 'variant', 'author', 'resolved_by')
    readonly_fields = ('snapshot', 'created_at')
    date_hierarchy = 'created_at'

from django.contrib import admin

from .models import (ExamItem, ExamModel, FacetType, FacetValue, GradeBand,
                     Source, Tag, Task, TaskImage, TaskSource, TaskSubitem,
                     TextbookImportAsset, TextbookImportBatch,
                     TextbookTaskDraft, Topic)


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
    list_display = ('__str__', 'grade_level', 'stars', 'answer_type',
                    'variant_of', 'created_by', 'created_at')
    list_filter = ('grade_level', 'stars', 'answer_type', 'grade_bands')
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
    list_display = ('external_id', 'batch', 'status', 'confidence', 'topic')
    list_filter = ('status', 'batch')
    search_fields = ('external_id', 'source_number', 'text_latex')


@admin.register(TextbookImportAsset)
class TextbookImportAssetAdmin(admin.ModelAdmin):
    list_display = ('original_name', 'stem', 'batch')
    search_fields = ('original_name', 'stem')

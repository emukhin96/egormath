from django.contrib import admin

from .models import Source, Tag, Task, TaskSource, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'parent', 'order')
    list_filter = ('parent',)
    search_fields = ('name',)
    ordering = ('parent__name', 'order', 'name')


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


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'grade_level', 'stars', 'answer_type',
                    'created_by', 'created_at')
    list_filter = ('grade_level', 'stars', 'answer_type', 'tags', 'topics')
    search_fields = ('text_plain', 'text_latex')
    filter_horizontal = ('topics', 'tags')
    inlines = [TaskSourceInline]
    readonly_fields = ('text_plain', 'created_at', 'updated_at')
    autocomplete_fields = ('created_by',)

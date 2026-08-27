from django.contrib import admin

from .models import Collection, ShareLink, Worksheet, WorksheetItem, WorksheetPdf


class WorksheetItemInline(admin.TabularInline):
    model = WorksheetItem
    extra = 0
    autocomplete_fields = ('task',)


@admin.register(Worksheet)
class WorksheetAdmin(admin.ModelAdmin):
    list_display = ('title', 'grade_label', 'owner', 'updated_at')
    list_filter = ('owner',)
    search_fields = ('title',)
    inlines = [WorksheetItemInline]


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ('worksheet', 'token', 'is_active', 'created_at')
    list_filter = ('is_active',)


@admin.register(WorksheetPdf)
class WorksheetPdfAdmin(admin.ModelAdmin):
    list_display = ('worksheet', 'variant', 'content_hash', 'created_at')
    list_filter = ('variant',)
    readonly_fields = ('worksheet', 'variant', 'content_hash', 'file', 'created_at')


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'source', 'parent', 'is_published', 'order')
    list_filter = ('is_published', 'source')
    search_fields = ('worksheet__title', 'locator')

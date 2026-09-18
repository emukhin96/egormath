from django.contrib import admin

from .models import CanvasPage


@admin.register(CanvasPage)
class CanvasPageAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'number', 'created_by_role', 'background',
                    'locked_at', 'student_updated_at', 'teacher_updated_at')
    list_filter = ('background', 'created_by_role')
    raw_id_fields = ('submission', 'answer', 'teacher_by')
    readonly_fields = ('student_version', 'teacher_version', 'created_at')

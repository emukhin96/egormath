from django.contrib import admin

from .models import (Assignment, Review, Submission, SubmissionCheckAttempt,
                     SubmissionPart, SubmissionPhoto)


class SubmissionInline(admin.TabularInline):
    model = Submission
    extra = 0
    readonly_fields = ('task', 'answer_text', 'answer_number',
                       'interval_low', 'interval_high', 'updated_at')
    can_delete = False


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('worksheet', 'student', 'status', 'check_visibility',
                    'allow_photos', 'assigned_at', 'due_at')
    list_filter = ('status', 'check_visibility', 'allow_photos')
    search_fields = ('worksheet__title', 'student__username',
                     'student__last_name')
    inlines = [SubmissionInline]


class SubmissionPhotoInline(admin.TabularInline):
    model = SubmissionPhoto
    extra = 0


class SubmissionPartInline(admin.TabularInline):
    model = SubmissionPart
    extra = 0


class SubmissionCheckAttemptInline(admin.TabularInline):
    model = SubmissionCheckAttempt
    extra = 0
    readonly_fields = ('number', 'result', 'snapshot', 'created_at')
    can_delete = False


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('assignment', 'task', 'display_answer', 'updated_at')
    inlines = [SubmissionPartInline, SubmissionPhotoInline,
               SubmissionCheckAttemptInline]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('submission', 'grade', 'reviewer', 'reviewed_at')
    list_filter = ('grade',)

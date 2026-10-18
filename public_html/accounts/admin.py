from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import Profile, StudentGroup


class ProfileInline(admin.StackedInline):
    model = Profile
    fk_name = 'user'
    can_delete = False
    verbose_name_plural = 'Профиль (роль)'


class UserWithProfileAdmin(UserAdmin):
    inlines = [ProfileInline]
    list_display = ('username', 'first_name', 'last_name', 'get_role', 'is_active')
    list_select_related = ('profile',)

    @admin.display(description='Роль')
    def get_role(self, obj):
        try:
            return obj.profile.get_role_display()
        except Profile.DoesNotExist:
            return '—'


admin.site.unregister(User)
admin.site.register(User, UserWithProfileAdmin)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'grade', 'teacher', 'base_editor')
    list_filter = ('role', 'grade', 'base_editor')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    autocomplete_fields = ('user', 'teacher')


@admin.register(StudentGroup)
class StudentGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'teacher')
    list_filter = ('teacher',)
    search_fields = ('name',)
    filter_horizontal = ('students',)

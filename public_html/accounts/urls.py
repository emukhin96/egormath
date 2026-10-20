from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(
        template_name='accounts/login.html',
        redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('join/<str:token>/', views.teacher_join, name='teacher_join'),
    path('profile/', views.profile, name='profile'),
    path('profile/task-list/', views.task_list_prefs, name='task_list_prefs'),
    path('teachers/', views.teachers, name='teachers'),
    path('teachers/<int:user_id>/reset-password/',
         views.teacher_reset_password, name='teacher_reset_password'),
    path('teachers/<int:user_id>/active/',
         views.teacher_toggle_active, name='teacher_toggle_active'),
    path('teachers/<int:user_id>/base-editor/',
         views.teacher_toggle_base_editor, name='teacher_toggle_base_editor'),
    path('teachers/invites/<int:invite_id>/revoke/',
         views.invite_revoke, name='invite_revoke'),
    path('students/', views.students, name='students'),
    path('students/bulk-groups/', views.students_bulk_groups,
         name='students_bulk_groups'),
    path('students/<int:user_id>/edit/', views.student_edit,
         name='student_edit'),
    path('students/<int:user_id>/reset-password/',
         views.reset_student_password, name='reset_student_password'),
    path('groups/<int:group_id>/delete/', views.group_delete,
         name='group_delete'),
    path('groups/<int:group_id>/rename/', views.group_rename,
         name='group_rename'),
]

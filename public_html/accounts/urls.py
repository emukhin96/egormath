from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(
        template_name='accounts/login.html',
        redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('students/', views.students, name='students'),
    path('students/<int:user_id>/edit/', views.student_edit,
         name='student_edit'),
    path('students/<int:user_id>/reset-password/',
         views.reset_student_password, name='reset_student_password'),
    path('groups/<int:group_id>/delete/', views.group_delete,
         name='group_delete'),
    path('groups/<int:group_id>/rename/', views.group_rename,
         name='group_rename'),
]

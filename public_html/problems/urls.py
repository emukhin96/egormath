from django.urls import path

from . import views

urlpatterns = [
    path('', views.task_list, name='task_list'),
    path('new/', views.task_create, name='task_create'),
    path('bulk-answers/', views.bulk_answers, name='bulk_answers'),
    path('bulk-update/', views.task_bulk_update, name='task_bulk_update'),
    path('<int:pk>/', views.task_detail, name='task_detail'),
    path('<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('<int:pk>/quick/', views.task_quick_update,
         name='task_quick_update'),
    path('images/<int:pk>/file/', views.task_image_file,
         name='task_image_file'),
]

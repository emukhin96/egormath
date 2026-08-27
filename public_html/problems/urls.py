from django.urls import path

from . import views

urlpatterns = [
    path('', views.task_list, name='task_list'),
    path('new/', views.task_create, name='task_create'),
    path('bulk-answers/', views.bulk_answers, name='bulk_answers'),
    path('bulk-update/', views.task_bulk_update, name='task_bulk_update'),
    path('solve/', views.task_neuro_solve, name='task_neuro_solve'),
    path('imports/', views.textbook_import_list,
         name='textbook_import_list'),
    path('imports/new/', views.textbook_import_upload,
         name='textbook_import_upload'),
    path('imports/<int:pk>/', views.textbook_import_detail,
         name='textbook_import_detail'),
    path('imports/<int:pk>/approve-clean/',
         views.textbook_import_approve_clean,
         name='textbook_import_approve_clean'),
    path('imports/<int:pk>/commit/', views.textbook_import_commit,
         name='textbook_import_commit'),
    path('imports/<int:batch_pk>/tasks/<int:pk>/',
         views.textbook_import_review, name='textbook_import_review'),
    path('<int:pk>/', views.task_detail, name='task_detail'),
    path('<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('<int:pk>/quick/', views.task_quick_update,
         name='task_quick_update'),
    path('<int:pk>/subitems/add/', views.task_subitem_add,
         name='task_subitem_add'),
    path('<int:pk>/subitems/<int:spk>/', views.task_subitem_update,
         name='task_subitem_update'),
    path('images/<int:pk>/file/', views.task_image_file,
         name='task_image_file'),
]

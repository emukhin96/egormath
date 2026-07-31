from django.urls import path

from . import views

urlpatterns = [
    path('', views.worksheet_list, name='worksheet_list'),
    path('new/', views.worksheet_create, name='worksheet_create'),
    path('<int:pk>/', views.worksheet_detail, name='worksheet_detail'),
    path('<int:pk>/edit/', views.worksheet_edit, name='worksheet_edit'),
    path('<int:pk>/pdf/', views.worksheet_pdf, name='worksheet_pdf'),
    path('<int:pk>/tex/', views.worksheet_tex, name='worksheet_tex'),
    path('<int:pk>/add-task/', views.worksheet_add_task,
         name='worksheet_add_task'),
    path('<int:pk>/items/<int:item_id>/remove/', views.worksheet_remove_item,
         name='worksheet_remove_item'),
    path('<int:pk>/items/<int:item_id>/move/<str:direction>/',
         views.worksheet_move_item, name='worksheet_move_item'),
    path('<int:pk>/items/<int:item_id>/rubric/', views.worksheet_set_rubric,
         name='worksheet_set_rubric'),
    path('<int:pk>/share/', views.share_create, name='share_create'),
    path('<int:pk>/share/<int:link_id>/toggle/', views.share_toggle,
         name='share_toggle'),
]

from django.urls import path

from . import views

urlpatterns = [
    path('assign/<int:worksheet_id>/', views.assign_worksheet,
         name='assign_worksheet'),
    path('<int:pk>/', views.assignment_detail, name='assignment_detail'),
    path('<int:pk>/answers/', views.save_answers, name='save_answers'),
    path('<int:pk>/check/<int:task_id>/', views.check_task, name='check_task'),
    path('<int:pk>/photos/<int:task_id>/', views.upload_photo,
         name='upload_photo'),
    path('<int:pk>/photos/<int:photo_id>/delete/', views.delete_photo,
         name='delete_photo'),
    path('<int:pk>/submit/', views.submit_assignment,
         name='submit_assignment'),
    path('<int:pk>/review/', views.review_assignment,
         name='review_assignment'),
    path('<int:pk>/review/save/', views.save_review, name='save_review'),
    path('photo/<int:photo_id>/', views.photo_file, name='photo_file'),
]

from django.urls import path

from . import views

app_name = 'canvas'

# Подключается как assignments/<pk>/canvas/<task_id>/ (core/urls.py)
urlpatterns = [
    path('', views.pages, name='pages'),
    path('<int:number>/', views.save_page, name='save'),
    path('<int:number>/delete/', views.delete_page, name='delete'),
]

from django.urls import path
from . import views

app_name = 'workaudit'
urlpatterns = [
    path('<str:kind>/<int:pk>/events/', views.events, name='events'),
    path('<str:kind>/<int:pk>/activity/', views.activity, name='activity'),
    path('history/<str:kind>/<int:pk>/', views.history, name='history'),
    path('run/<int:pk>/settings/', views.run_settings, name='run_settings'),
]

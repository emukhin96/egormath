from django.contrib import admin
from django.urls import include, path

from accounts import views as accounts_views
from worksheets import views as worksheets_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', accounts_views.index, name='index'),
    path('dashboard/', accounts_views.dashboard, name='dashboard'),
    path('accounts/', include('accounts.urls')),
    path('problems/', include('problems.urls')),
    path('worksheets/', include('worksheets.urls')),
    path('assignments/', include('assignments.urls')),
    path('s/<str:token>/', worksheets_views.public_worksheet, name='public_worksheet'),
    path('s/<str:token>/pdf/', worksheets_views.public_worksheet_pdf, name='public_worksheet_pdf'),
]

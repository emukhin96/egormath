from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import include, path
from django.views.generic.base import RedirectView

from accounts import views as accounts_views
from core import views as core_views
from livefile import views as livefile_views
from worksheets import views as worksheets_views


class FaviconRedirectView(RedirectView):
    """Синий значок на проде, зелёный на локальной машине (DEBUG)."""

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        name = 'favicon-local.ico' if settings.DEBUG else 'favicon.ico'
        return staticfiles_storage.url(name)


urlpatterns = [
    path('favicon.ico', FaviconRedirectView.as_view(), name='favicon'),
    path('healthz', core_views.healthz, name='healthz'),
    path('robots.txt', core_views.robots_txt, name='robots_txt'),
    path('admin/', admin.site.urls),
    path('', accounts_views.index, name='index'),
    path('dashboard/', accounts_views.dashboard, name='dashboard'),
    path('accounts/', include('accounts.urls')),
    path('problems/', include('problems.urls')),
    path('worksheets/cart/', include('worksheets.cart_urls')),
    path('worksheets/', include('worksheets.urls')),
    path('assignments/', include('assignments.urls')),
    path('assignments/<int:pk>/canvas/<int:task_id>/', include('canvas.urls')),
    path('work-activity/', include('workaudit.urls')),
    path('independent-works/', include('independentworks.urls')),
    path('s/<str:token>/', worksheets_views.public_worksheet, name='public_worksheet'),
    path('s/<str:token>/pdf/', worksheets_views.public_worksheet_pdf, name='public_worksheet_pdf'),
    # Файлы-версии живых страниц: на проде отдаёт Apache, это — для runserver.
    path('live/<str:token>.txt', livefile_views.serve, name='live_file'),
]

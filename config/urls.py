from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("management/dashboard/", include("apps.dashboard.urls")),
    path("management/scheduling/", include("apps.scheduling.urls")),
    path("management/inspections/", include("apps.inspections.urls")),
    path("management/reports/", include("apps.reports.urls")),
    path("management/", include("apps.accounts.urls")),
    path("progress/", include("apps.progress.urls")),
    path("", include("apps.housing.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

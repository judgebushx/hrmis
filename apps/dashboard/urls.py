from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.programme_dashboard, name="programme-dashboard"),
    path("export/", views.programme_export, name="programme-export"),
]

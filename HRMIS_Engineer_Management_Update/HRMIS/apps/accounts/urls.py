from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("engineers/", views.engineer_list, name="engineer-list"),
    path("engineers/new/", views.engineer_create, name="engineer-create"),
    path("engineers/assign-houses/", views.bulk_assign_houses, name="house-assign"),
    path("engineers/<int:pk>/", views.engineer_detail, name="engineer-detail"),
    path("engineers/<int:pk>/edit/", views.engineer_update, name="engineer-update"),
    path("engineers/<int:pk>/reset-password/", views.engineer_password_reset, name="engineer-password-reset"),
]

from django.urls import path
from . import views

app_name = "housing"
urlpatterns = [
    path("", views.house_list, name="house-list"),
    path("houses/new/", views.house_create, name="house-create"),
    path("houses/import/", views.import_houses, name="house-import"),
    path("houses/import-template/", views.download_import_template, name="house-import-template"),
    path("houses/<int:pk>/", views.house_detail, name="house-detail"),
    path("houses/<int:pk>/edit/", views.house_update, name="house-update"),
    path("houses/<int:pk>/delete/", views.house_delete, name="house-delete"),
]

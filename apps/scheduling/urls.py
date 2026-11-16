from django.urls import path
from . import views

app_name = "scheduling"
urlpatterns = [
    path("", views.programme_schedule, name="programme-schedule"),
    path("bulk/", views.bulk_schedule, name="bulk-schedule"),
    path("gantt/", views.programme_gantt, name="programme-gantt"),
    path("houses/<int:house_pk>/", views.house_schedule_edit, name="house-schedule-edit"),
]

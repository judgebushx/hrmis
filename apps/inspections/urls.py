from django.urls import path
from . import views
app_name = "inspections"
urlpatterns = [
    path("", views.inspection_list, name="inspection-list"),
    path("my-defects/", views.my_assigned_defects, name="my-assigned-defects"),
    path("defects/<int:pk>/work/", views.defect_work_update, name="defect-work-update"),
    path("houses/<int:house_pk>/new/", views.inspection_create, name="inspection-create"),
    path("<int:pk>/", views.inspection_detail, name="inspection-detail"),
    path("<int:pk>/review/", views.inspection_review, name="inspection-review"),
    path("defects/<int:pk>/update/", views.defect_update, name="defect-update"),
]

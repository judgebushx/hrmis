from django.urls import path
from . import views

app_name = "progress"
urlpatterns = [
    path("houses/<int:house_pk>/", views.house_progress, name="house-progress"),
    path("reviews/", views.progress_review_list, name="progress-review-list"),
    path("reviews/<int:record_pk>/", views.progress_review, name="progress-review"),
]

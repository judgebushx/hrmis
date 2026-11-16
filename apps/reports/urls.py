from django.urls import path
from . import views

app_name = 'reports'
urlpatterns = [
    path('', views.report_centre, name='centre'),
    path('pdf/', views.report_pdf, name='pdf'),
]

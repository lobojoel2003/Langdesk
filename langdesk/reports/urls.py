from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.report, name="report"),
    path("summary.csv", views.summary_export, name="summary_csv"),
    path("log.csv", views.log_export, name="log_csv"),
]

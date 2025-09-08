from django.urls import path
from .views import (
    TimeSeriesView,
    TemplatesUsageView,
    DataQualityView,
    ExportPetitionsCSVView,
)

urlpatterns = [
    path("timeseries/", TimeSeriesView.as_view(), name="reports-timeseries"),
    path("templates-usage/", TemplatesUsageView.as_view(), name="reports-templates-usage"),
    path("data-quality/", DataQualityView.as_view(), name="reports-data-quality"),
    path("export/petitions/", ExportPetitionsCSVView.as_view(), name="reports-export-petitions"),
]

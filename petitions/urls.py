from django.urls import path
from .views import GeneratePetition
urlpatterns = [ path("generate/", GeneratePetition.as_view()) ]

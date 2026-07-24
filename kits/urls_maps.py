"""Rotas do proxy Google Places (montadas em /api/maps/)."""
from django.urls import path

from .views_maps import PlaceDetailsView, PlacesAutocompleteView

urlpatterns = [
    path("places/autocomplete/", PlacesAutocompleteView.as_view(), name="maps-places-autocomplete"),
    path("places/details/", PlaceDetailsView.as_view(), name="maps-places-details"),
]

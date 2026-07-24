"""Endpoints de proxy da Google Places API (autocomplete de endereço)."""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .services_maps import (
    MapsConfigError,
    MapsUpstreamError,
    autocomplete,
    place_details,
)


class PlacesAutocompleteView(APIView):
    """GET /api/maps/places/autocomplete/?input=...&sessiontoken=...

    Retorna sugestões de endereço: [{ description, place_id }].
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        entrada = request.query_params.get("input", "")
        token = request.query_params.get("sessiontoken", "")
        try:
            predictions = autocomplete(entrada, token)
        except MapsConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except MapsUpstreamError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"predictions": predictions})


class PlaceDetailsView(APIView):
    """GET /api/maps/places/details/?place_id=...&sessiontoken=...

    Retorna endereço quebrado em campos + latitude/longitude.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        place_id = request.query_params.get("place_id", "")
        token = request.query_params.get("sessiontoken", "")
        if not place_id:
            return Response(
                {"detail": "Parâmetro 'place_id' é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            detalhes = place_details(place_id, token)
        except MapsConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except MapsUpstreamError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(detalhes)

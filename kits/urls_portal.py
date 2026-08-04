"""Rota pública do portal de assinatura (link único entregue ao cliente)."""
from django.urls import path

from .views_portal import AssinaturaPortalView

urlpatterns = [
    path(
        "assinar/<uuid:token>/",
        AssinaturaPortalView.as_view(),
        name="assinatura-portal",
    ),
]

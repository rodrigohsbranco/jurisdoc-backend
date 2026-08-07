"""Rotas do app FlowALR relacionadas a contas (SSO de colaboradores)."""
from django.urls import path

from .views_app import ValidarCredenciaisAppView

urlpatterns = [
    path(
        "auth/validar-credenciais/",
        ValidarCredenciaisAppView.as_view(),
        name="app-validar-credenciais",
    ),
]

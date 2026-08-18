"""Rotas da área "Sou cliente" do app FlowALR."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views_cliente_app import (
    AlterarSenhaClienteView,
    LoginClienteView,
    MeusDadosClienteViewSet,
    RegistrarClienteView,
)

router = DefaultRouter()
router.register(r"meus-dados", MeusDadosClienteViewSet, basename="cliente-app-meus-dados")

urlpatterns = [
    path("registrar/", RegistrarClienteView.as_view(), name="cliente-app-registrar"),
    path("login/", LoginClienteView.as_view(), name="cliente-app-login"),
    path("alterar-senha/", AlterarSenhaClienteView.as_view(), name="cliente-app-alterar-senha"),
    path("", include(router.urls)),
]

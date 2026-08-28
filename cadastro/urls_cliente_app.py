"""Rotas da área "Sou cliente" do app FlowALR.

Entrada principal: código por WhatsApp (`whatsapp/`).
`login/` e `alterar-senha/` são o acesso alternativo, para quando o WhatsApp falha.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views_cliente_app import (
    AlterarSenhaClienteView,
    LoginClienteView,
    MeusDadosClienteViewSet,
)
from .views_cliente_whatsapp import (
    DiagnosticoWhatsAppView,
    SolicitarCodigoView,
    ValidarCodigoView,
)

router = DefaultRouter()
router.register(r"meus-dados", MeusDadosClienteViewSet, basename="cliente-app-meus-dados")

urlpatterns = [
    # Entrada por WhatsApp
    path(
        "whatsapp/solicitar-codigo/",
        SolicitarCodigoView.as_view(),
        name="cliente-app-solicitar-codigo",
    ),
    path(
        "whatsapp/validar-codigo/",
        ValidarCodigoView.as_view(),
        name="cliente-app-validar-codigo",
    ),
    path(
        "whatsapp/diagnostico/",
        DiagnosticoWhatsAppView.as_view(),
        name="cliente-app-whatsapp-diagnostico",
    ),
    # Acesso alternativo
    path("login/", LoginClienteView.as_view(), name="cliente-app-login"),
    path("alterar-senha/", AlterarSenhaClienteView.as_view(), name="cliente-app-alterar-senha"),
    path("", include(router.urls)),
]

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    AcaoKitViewSet,
    ClausulaPorcentagemPadraoView,
    ClausulaPorcentagemUFViewSet,
    KitViewSet,
)

router = DefaultRouter()
# Cláusula de porcentagem (admin-only) — registrado ANTES do KitViewSet (que
# usa prefix vazio "") para que as rotas não sejam capturadas pelo viewset
# genérico de kits.
router.register(
    r"clausula-porcentagem/ufs",
    ClausulaPorcentagemUFViewSet,
    basename="clausula-porcentagem-uf",
)
router.register(r"", KitViewSet, basename="kit")

urlpatterns = [
    path(
        "clausula-porcentagem/padrao/",
        ClausulaPorcentagemPadraoView.as_view(),
        name="clausula-porcentagem-padrao",
    ),
    path("", include(router.urls)),
    path(
        "<int:kit_pk>/acoes/",
        AcaoKitViewSet.as_view({"get": "list", "post": "create"}),
        name="kit-acoes-list",
    ),
    path(
        "<int:kit_pk>/acoes/<int:pk>/",
        AcaoKitViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="kit-acoes-detail",
    ),
    path(
        "<int:kit_pk>/acoes/<int:pk>/anexos/upload/",
        AcaoKitViewSet.as_view({"post": "upload_attachments"}),
        name="kit-acoes-anexos-upload",
    ),
    path(
        "<int:kit_pk>/acoes/<int:pk>/anexos/remove/",
        AcaoKitViewSet.as_view({"post": "remove_attachment"}),
        name="kit-acoes-anexos-remove",
    ),
]

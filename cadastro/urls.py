from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ClienteViewSet,
    ContaBancariaViewSet,
    DescricaoBancoViewSet,
    RepresentanteViewSet,
)

router = DefaultRouter()
router.register(r"clientes", ClienteViewSet, basename="cliente")
router.register(r"contas", ContaBancariaViewSet, basename="conta")
router.register(r"bancos-descricoes", DescricaoBancoViewSet, basename="banco-descricao")
router.register(r"representantes", RepresentanteViewSet, basename="representante")

urlpatterns = [
    path("", include(router.urls)),
]

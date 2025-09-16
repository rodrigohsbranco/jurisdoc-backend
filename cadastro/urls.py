from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import ClienteViewSet, ContaBancariaViewSet, DescricaoBancoViewSet

router = DefaultRouter()
router.register("clientes", ClienteViewSet, basename="cliente")
router.register("contas", ContaBancariaViewSet, basename="conta")
router.register("bancos-descricoes", DescricaoBancoViewSet, basename="banco-descricao")

urlpatterns = [path("", include(router.urls))]

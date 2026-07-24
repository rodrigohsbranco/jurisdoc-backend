from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CapacidadesDiretasView, CapacidadeViewSet, PermissaoViewSet

router = DefaultRouter()
router.register("capacidades", CapacidadeViewSet, basename="capacidade")
router.register("permissoes", PermissaoViewSet, basename="permissao")

urlpatterns = router.urls + [
    path("capacidades-diretas/", CapacidadesDiretasView.as_view(), name="capacidades-diretas"),
]

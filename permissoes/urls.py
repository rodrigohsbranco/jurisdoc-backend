from rest_framework.routers import DefaultRouter

from .views import CapacidadeViewSet, PermissaoViewSet

router = DefaultRouter()
router.register("capacidades", CapacidadeViewSet, basename="capacidade")
router.register("permissoes", PermissaoViewSet, basename="permissao")

urlpatterns = router.urls

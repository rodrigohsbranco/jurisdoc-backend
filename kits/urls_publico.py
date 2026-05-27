from rest_framework.routers import DefaultRouter

from .views_publico import AssociacaoKitPublicoViewSet, BancoKitPublicoViewSet, TarifaKitPublicoViewSet

router = DefaultRouter()
router.register(r"bancos", BancoKitPublicoViewSet, basename="catalogo-banco")
router.register(r"tarifas", TarifaKitPublicoViewSet, basename="catalogo-tarifa")
router.register(r"associacoes", AssociacaoKitPublicoViewSet, basename="catalogo-associacao")

urlpatterns = router.urls

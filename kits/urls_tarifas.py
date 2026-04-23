from rest_framework.routers import DefaultRouter

from .views import TarifaKitViewSet

router = DefaultRouter()
router.register(r"", TarifaKitViewSet, basename="tarifa-kit")

urlpatterns = router.urls

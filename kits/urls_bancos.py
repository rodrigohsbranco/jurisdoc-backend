from rest_framework.routers import DefaultRouter

from .views import BancoKitViewSet

router = DefaultRouter()
router.register(r"", BancoKitViewSet, basename="banco-kit")

urlpatterns = router.urls

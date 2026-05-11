from rest_framework.routers import DefaultRouter

from .views import AssociacaoKitViewSet

router = DefaultRouter()
router.register(r"", AssociacaoKitViewSet, basename="associacao-kit")

urlpatterns = router.urls

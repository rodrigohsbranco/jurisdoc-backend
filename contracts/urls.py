from rest_framework.routers import DefaultRouter
from .views import ContratoViewSet

router = DefaultRouter()
router.register(r"contracts", ContratoViewSet, basename="contracts")

urlpatterns = router.urls

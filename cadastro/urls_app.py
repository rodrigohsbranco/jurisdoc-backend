from rest_framework.routers import DefaultRouter

from .views_app import ClienteAppViewSet

router = DefaultRouter()
router.register(r"clientes", ClienteAppViewSet, basename="app-cliente")

urlpatterns = router.urls

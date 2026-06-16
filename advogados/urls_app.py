from rest_framework.routers import DefaultRouter

from .views_app import AdvogadoAppViewSet

router = DefaultRouter()
router.register(r"advogados", AdvogadoAppViewSet, basename="app-advogado")

urlpatterns = router.urls

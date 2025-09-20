from rest_framework.routers import DefaultRouter
from .views import TemplateViewSet
router = DefaultRouter()
router.register(r"", TemplateViewSet, basename="templates")
urlpatterns = router.urls

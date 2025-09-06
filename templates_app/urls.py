from rest_framework.routers import DefaultRouter
from .views import TemplateViewSet
router = DefaultRouter()
router.register("", TemplateViewSet, basename="template")
urlpatterns = router.urls

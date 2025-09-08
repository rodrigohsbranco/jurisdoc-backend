# petitions/urls.py
from rest_framework.routers import DefaultRouter
from .views import PetitionViewSet

router = DefaultRouter()
router.register(r"", PetitionViewSet, basename="petitions")  # <- raiz

urlpatterns = router.urls

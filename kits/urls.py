from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import AcaoKitViewSet, KitViewSet

router = DefaultRouter()
router.register(r"", KitViewSet, basename="kit")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "<int:kit_pk>/acoes/",
        AcaoKitViewSet.as_view({"get": "list", "post": "create"}),
        name="kit-acoes-list",
    ),
    path(
        "<int:kit_pk>/acoes/<int:pk>/",
        AcaoKitViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="kit-acoes-detail",
    ),
]

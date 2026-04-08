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
    path(
        "<int:kit_pk>/acoes/<int:pk>/anexos/upload/",
        AcaoKitViewSet.as_view({"post": "upload_attachments"}),
        name="kit-acoes-anexos-upload",
    ),
    path(
        "<int:kit_pk>/acoes/<int:pk>/anexos/remove/",
        AcaoKitViewSet.as_view({"post": "remove_attachment"}),
        name="kit-acoes-anexos-remove",
    ),
]

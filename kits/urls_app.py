from django.urls import path
from rest_framework.routers import DefaultRouter

from .views_app import AcaoKitAppViewSet, KitAppViewSet

router = DefaultRouter()
router.register(r"kits", KitAppViewSet, basename="app-kit")

urlpatterns = router.urls + [
    path(
        "kits/<int:kit_pk>/acoes/",
        AcaoKitAppViewSet.as_view({"get": "list", "post": "create"}),
        name="app-kit-acoes-list",
    ),
    path(
        "kits/<int:kit_pk>/acoes/<int:pk>/",
        AcaoKitAppViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="app-kit-acoes-detail",
    ),
    path(
        "kits/<int:kit_pk>/acoes/<int:pk>/anexos/upload/",
        AcaoKitAppViewSet.as_view({"post": "upload_attachments"}),
        name="app-kit-acoes-anexos-upload",
    ),
    path(
        "kits/<int:kit_pk>/acoes/<int:pk>/anexos/remove/",
        AcaoKitAppViewSet.as_view({"post": "remove_attachment"}),
        name="app-kit-acoes-anexos-remove",
    ),
]

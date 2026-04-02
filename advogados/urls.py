from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import AdvogadoViewSet, OabUfViewSet

router = DefaultRouter()
router.register(r"", AdvogadoViewSet, basename="advogado")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "<int:advogado_pk>/oabs/",
        OabUfViewSet.as_view({"get": "list", "post": "create"}),
        name="advogado-oabs-list",
    ),
    path(
        "<int:advogado_pk>/oabs/<int:pk>/",
        OabUfViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="advogado-oabs-detail",
    ),
]

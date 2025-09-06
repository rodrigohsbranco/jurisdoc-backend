from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import ClienteViewSet, ContaBancariaViewSet

router = DefaultRouter()
router.register("clientes", ClienteViewSet, basename="cliente")
router.register("contas", ContaBancariaViewSet, basename="conta")

urlpatterns = [ path("", include(router.urls)) ]

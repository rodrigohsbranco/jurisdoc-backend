from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

from accounts.service_auth import IsServiceClient, ServiceClientAuthentication
from .models import AssociacaoKit, BancoKit, TarifaKit
from .serializers import AssociacaoKitSerializer, BancoKitSerializer, TarifaKitSerializer


class _CatalogoBaseViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Base para endpoints de catálogo acessíveis apenas via Client Credentials.
    Usuários humanos não têm acesso — somente backends autenticados como AppClient.
    """

    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceClient]
    pagination_class = None


class BancoKitPublicoViewSet(_CatalogoBaseViewSet):
    """
    Lista e detalha bancos cadastrados no sistema (somente leitura, Client Credentials).
    Retorna apenas registros ativos, ordenados por ordem e nome.
    """

    serializer_class = BancoKitSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["ativo"]
    search_fields = ["nome"]
    ordering_fields = ["nome", "ordem"]
    ordering = ["ordem", "nome"]

    def get_queryset(self):
        return BancoKit.objects.filter(ativo=True).order_by("ordem", "nome")


class TarifaKitPublicoViewSet(_CatalogoBaseViewSet):
    """
    Lista e detalha tarifas cadastradas no sistema (somente leitura, Client Credentials).
    Retorna apenas registros ativos, ordenados por ordem e nome.
    """

    serializer_class = TarifaKitSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["ativo"]
    search_fields = ["nome"]
    ordering_fields = ["nome", "ordem"]
    ordering = ["ordem", "nome"]

    def get_queryset(self):
        return TarifaKit.objects.filter(ativo=True).order_by("ordem", "nome")


class AssociacaoKitPublicoViewSet(_CatalogoBaseViewSet):
    """
    Lista e detalha associações cadastradas no sistema (somente leitura, Client Credentials).
    Retorna apenas registros ativos, ordenados por ordem e nome.
    """

    serializer_class = AssociacaoKitSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["ativo"]
    search_fields = ["nome", "abreviacao"]
    ordering_fields = ["nome", "abreviacao", "ordem"]
    ordering = ["ordem", "nome"]

    def get_queryset(self):
        return AssociacaoKit.objects.filter(ativo=True).order_by("ordem", "nome")

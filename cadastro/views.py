# cadastro/views.py
from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Cliente, ContaBancaria
from .filters import ClienteFilter, ContaBancariaFilter

# Se quiser manter a classe abaixo para uso futuro, tudo bem,
# mas não vamos usá-la nos ViewSets do cadastro agora.
class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and getattr(request.user, "is_admin", False))

class ClienteViewSet(viewsets.ModelViewSet):
    queryset = Cliente.objects.all().order_by("nome_completo")
    permission_classes = [permissions.IsAuthenticated]  # << AQUI
    serializer_class = None  # setado no get_serializer_class
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ClienteFilter
    search_fields = ["nome_completo", "cpf", "cidade", "bairro"]
    ordering_fields = ["nome_completo", "criado_em", "atualizado_em"]

    def get_serializer_class(self):
        from .serializers import ClienteSerializer
        return ClienteSerializer

class ContaBancariaViewSet(viewsets.ModelViewSet):
    queryset = (
        ContaBancaria.objects.select_related("cliente")
        .all()
        .order_by("cliente__nome_completo", "banco_nome")
    )
    permission_classes = [permissions.IsAuthenticated]  # << E AQUI
    serializer_class = None
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ContaBancariaFilter
    filterset_fields = ["cliente", "banco_nome", "tipo", "is_principal"]
    search_fields = ["banco_nome", "agencia", "conta", "cliente__nome_completo"]
    ordering_fields = ["banco_nome", "agencia", "conta", "criado_em", "is_principal"]

    def get_serializer_class(self):
        from .serializers import ContaBancariaSerializer
        return ContaBancariaSerializer

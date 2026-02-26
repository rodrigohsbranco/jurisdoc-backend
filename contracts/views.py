from rest_framework import viewsets, filters, permissions
from django_filters.rest_framework import DjangoFilterBackend

from .models import Contrato
from .serializers import ContratoSerializer


class ContratoViewSet(viewsets.ModelViewSet):
    """
    API de contratos vinculados a clientes.
    Permite criar, listar, editar e excluir contratos.
    """

    queryset = Contrato.objects.select_related("cliente", "criado_por").all()
    serializer_class = ContratoSerializer
    permission_classes = [permissions.IsAuthenticated]

    # Filtros e ordenação
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["cliente", "situacao", "origem_averbacao"]
    search_fields = ["numero_contrato", "banco_nome"]
    ordering_fields = [
        "data_inclusao",
        "data_inicio_desconto",
        "data_fim_desconto",
        "valor_parcela",
        "valor_emprestado",
        "valor_liberado",
        "criado_em",
    ]
    ordering = ["-criado_em"]

    def perform_create(self, serializer):
        # Garante que o usuário autenticado será vinculado automaticamente
        serializer.save(criado_por=self.request.user)

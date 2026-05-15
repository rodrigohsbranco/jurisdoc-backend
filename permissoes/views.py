from django.db.models import Count
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Capacidade, Permissao
from .permissions import HasCapability
from .serializers import CapacidadeSerializer, PermissaoSerializer


class CapacidadeViewSet(viewsets.ReadOnlyModelViewSet):
    """Catálogo de capacidades — somente leitura."""
    queryset = Capacidade.objects.all()
    serializer_class = CapacidadeSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["codigo", "recurso", "acao", "descricao"]
    ordering_fields = ["categoria", "recurso", "acao", "codigo"]
    pagination_class = None  # catálogo pequeno; devolve tudo

    def get_permissions(self):
        return [HasCapability.for_action(self.action, {
            "list": "permissoes.visualizar",
            "retrieve": "permissoes.visualizar",
            "agrupadas": "permissoes.visualizar",
        })]

    @action(detail=False, methods=["get"], url_path="agrupadas")
    def agrupadas(self, request):
        """Devolve capacidades organizadas para a matriz da UI:
        [{categoria, recursos: [{recurso, acoes: [{codigo, acao, descricao, id}]}]}]
        """
        data: dict = {}
        for cap in self.get_queryset():
            cat = data.setdefault(cap.categoria, {})
            rec = cat.setdefault(cap.recurso, [])
            rec.append({
                "id": cap.id,
                "codigo": cap.codigo,
                "acao": cap.acao,
                "descricao": cap.descricao,
            })
        agrupado = [
            {
                "categoria": categoria,
                "recursos": [
                    {"recurso": recurso, "acoes": acoes}
                    for recurso, acoes in recursos.items()
                ],
            }
            for categoria, recursos in data.items()
        ]
        return Response(agrupado)


class PermissaoViewSet(viewsets.ModelViewSet):
    """CRUD de Permissões (perfis nomeados)."""
    serializer_class = PermissaoSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nome", "descricao"]
    ordering_fields = ["nome", "criado_em", "atualizado_em"]

    def get_queryset(self):
        return (
            Permissao.objects
            .annotate(usuarios_count=Count("usuarios", distinct=True))
            .prefetch_related("capacidades")
        )

    def get_permissions(self):
        return [HasCapability.for_action(self.action, {
            "list": "permissoes.visualizar",
            "retrieve": "permissoes.visualizar",
            "create": "permissoes.criar",
            "update": "permissoes.editar",
            "partial_update": "permissoes.editar",
            "destroy": "permissoes.deletar",
        })]

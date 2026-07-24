from django.contrib.auth import get_user_model
from django.db.models import Count
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Capacidade, Permissao
from .permissions import CAPACIDADES_SEM_BYPASS_ADMIN, HasCapability
from .serializers import CapacidadeSerializer, PermissaoSerializer

User = get_user_model()


class CapacidadeViewSet(viewsets.ReadOnlyModelViewSet):
    """Catálogo de capacidades para montar PERFIS — somente leitura.

    Capacidades sensíveis (CAPACIDADES_SEM_BYPASS_ADMIN) são omitidas: elas não
    entram em perfis, são atribuídas por usuário (CapacidadesDiretasView).
    """
    serializer_class = CapacidadeSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["codigo", "recurso", "acao", "descricao"]
    ordering_fields = ["categoria", "recurso", "acao", "codigo"]
    pagination_class = None  # catálogo pequeno; devolve tudo

    def get_queryset(self):
        return Capacidade.objects.exclude(codigo__in=CAPACIDADES_SEM_BYPASS_ADMIN)

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


class CapacidadesDiretasView(APIView):
    """Atribuição DIRETA de capacidades sensíveis a usuários específicos.

    Capacidades sensíveis (CAPACIDADES_SEM_BYPASS_ADMIN) não são herdadas por
    admin e podem ser concedidas por usuário, fora de qualquer perfil.

    GET  → lista cada capacidade sensível com todos os usuários ativos e se cada
           um tem a concessão direta.
    POST → concede/revoga: body {codigo, user_id, concedida}.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasCapability("permissoes.editar")]
        return [HasCapability("permissoes.visualizar")]

    def _caps_sensiveis(self):
        return (
            Capacidade.objects
            .filter(codigo__in=CAPACIDADES_SEM_BYPASS_ADMIN)
            .prefetch_related("usuarios_diretos")
            .order_by("categoria", "recurso", "acao")
        )

    def get(self, request):
        usuarios = list(
            User.objects.filter(is_active=True).order_by("nome_completo", "username")
        )
        data = []
        for cap in self._caps_sensiveis():
            com_acesso = set(cap.usuarios_diretos.values_list("id", flat=True))
            data.append({
                "codigo": cap.codigo,
                "recurso": cap.recurso,
                "acao": cap.acao,
                "descricao": cap.descricao,
                "usuarios": [
                    {
                        "id": u.id,
                        "username": u.username,
                        "nome": u.nome_completo or u.username,
                        "is_admin": u.is_admin,
                        "concedida": u.id in com_acesso,
                    }
                    for u in usuarios
                ],
            })
        return Response(data)

    def post(self, request):
        codigo = request.data.get("codigo")
        user_id = request.data.get("user_id")
        conceder = bool(request.data.get("concedida"))

        if codigo not in CAPACIDADES_SEM_BYPASS_ADMIN:
            return Response(
                {"detail": "Capacidade não é atribuível diretamente."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cap = Capacidade.objects.filter(codigo=codigo).first()
        if not cap:
            return Response({"detail": "Capacidade não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        alvo = User.objects.filter(pk=user_id, is_active=True).first()
        if not alvo:
            return Response({"detail": "Usuário não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if conceder:
            alvo.capacidades_diretas.add(cap)
        else:
            alvo.capacidades_diretas.remove(cap)
        return Response({"codigo": codigo, "user_id": alvo.id, "concedida": conceder})

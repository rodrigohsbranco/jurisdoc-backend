# cadastro/views.py
from rest_framework import viewsets, permissions, filters, decorators, response, status
from django_filters.rest_framework import DjangoFilterBackend

from .models import Cliente, ContaBancaria, DescricaoBanco
from .filters import ClienteFilter, ContaBancariaFilter, DescricaoBancoFilter


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


class DescricaoBancoViewSet(viewsets.ModelViewSet):
    """
    Múltiplas descrições por banco (banco_id), com 1 ativa por vez.

    Endpoints úteis:
      - GET  /api/cadastro/bancos-descricoes/lookup/?bank_id=...  → retorna a ATIVA (200) ou 204 se nenhuma existir
      - GET  /api/cadastro/bancos-descricoes/variacoes/?bank_id=... → lista TODAS as descrições do banco (ordenadas: ativa primeiro)
      - POST /api/cadastro/bancos-descricoes/                     → cria nova descrição (pode vir com is_ativa=True)
      - PATCH/PUT /api/cadastro/bancos-descricoes/{id}/           → edita a descrição (pode marcar is_ativa=True)
      - POST/PATCH /api/cadastro/bancos-descricoes/{id}/set-ativa/→ marca esta como ativa (desativa as demais do mesmo banco)
    """
    queryset = DescricaoBanco.objects.all().order_by("banco_nome", "-is_ativa", "-atualizado_em")
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = None  # setado no get_serializer_class
    # lookup_field padrão = "pk" (id). Mantemos padrão pois há várias descrições por banco_id.

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DescricaoBancoFilter
    search_fields = ["banco_nome", "descricao", "banco_id"]
    ordering_fields = ["banco_nome", "is_ativa", "atualizado_em", "criado_em"]

    def get_serializer_class(self):
        from .serializers import DescricaoBancoSerializer
        return DescricaoBancoSerializer

    @decorators.action(detail=False, methods=["get"], url_path="lookup")
    def lookup(self, request):
        """
        Retorna a descrição ATIVA de um banco (ou a mais recente se nenhuma estiver ativa).
        - Params: bank_id=... [ou bank_name=...]
        """
        bank_id = request.query_params.get("bank_id") or request.query_params.get("banco_id")
        bank_name = request.query_params.get("bank_name") or request.query_params.get("banco_nome")

        if not bank_id and not bank_name:
            return response.Response(
                {"detail": "Informe bank_id/banco_id ou bank_name/banco_nome."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = self.get_queryset()
        if bank_id:
            qs = qs.filter(banco_id=bank_id)
        else:
            qs = qs.filter(banco_nome=bank_name)

        # tenta a ativa; se não houver, pega a mais recente
        obj = qs.filter(is_ativa=True).order_by("-atualizado_em").first() or qs.order_by("-is_ativa", "-atualizado_em").first()
        if not obj:
            return response.Response(status=status.HTTP_204_NO_CONTENT)

        ser = self.get_serializer(obj)
        return response.Response(ser.data, status=status.HTTP_200_OK)

    @decorators.action(detail=False, methods=["get"], url_path="variacoes")
    def variacoes(self, request):
        """
        Lista todas as descrições de um banco.
        - Params: bank_id=...
        """
        bank_id = request.query_params.get("bank_id") or request.query_params.get("banco_id")
        if not bank_id:
            return response.Response({"detail": "Parâmetro bank_id é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

        qs = self.get_queryset().filter(banco_id=bank_id).order_by("-is_ativa", "-atualizado_em")
        ser = self.get_serializer(qs, many=True)
        return response.Response(ser.data, status=status.HTTP_200_OK)

    @decorators.action(detail=True, methods=["post", "patch"], url_path="set-ativa")
    def set_ativa(self, request, pk=None):
        """
        Marca esta descrição (id) como ATIVA e desativa as demais do mesmo banco.
        """
        obj = self.get_object()
        from .serializers import DescricaoBancoSerializer  # evita import circular
        ser = DescricaoBancoSerializer(
            obj,
            data={"is_ativa": True},
            partial=True,
            context={"request": request},
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        return response.Response(ser.data, status=status.HTTP_200_OK)

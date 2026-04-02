from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import AcaoKit, Kit
from .serializers import (
    AcaoKitSerializer,
    KitCreateSerializer,
    KitDetailSerializer,
    KitListSerializer,
)


class IsOwnerOrAdmin(permissions.BasePermission):
    """Permite acesso ao dono do kit ou admins."""

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "is_admin", False):
            return True
        return obj.criado_por == request.user


# Transições válidas de status
TRANSICOES_VALIDAS = {
    "rascunho": ["acoes"],
    "acoes": ["finalizado"],
    "finalizado": ["assinado"],
    "assinado": [],
}


class KitViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "cliente", "criado_por"]
    search_fields = ["cliente__nome_completo", "cliente__cpf"]
    ordering_fields = ["criado_em", "atualizado_em"]
    ordering = ["-criado_em"]

    def get_queryset(self):
        qs = Kit.objects.select_related("cliente", "criado_por").prefetch_related("acoes", "documentos")
        if getattr(self.request.user, "is_admin", False):
            return qs
        return qs.filter(criado_por=self.request.user)

    def get_serializer_class(self):
        if self.action == "list":
            return KitListSerializer
        if self.action == "create":
            return KitCreateSerializer
        return KitDetailSerializer

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    def perform_destroy(self, instance):
        if instance.status != "rascunho":
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Só é possível excluir kits em rascunho.")
        instance.delete()

    # ── Custom actions ──

    @action(detail=True, methods=["post"])
    def finalizar(self, request, pk=None):
        kit = self.get_object()
        if kit.status not in TRANSICOES_VALIDAS or "finalizado" not in TRANSICOES_VALIDAS.get(kit.status, []):
            return Response(
                {"detail": f"Não é possível finalizar um kit com status '{kit.get_status_display()}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if kit.acoes.count() == 0:
            return Response(
                {"detail": "O kit precisa ter pelo menos uma ação para ser finalizado."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kit.status = "finalizado"
        kit.save(update_fields=["status", "atualizado_em"])
        return Response(KitDetailSerializer(kit).data)

    @action(detail=True, methods=["post"])
    def assinar(self, request, pk=None):
        kit = self.get_object()
        if kit.status != "finalizado":
            return Response(
                {"detail": "Só é possível assinar um kit finalizado."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kit.status = "assinado"
        kit.save(update_fields=["status", "atualizado_em"])
        return Response(KitDetailSerializer(kit).data)

    @action(detail=True, methods=["post"], url_path="mudar-status")
    def mudar_status(self, request, pk=None):
        """Avança o status do kit para o próximo estado válido."""
        kit = self.get_object()
        novo_status = request.data.get("status")
        if not novo_status:
            return Response({"detail": "Informe o novo status."}, status=status.HTTP_400_BAD_REQUEST)

        # Se já está no status desejado, retorna sem erro
        if kit.status == novo_status:
            return Response(KitDetailSerializer(kit).data)

        validos = TRANSICOES_VALIDAS.get(kit.status, [])
        if novo_status not in validos:
            return Response(
                {"detail": f"Transição de '{kit.status}' para '{novo_status}' não é permitida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kit.status = novo_status
        kit.save(update_fields=["status", "atualizado_em"])
        return Response(KitDetailSerializer(kit).data)


class AcaoKitViewSet(viewsets.ModelViewSet):
    serializer_class = AcaoKitSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AcaoKit.objects.filter(kit_id=self.kwargs["kit_pk"])

    def perform_create(self, serializer):
        kit = Kit.objects.get(pk=self.kwargs["kit_pk"])
        serializer.save(kit=kit)

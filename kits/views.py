from django.core.files.storage import default_storage
from django.db.models import Count, Q
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from accounts.permissions import IsAdmin
from .models import AcaoKit, AssociacaoKit, BancoKit, Kit, TarifaKit
from .serializers import (
    AcaoKitSerializer,
    AssociacaoKitSerializer,
    BancoKitSerializer,
    KitCreateSerializer,
    KitDetailSerializer,
    KitListSerializer,
    TarifaKitSerializer,
)


class IsOwnerOrAdmin(permissions.BasePermission):
    """Permite acesso ao dono do kit ou admins."""

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "is_admin", False):
            return True
        return obj.criado_por == request.user


# Transições válidas de status
TRANSICOES_VALIDAS = {
    "rascunho": ["acoes", "finalizado"],
    "acoes": ["finalizado"],
    "finalizado": ["assinado"],
    "assinado": [],
}


class KitViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["tipo", "status", "cliente", "criado_por"]
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
        if kit.tipo != "previdenciario" and kit.acoes.count() == 0:
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

    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = self.get_queryset()
        counts = qs.aggregate(
            total=Count("id"),
            rascunho=Count("id", filter=Q(status="rascunho")),
            em_andamento=Count("id", filter=Q(status="acoes")),
            pendentes=Count("id", filter=Q(status="finalizado")),
            assinados=Count("id", filter=Q(status="assinado")),
        )
        return Response(counts)


class AcaoKitViewSet(viewsets.ModelViewSet):
    serializer_class = AcaoKitSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    DOCS_FIELD_MAP = {
        "historico_emprestimo": "historico_emprestimo_arquivos",
        "historico_credito": "historico_credito_arquivos",
        "extrato_bancario": "extrato_bancario_arquivos",
    }

    def _get_kit(self):
        from django.shortcuts import get_object_or_404
        kit = get_object_or_404(Kit, pk=self.kwargs["kit_pk"])
        user = self.request.user
        if not getattr(user, "is_admin", False) and kit.criado_por != user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Você não tem permissão para acessar este kit.")
        return kit

    def get_queryset(self):
        self._get_kit()
        return AcaoKit.objects.filter(kit_id=self.kwargs["kit_pk"])

    def get_serializer(self, *args, **kwargs):
        data = kwargs.get("data")
        request = getattr(self, "request", None)
        if data is not None and request is not None and hasattr(data, "copy"):
            mutable = data.copy()
            for key in [
                "historico_emprestimo_keep_paths",
                "historico_credito_keep_paths",
                "extrato_bancario_keep_paths",
            ]:
                values = request.data.getlist(key)
                if values:
                    mutable.setlist(key, values)

            for key in [
                "historico_emprestimo_files",
                "historico_credito_files",
                "extrato_bancario_files",
            ]:
                files = request.FILES.getlist(key)
                if files:
                    mutable.setlist(key, files)

            kwargs["data"] = mutable
        return super().get_serializer(*args, **kwargs)

    def perform_create(self, serializer):
        kit = self._get_kit()
        serializer.save(kit=kit)

    @action(detail=True, methods=["post"], url_path="anexos/upload")
    def upload_attachments(self, request, kit_pk=None, pk=None):
        instance = self.get_object()
        owner = request.data.get("owner")
        field_name = self.DOCS_FIELD_MAP.get(owner)
        if not field_name:
            return Response({"detail": "Owner inválido."}, status=status.HTTP_400_BAD_REQUEST)

        files = request.FILES.getlist("files")
        if not files:
            return Response({"detail": "Nenhum arquivo enviado."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(getattr(instance, field_name) or [])
        for file in files:
            path = default_storage.save(f"kits/acoes/{instance.pk}/{owner}/{file.name}", file)
            docs.append({"path": path, "name": file.name})

        setattr(instance, field_name, docs)
        instance.save(update_fields=[field_name])

        serializer = self.get_serializer(instance)
        return Response({"documentos": serializer.data[field_name]}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="anexos/remove")
    def remove_attachment(self, request, kit_pk=None, pk=None):
        instance = self.get_object()
        owner = request.data.get("owner")
        field_name = self.DOCS_FIELD_MAP.get(owner)
        if not field_name:
            return Response({"detail": "Owner inválido."}, status=status.HTTP_400_BAD_REQUEST)

        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return Response({"detail": "Informe o campo 'path'."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(getattr(instance, field_name) or [])
        new_docs = [doc for doc in docs if doc.get("path") != path_to_remove]
        if len(new_docs) == len(docs):
            return Response({"detail": "Documento não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        setattr(instance, field_name, new_docs)
        instance.save(update_fields=[field_name])

        serializer = self.get_serializer(instance)
        return Response({"documentos": serializer.data[field_name]}, status=status.HTTP_200_OK)


class BancoKitViewSet(viewsets.ModelViewSet):
    queryset = BancoKit.objects.all()
    serializer_class = BancoKitSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nome"]
    ordering_fields = ["nome", "ordem"]
    ordering = ["ordem", "nome"]
    pagination_class = None

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdmin()]


class TarifaKitViewSet(viewsets.ModelViewSet):
    queryset = TarifaKit.objects.all()
    serializer_class = TarifaKitSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nome"]
    ordering_fields = ["nome", "ordem"]
    ordering = ["ordem", "nome"]
    pagination_class = None

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdmin()]


class AssociacaoKitViewSet(viewsets.ModelViewSet):
    queryset = AssociacaoKit.objects.all()
    serializer_class = AssociacaoKitSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nome", "abreviacao"]
    ordering_fields = ["nome", "abreviacao", "ordem"]
    ordering = ["ordem", "nome"]
    pagination_class = None

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdmin()]

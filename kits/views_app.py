from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from accounts.service_auth import IsServiceAdmin, ServiceClientAuthentication
from .models import AcaoKit, Kit, resolver_clausula_porcentagem
from .serializers import AcaoKitSerializer
from .serializers_app import KitAppCreateSerializer, KitAppDetailSerializer, KitAppListSerializer


TRANSICOES_VALIDAS = {
    "rascunho": ["acoes", "finalizado"],
    "acoes": ["finalizado"],
    "finalizado": ["assinado"],
    "assinado": [],
}

_APP_SYSTEM_USERNAME = "app_flowalr"


def _get_app_user():
    User = get_user_model()
    try:
        return User.objects.get(username=_APP_SYSTEM_USERNAME)
    except User.DoesNotExist:
        raise ValidationError(
            {"detail": f"Usuário de sistema '{_APP_SYSTEM_USERNAME}' não encontrado. Crie-o no JurisDoc antes de usar a API de kits pelo app."}
        )


class KitAppViewSet(viewsets.ModelViewSet):
    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceAdmin]
    pagination_class = None
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["tipo", "status", "cliente", "origem"]
    search_fields = ["cliente__nome_completo", "cliente__cpf", "app_criado_por_nome"]
    ordering_fields = ["criado_em", "atualizado_em", "status"]
    ordering = ["-criado_em"]

    def get_queryset(self):
        return (
            Kit.objects
            .select_related("cliente", "criado_por")
            .prefetch_related("acoes", "documentos")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return KitAppListSerializer
        if self.action == "create":
            return KitAppCreateSerializer
        return KitAppDetailSerializer

    def perform_create(self, serializer):
        app_user = _get_app_user()
        serializer.save(criado_por=app_user, origem="app")

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status != "rascunho":
            return Response(
                {"detail": "Só é possível excluir kits em rascunho."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Ações de status ──

    @action(detail=True, methods=["post"])
    def finalizar(self, request, pk=None):
        kit = self.get_object()
        if "finalizado" not in TRANSICOES_VALIDAS.get(kit.status, []):
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
        return Response(KitAppDetailSerializer(kit, context={"request": request}).data)

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
        return Response(KitAppDetailSerializer(kit, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="mudar-status")
    def mudar_status(self, request, pk=None):
        kit = self.get_object()
        novo_status = request.data.get("status")
        if not novo_status:
            return Response({"detail": "Informe o novo status."}, status=status.HTTP_400_BAD_REQUEST)

        if kit.status == novo_status:
            return Response(KitAppDetailSerializer(kit, context={"request": request}).data)

        validos = TRANSICOES_VALIDAS.get(kit.status, [])
        if novo_status not in validos:
            return Response(
                {"detail": f"Transição de '{kit.status}' para '{novo_status}' não é permitida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kit.status = novo_status
        kit.save(update_fields=["status", "atualizado_em"])
        return Response(KitAppDetailSerializer(kit, context={"request": request}).data)

    # ── Advogados ──

    @action(detail=True, methods=["get"], url_path="advogados/sugeridos")
    def advogados_sugeridos(self, request, pk=None):
        from .services_advogados import sugerir_advogados
        kit = self.get_object()
        uf = (getattr(kit.cliente, "uf", "") or "").upper()
        tipos = set(kit.acoes.values_list("tipo_acao", flat=True))
        ids = sugerir_advogados(uf, tipos)
        return Response({"advogados_ids": ids, "uf_cliente": uf})

    @action(detail=True, methods=["get", "post"], url_path="advogados")
    def advogados(self, request, pk=None):
        from .services_advogados import montar_snapshot
        kit = self.get_object()

        if request.method == "GET":
            return Response({"advogados_snapshot": list(kit.advogados_snapshot or [])})

        ids = request.data.get("advogados_ids")
        if ids is None or not isinstance(ids, list):
            return Response(
                {"detail": "Informe 'advogados_ids' como lista de IDs inteiros."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uf = (getattr(kit.cliente, "uf", "") or "").upper()
        snapshot, warnings = montar_snapshot(ids, uf)
        kit.advogados_snapshot = snapshot
        kit.save(update_fields=["advogados_snapshot", "atualizado_em"])
        return Response({"advogados_snapshot": snapshot, "warnings": warnings})

    # ── Cláusula de porcentagem ──

    @action(detail=True, methods=["get", "post"], url_path="clausula-snapshot")
    def clausula_snapshot(self, request, pk=None):
        kit = self.get_object()
        uf = (getattr(kit.cliente, "uf", "") or "").upper()

        if kit.clausula_porcentagem_snapshot:
            return Response({
                "uf": uf,
                "texto": kit.clausula_porcentagem_snapshot,
                "fonte": "snapshot",
                "ja_persistido": True,
            })

        tipos = list(kit.acoes.order_by("id").values_list("tipo_acao", flat=True))
        texto, fonte = resolver_clausula_porcentagem(uf, tipos)

        if request.method == "POST":
            kit.clausula_porcentagem_snapshot = texto
            kit.save(update_fields=["clausula_porcentagem_snapshot", "atualizado_em"])
            return Response({"uf": uf, "texto": texto, "fonte": fonte, "ja_persistido": True})

        return Response({"uf": uf, "texto": texto, "fonte": fonte, "ja_persistido": False})

    # ── Stats ──

    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = self.get_queryset().filter(origem="app")
        counts = qs.aggregate(
            total=Count("id"),
            rascunho=Count("id", filter=Q(status="rascunho")),
            em_andamento=Count("id", filter=Q(status="acoes")),
            pendentes=Count("id", filter=Q(status="finalizado")),
            assinados=Count("id", filter=Q(status="assinado")),
        )
        return Response(counts)


class AcaoKitAppViewSet(viewsets.ModelViewSet):
    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceAdmin]
    serializer_class = AcaoKitSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    DOCS_FIELD_MAP = {
        "historico_emprestimo": "historico_emprestimo_arquivos",
        "historico_credito": "historico_credito_arquivos",
        "extrato_bancario": "extrato_bancario_arquivos",
    }

    def _get_kit(self):
        return get_object_or_404(Kit, pk=self.kwargs["kit_pk"])

    def get_queryset(self):
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
            return Response(
                {"detail": "Owner inválido. Use: historico_emprestimo, historico_credito ou extrato_bancario."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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

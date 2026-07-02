import re

from django.core.files.storage import default_storage

from rest_framework import viewsets, filters, decorators, response, status
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend

from accounts.service_auth import IsServiceAdmin, ServiceClientAuthentication
from .media_paths import build_media_file_url
from .models import Cliente
from .filters import ClienteFilter
from .serializers import ClienteSerializer

_STATUS_DISPLAY = {
    "rascunho": "Rascunho",
    "acoes": "Em andamento",
    "finalizado": "Pend. assinatura",
    "assinado": "Assinado",
}
_TIPO_DISPLAY = {
    "bancario": "Bancário",
    "previdenciario": "Previdenciário",
    "marketing": "Marketing",
}


_RELATED_DOCS_FIELD_MAP = {
    "rogado": "rogado_documentos",
    "testemunha1": "testemunha1_documentos",
    "testemunha2": "testemunha2_documentos",
    "responsavel_legal": "responsavel_legal_documentos",
}


def _docs_with_urls(docs, request):
    return [{**d, "url": build_media_file_url(request, d.get("path"))} for d in docs]


class ClienteAppViewSet(viewsets.ModelViewSet):
    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceAdmin]
    serializer_class = ClienteSerializer
    pagination_class = None
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ClienteFilter
    search_fields = ["nome_completo", "cpf", "cidade", "bairro", "profissao", "nacionalidade"]
    ordering_fields = ["nome_completo", "criado_em", "atualizado_em", "cidade"]
    ordering = ["-criado_em"]

    def get_queryset(self):
        qs = Cliente.objects.all().order_by("-criado_em")
        if self.request.query_params.get("is_active") is None:
            qs = qs.filter(is_active=True)
        return qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = False
        instance.save()
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        instance = Cliente.objects.filter(pk=pk).first()
        if instance is None:
            return response.Response({"detail": "Cliente não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        if instance.is_active:
            return response.Response({"detail": "Este cliente já está ativo."}, status=status.HTTP_400_BAD_REQUEST)
        instance.is_active = True
        instance.save()
        return response.Response(self.get_serializer(instance).data)

    # ------------------------------------------------------------------
    # Busca por CPF com resumo de kits
    # ------------------------------------------------------------------

    @decorators.action(detail=False, methods=["get"], url_path="buscar-por-cpf")
    def buscar_por_cpf(self, request):
        """
        Consulta cliente pelo CPF e retorna seus dados + resumo dos kits existentes.

        GET /api/app/clientes/buscar-por-cpf/?cpf=01234567890

        Resposta quando encontrado:
          { "encontrado": true, "cliente": {...}, "kits": [{id, tipo, tipo_display, status, status_display, criado_em}] }

        Resposta quando não encontrado:
          { "encontrado": false, "cliente": null, "kits": [] }
        """
        from kits.models import Kit

        cpf_raw = request.query_params.get("cpf", "")
        cpf = re.sub(r"\D", "", cpf_raw)
        if len(cpf) != 11:
            return response.Response(
                {"detail": "Informe o CPF com 11 dígitos (apenas números ou formatado)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente = Cliente.objects.filter(cpf=cpf, is_active=True).first()
        if cliente is None:
            return response.Response({"encontrado": False, "cliente": None, "kits": []})

        kits = (
            Kit.objects
            .filter(cliente=cliente)
            .only("id", "tipo", "status", "criado_em")
            .order_by("-criado_em")
        )

        kits_data = [
            {
                "id": k.id,
                "tipo": k.tipo,
                "tipo_display": _TIPO_DISPLAY.get(k.tipo, k.tipo),
                "status": k.status,
                "status_display": _STATUS_DISPLAY.get(k.status, k.status),
                "criado_em": k.criado_em,
            }
            for k in kits
        ]

        return response.Response({
            "encontrado": True,
            "cliente": self.get_serializer(cliente).data,
            "kits": kits_data,
        })

    # ------------------------------------------------------------------
    # Documentos pessoais
    # ------------------------------------------------------------------

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="documentos-pessoais/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_docs(self, request, pk=None):
        instance = self.get_object()
        files = request.FILES.getlist("files")
        if not files:
            return response.Response({"detail": "Nenhum arquivo enviado."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(instance.documentos_pessoais or [])
        for f in files:
            path = default_storage.save(f"clientes/docs/{instance.pk}/{f.name}", f)
            docs.append({"path": path, "name": f.name})

        instance.documentos_pessoais = docs
        instance.save(update_fields=["documentos_pessoais"])
        return response.Response({"documentos_pessoais": _docs_with_urls(docs, request)})

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="documentos-pessoais/remove",
    )
    def remove_doc(self, request, pk=None):
        instance = self.get_object()
        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return response.Response({"detail": "Informe o campo 'path'."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(instance.documentos_pessoais or [])
        new_docs = [d for d in docs if d.get("path") != path_to_remove]
        if len(new_docs) == len(docs):
            return response.Response({"detail": "Documento não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        instance.documentos_pessoais = new_docs
        instance.save(update_fields=["documentos_pessoais"])
        return response.Response({"documentos_pessoais": _docs_with_urls(new_docs, request)})

    # ------------------------------------------------------------------
    # Documentos vinculados (rogado, testemunhas, responsável legal)
    # ------------------------------------------------------------------

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="documentos-vinculados/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_related_docs(self, request, pk=None):
        """
        Campos do form-data:
          owner: rogado | testemunha1 | testemunha2 | responsavel_legal
          files: um ou mais arquivos
        """
        instance = self.get_object()
        owner = request.data.get("owner")
        field_name = _RELATED_DOCS_FIELD_MAP.get(owner)
        if not field_name:
            return response.Response(
                {"detail": "Campo 'owner' inválido. Use: rogado, testemunha1, testemunha2, responsavel_legal."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        files = request.FILES.getlist("files")
        if not files:
            return response.Response({"detail": "Nenhum arquivo enviado."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(getattr(instance, field_name) or [])
        for f in files:
            path = default_storage.save(f"clientes/docs/{instance.pk}/{owner}/{f.name}", f)
            docs.append({"path": path, "name": f.name})

        setattr(instance, field_name, docs)
        instance.save(update_fields=[field_name])
        return response.Response({"owner": owner, "documentos": _docs_with_urls(docs, request)})

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="documentos-vinculados/remove",
    )
    def remove_related_doc(self, request, pk=None):
        """
        Body JSON:
          owner: rogado | testemunha1 | testemunha2 | responsavel_legal
          path: caminho do arquivo a remover
        """
        instance = self.get_object()
        owner = request.data.get("owner")
        field_name = _RELATED_DOCS_FIELD_MAP.get(owner)
        if not field_name:
            return response.Response(
                {"detail": "Campo 'owner' inválido. Use: rogado, testemunha1, testemunha2, responsavel_legal."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return response.Response({"detail": "Informe o campo 'path'."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(getattr(instance, field_name) or [])
        new_docs = [d for d in docs if d.get("path") != path_to_remove]
        if len(new_docs) == len(docs):
            return response.Response({"detail": "Documento não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        setattr(instance, field_name, new_docs)
        instance.save(update_fields=[field_name])
        return response.Response({"owner": owner, "documentos": _docs_with_urls(new_docs, request)})

    # ------------------------------------------------------------------
    # Comprovantes de residência
    # ------------------------------------------------------------------

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="comprovantes-residencia/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_comprovantes(self, request, pk=None):
        instance = self.get_object()
        files = request.FILES.getlist("files")
        if not files:
            return response.Response({"detail": "Nenhum arquivo enviado."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(instance.comprovantes_residencia or [])
        for f in files:
            path = default_storage.save(f"clientes/comprovantes/{instance.pk}/{f.name}", f)
            docs.append({"path": path, "name": f.name})

        instance.comprovantes_residencia = docs
        instance.save(update_fields=["comprovantes_residencia"])
        return response.Response({"comprovantes_residencia": _docs_with_urls(docs, request)})

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="comprovantes-residencia/remove",
    )
    def remove_comprovante(self, request, pk=None):
        instance = self.get_object()
        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return response.Response({"detail": "Informe o campo 'path'."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(instance.comprovantes_residencia or [])
        new_docs = [d for d in docs if d.get("path") != path_to_remove]
        if len(new_docs) == len(docs):
            return response.Response({"detail": "Comprovante não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        instance.comprovantes_residencia = new_docs
        instance.save(update_fields=["comprovantes_residencia"])
        return response.Response({"comprovantes_residencia": _docs_with_urls(new_docs, request)})

    # ------------------------------------------------------------------
    # Documentos do responsável pelo imóvel
    # ------------------------------------------------------------------

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="responsavel-imovel-docs/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_responsavel_docs(self, request, pk=None):
        instance = self.get_object()
        files = request.FILES.getlist("files")
        if not files:
            return response.Response({"detail": "Nenhum arquivo enviado."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(instance.responsavel_imovel_docs or [])
        for f in files:
            path = default_storage.save(f"clientes/comprovantes/{instance.pk}/responsavel/{f.name}", f)
            docs.append({"path": path, "name": f.name})

        instance.responsavel_imovel_docs = docs
        instance.save(update_fields=["responsavel_imovel_docs"])
        return response.Response({"responsavel_imovel_docs": _docs_with_urls(docs, request)})

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="responsavel-imovel-docs/remove",
    )
    def remove_responsavel_doc(self, request, pk=None):
        instance = self.get_object()
        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return response.Response({"detail": "Informe o campo 'path'."}, status=status.HTTP_400_BAD_REQUEST)

        docs = list(instance.responsavel_imovel_docs or [])
        new_docs = [d for d in docs if d.get("path") != path_to_remove]
        if len(new_docs) == len(docs):
            return response.Response({"detail": "Documento não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        instance.responsavel_imovel_docs = new_docs
        instance.save(update_fields=["responsavel_imovel_docs"])
        return response.Response({"responsavel_imovel_docs": _docs_with_urls(new_docs, request)})

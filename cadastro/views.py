# cadastro/views.py
import os
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps

from rest_framework import viewsets, permissions, filters, decorators, response, status
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend

from permissoes.permissions import HasCapability
from .media_paths import build_media_file_url
from .models import Cliente, ContaBancaria, ContaBancariaReu, DescricaoBanco, Representante, Contrato
from .filters import ClienteFilter, ContaBancariaFilter, DescricaoBancoFilter


# Se quiser manter a classe abaixo para uso futuro, tudo bem,
# mas não vamos usá-la nos ViewSets do cadastro agora.
class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and getattr(request.user, "is_admin", False))


class ClienteViewSet(viewsets.ModelViewSet):
    queryset = Cliente.objects.filter(is_active=True).order_by("-criado_em")
    serializer_class = None  # setado no get_serializer_class

    def get_permissions(self):
        return [HasCapability.for_action(self.action, {
            "list": "clientes.visualizar",
            "retrieve": "clientes.visualizar",
            "create": "clientes.criar",
            "update": "clientes.editar",
            "partial_update": "clientes.editar",
            "destroy": "clientes.deletar",
            "restore": "clientes.restaurar",
            "upload_docs": "clientes.editar",
            "remove_doc": "clientes.editar",
            "upload_related_docs": "clientes.editar",
            "remove_related_doc": "clientes.editar",
            "upload_comprovantes": "clientes.editar",
            "remove_comprovante": "clientes.editar",
            "upload_responsavel_docs": "clientes.editar",
            "remove_responsavel_doc": "clientes.editar",
            "upload_fotos_residencia": "clientes.editar",
            "remove_foto_residencia": "clientes.editar",
        })]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ClienteFilter
    search_fields = [
        "nome_completo",
        "cpf",
        "cidade",
        "bairro",
        # campos novos úteis para busca
        "profissao",
        "nacionalidade",
    ]
    ordering_fields = [
        "nome_completo",
        "criado_em",
        "atualizado_em",
        # ordenações adicionais úteis
        "cidade",
        "bairro",
    ]
    DOCS_FIELD_MAP = {
        "documentos_pessoais": "documentos_pessoais",
        "rogado": "rogado_documentos",
        "testemunha1": "testemunha1_documentos",
        "testemunha2": "testemunha2_documentos",
        "responsavel_legal": "responsavel_legal_documentos",
    }

    def get_queryset(self):
        """
        Retorna apenas clientes ativos por padrão.
        Para ver inativos, use ?is_active=false na query.
        Para ver todos, use ?is_active= (vazio) ou não passe o parâmetro e use o filtro manualmente.
        """
        qs = Cliente.objects.all().order_by("-criado_em")
        is_active_param = self.request.query_params.get("is_active")
        
        # Se não foi especificado, filtra apenas ativos por padrão
        if is_active_param is None:
            qs = qs.filter(is_active=True)
        
        # Se foi especificado, o django-filters vai aplicar o filtro
        return qs

    def get_serializer_class(self):
        from .serializers import ClienteSerializer
        return ClienteSerializer

    def destroy(self, request, *args, **kwargs):
        """
        Soft delete: marca o cliente como inativo ao invés de deletar.
        """
        instance = self.get_object()
        instance.is_active = False
        instance.save()
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="documentos-pessoais/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_docs(self, request, pk=None):
        """
        Upload de documentos pessoais (múltiplos arquivos).
        Aceita campo 'files' com um ou mais arquivos.
        Salva em clientes/docs/<pk>/ e adiciona os paths ao JSONField.
        """
        instance = self.get_object()
        files = request.FILES.getlist("files")
        if not files:
            return response.Response(
                {"detail": "Nenhum arquivo enviado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(instance.documentos_pessoais or [])
        for f in files:
            path = default_storage.save(f"clientes/docs/{instance.pk}/{f.name}", f)
            docs.append({"path": path, "name": f.name})

        instance.documentos_pessoais = docs
        instance.save(update_fields=["documentos_pessoais"])

        # Retorna com URLs absolutas
        result = self._docs_with_urls(docs, request)
        return response.Response({"documentos_pessoais": result}, status=status.HTTP_200_OK)

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="documentos-pessoais/remove",
    )
    def remove_doc(self, request, pk=None):
        """
        Remove um documento pessoal pelo path.
        Body: {"path": "clientes/docs/123/rg.jpg"}
        """
        instance = self.get_object()
        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return response.Response(
                {"detail": "Informe o campo 'path'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(instance.documentos_pessoais or [])
        new_docs = [d for d in docs if d.get("path") != path_to_remove]

        if len(new_docs) == len(docs):
            return response.Response(
                {"detail": "Documento não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Remove arquivo do disco
        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        instance.documentos_pessoais = new_docs
        instance.save(update_fields=["documentos_pessoais"])

        result = self._docs_with_urls(new_docs, request)
        return response.Response({"documentos_pessoais": result}, status=status.HTTP_200_OK)

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="documentos-vinculados/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_related_docs(self, request, pk=None):
        """
        Upload de documentos por participante do kit.
        Campos:
        - owner: rogado | testemunha1 | testemunha2 | responsavel_legal
        - files: um ou mais arquivos
        """
        instance = self.get_object()
        owner = request.data.get("owner")
        field_name = self.DOCS_FIELD_MAP.get(owner)
        if not field_name or field_name == "documentos_pessoais":
            return response.Response(
                {"detail": "Owner inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        files = request.FILES.getlist("files")
        if not files:
            return response.Response(
                {"detail": "Nenhum arquivo enviado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(getattr(instance, field_name) or [])
        for f in files:
            path = default_storage.save(f"clientes/docs/{instance.pk}/{owner}/{f.name}", f)
            docs.append({"path": path, "name": f.name})

        setattr(instance, field_name, docs)
        instance.save(update_fields=[field_name])

        return response.Response(
            {"documentos": self._docs_with_urls(docs, request)},
            status=status.HTTP_200_OK,
        )

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="documentos-vinculados/remove",
    )
    def remove_related_doc(self, request, pk=None):
        """
        Remove documento de participante do kit.
        Body:
        - owner: rogado | testemunha1 | testemunha2 | responsavel_legal
        - path: caminho do arquivo
        """
        instance = self.get_object()
        owner = request.data.get("owner")
        field_name = self.DOCS_FIELD_MAP.get(owner)
        if not field_name or field_name == "documentos_pessoais":
            return response.Response(
                {"detail": "Owner inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return response.Response(
                {"detail": "Informe o campo 'path'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(getattr(instance, field_name) or [])
        new_docs = [d for d in docs if d.get("path") != path_to_remove]

        if len(new_docs) == len(docs):
            return response.Response(
                {"detail": "Documento não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        setattr(instance, field_name, new_docs)
        instance.save(update_fields=[field_name])

        return response.Response(
            {"documentos": self._docs_with_urls(new_docs, request)},
            status=status.HTTP_200_OK,
        )

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="comprovantes-residencia/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_comprovantes(self, request, pk=None):
        """Upload de comprovantes de residência do cliente (múltiplos arquivos)."""
        instance = self.get_object()
        files = request.FILES.getlist("files")
        if not files:
            return response.Response(
                {"detail": "Nenhum arquivo enviado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(instance.comprovantes_residencia or [])
        for f in files:
            path = default_storage.save(
                f"clientes/comprovantes/{instance.pk}/{f.name}", f
            )
            docs.append({"path": path, "name": f.name})

        instance.comprovantes_residencia = docs
        instance.save(update_fields=["comprovantes_residencia"])
        return response.Response(
            {"comprovantes_residencia": self._docs_with_urls(docs, request)},
            status=status.HTTP_200_OK,
        )

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="comprovantes-residencia/remove",
    )
    def remove_comprovante(self, request, pk=None):
        """Remove um comprovante de residência pelo path."""
        instance = self.get_object()
        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return response.Response(
                {"detail": "Informe o campo 'path'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(instance.comprovantes_residencia or [])
        new_docs = [d for d in docs if d.get("path") != path_to_remove]
        if len(new_docs) == len(docs):
            return response.Response(
                {"detail": "Comprovante não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        instance.comprovantes_residencia = new_docs
        instance.save(update_fields=["comprovantes_residencia"])
        return response.Response(
            {"comprovantes_residencia": self._docs_with_urls(new_docs, request)},
            status=status.HTTP_200_OK,
        )

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="responsavel-imovel-docs/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_responsavel_docs(self, request, pk=None):
        """Upload de documentos do responsável pelo imóvel (múltiplos arquivos)."""
        instance = self.get_object()
        files = request.FILES.getlist("files")
        if not files:
            return response.Response(
                {"detail": "Nenhum arquivo enviado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(instance.responsavel_imovel_docs or [])
        for f in files:
            path = default_storage.save(
                f"clientes/comprovantes/{instance.pk}/responsavel/{f.name}", f
            )
            docs.append({"path": path, "name": f.name})

        instance.responsavel_imovel_docs = docs
        instance.save(update_fields=["responsavel_imovel_docs"])
        return response.Response(
            {"responsavel_imovel_docs": self._docs_with_urls(docs, request)},
            status=status.HTTP_200_OK,
        )

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="responsavel-imovel-docs/remove",
    )
    def remove_responsavel_doc(self, request, pk=None):
        """Remove um documento do responsável pelo imóvel pelo path."""
        instance = self.get_object()
        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return response.Response(
                {"detail": "Informe o campo 'path'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(instance.responsavel_imovel_docs or [])
        new_docs = [d for d in docs if d.get("path") != path_to_remove]
        if len(new_docs) == len(docs):
            return response.Response(
                {"detail": "Documento não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        instance.responsavel_imovel_docs = new_docs
        instance.save(update_fields=["responsavel_imovel_docs"])
        return response.Response(
            {"responsavel_imovel_docs": self._docs_with_urls(new_docs, request)},
            status=status.HTTP_200_OK,
        )

    # --- Fotos da residência (geolocalização) ---
    FOTOS_RESIDENCIA_MAX = 10
    FOTOS_RESIDENCIA_MIME = {"image/jpeg", "image/png", "image/webp"}

    @staticmethod
    def _comprimir_imagem(f):
        """Redimensiona (máx 1920px) e recomprime como JPEG, removendo metadados/EXIF.
        Retorna (ContentFile, nome_final)."""
        img = Image.open(f)
        img = ImageOps.exif_transpose(img)  # corrige orientação antes de descartar EXIF
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((1920, 1920))  # mantém proporção, sem upscale
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=82, optimize=True)
        buffer.seek(0)
        base = os.path.splitext(os.path.basename(f.name))[0]
        return ContentFile(buffer.read()), f"{base}.jpg"

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="fotos-residencia/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_fotos_residencia(self, request, pk=None):
        """
        Upload de fotos da residência (múltiplos arquivos).
        Aceita campo 'files'. Valida MIME (jpg/png/webp) e limite de 10 fotos.
        Comprime via Pillow e salva em clientes/fotos_residencia/<pk>/.
        """
        instance = self.get_object()
        files = request.FILES.getlist("files")
        if not files:
            return response.Response(
                {"detail": "Nenhum arquivo enviado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(instance.fotos_residencia or [])
        if len(docs) + len(files) > self.FOTOS_RESIDENCIA_MAX:
            return response.Response(
                {"detail": f"Limite de {self.FOTOS_RESIDENCIA_MAX} fotos por residência."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for f in files:
            if f.content_type not in self.FOTOS_RESIDENCIA_MIME:
                return response.Response(
                    {"detail": f"Formato não suportado: {f.name}. Use JPG, PNG ou WEBP."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        for f in files:
            try:
                content, nome = self._comprimir_imagem(f)
            except Exception:
                return response.Response(
                    {"detail": f"Imagem inválida ou corrompida: {f.name}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            path = default_storage.save(
                f"clientes/fotos_residencia/{instance.pk}/{nome}", content
            )
            docs.append({"path": path, "name": nome})

        instance.fotos_residencia = docs
        instance.save(update_fields=["fotos_residencia"])

        result = self._docs_with_urls(docs, request)
        return response.Response({"fotos_residencia": result}, status=status.HTTP_200_OK)

    @decorators.action(
        detail=True,
        methods=["post"],
        url_path="fotos-residencia/remove",
    )
    def remove_foto_residencia(self, request, pk=None):
        """Remove uma foto da residência pelo path. Body: {"path": "..."}"""
        instance = self.get_object()
        path_to_remove = request.data.get("path")
        if not path_to_remove:
            return response.Response(
                {"detail": "Informe o campo 'path'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        docs = list(instance.fotos_residencia or [])
        new_docs = [d for d in docs if d.get("path") != path_to_remove]
        if len(new_docs) == len(docs):
            return response.Response(
                {"detail": "Foto não encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if default_storage.exists(path_to_remove):
            default_storage.delete(path_to_remove)

        instance.fotos_residencia = new_docs
        instance.save(update_fields=["fotos_residencia"])
        return response.Response(
            {"fotos_residencia": self._docs_with_urls(new_docs, request)},
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _docs_with_urls(docs, request):
        """Adiciona URL absoluta a cada doc baseado no path salvo."""
        result = []
        for d in docs:
            url = build_media_file_url(request, d.get("path"))
            result.append({**d, "url": url})
        return result

    @decorators.action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        """
        Restaura um cliente inativo (marca como ativo novamente).
        """
        instance = self.get_object()
        if instance.is_active:
            return response.Response(
                {"detail": "Este cliente já está ativo."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance.is_active = True
        instance.save()
        ser = self.get_serializer(instance)
        return response.Response(ser.data, status=status.HTTP_200_OK)


class ContaBancariaViewSet(viewsets.ModelViewSet):
    queryset = (
        ContaBancaria.objects.select_related("cliente")
        .all()
        .order_by("cliente__nome_completo", "banco_nome")
    )
    serializer_class = None

    def get_permissions(self):
        return [HasCapability.for_action(self.action, {
            "list": "contas.visualizar",
            "retrieve": "contas.visualizar",
            "create": "contas.criar",
            "update": "contas.editar",
            "partial_update": "contas.editar",
            "destroy": "contas.deletar",
        })]
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

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DescricaoBancoFilter

    def get_permissions(self):
        return [HasCapability.for_action(self.action, {
            "list": "bancos_tarifas.visualizar",
            "retrieve": "bancos_tarifas.visualizar",
            "lookup": "bancos_tarifas.visualizar",
            "variacoes": "bancos_tarifas.visualizar",
            "create": "bancos_tarifas.criar",
            "update": "bancos_tarifas.editar",
            "partial_update": "bancos_tarifas.editar",
            "destroy": "bancos_tarifas.deletar",
            "set_ativa": "bancos_tarifas.ativar",
        })]
    search_fields = ["banco_nome", "nome_banco", "cnpj", "endereco", "banco_id"]
    ordering_fields = ["banco_nome", "is_ativa", "atualizado_em", "criado_em"]

    def get_serializer_class(self):
        from .serializers import DescricaoBancoSerializer
        return DescricaoBancoSerializer

    def get_queryset(self):
        """
        Retorna o queryset base. Mantém filtragens apenas para listagem,
        mas permite exclusão de qualquer registro existente.
        """
        qs = DescricaoBanco.objects.all().order_by("banco_nome", "-is_ativa", "-atualizado_em")

        # ⚙️ Se a ação for listagem, aplicamos filtros via filterset
        if self.action in ["list", "variacoes", "lookup"]:
            # A filtragem extra ocorre nos métodos específicos (lookup/variacoes)
            return qs

        # Para DELETE ou PATCH/PUT, retornamos o conjunto completo
        return qs

    # ====================== Custom Actions ======================

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

        obj = (
            qs.filter(is_ativa=True).order_by("-atualizado_em").first()
            or qs.order_by("-is_ativa", "-atualizado_em").first()
        )
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
            return response.Response(
                {"detail": "Parâmetro bank_id é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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


# --------------------------------------------------------------------
# Representantes
# --------------------------------------------------------------------
class RepresentanteViewSet(viewsets.ModelViewSet):
    """
    CRUD de Representantes de Cliente.
    - Cópia de endereço do cliente é feita no serializer quando 'usa_endereco_do_cliente=True'.
    """
    queryset = Representante.objects.select_related("cliente").all().order_by("cliente__nome_completo", "nome_completo")
    serializer_class = None  # setado no get_serializer_class

    def get_permissions(self):
        return [HasCapability.for_action(self.action, {
            "list": "representantes.visualizar",
            "retrieve": "representantes.visualizar",
            "create": "representantes.criar",
            "update": "representantes.editar",
            "partial_update": "representantes.editar",
            "destroy": "representantes.deletar",
        })]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # Usamos filterset_fields simples para não depender de um filtro customizado
    filterset_fields = [
        "cliente",
        "cpf",
        "se_idoso",
        "se_incapaz",
        "se_crianca_adolescente",
    ]
    search_fields = [
        "nome_completo",
        "cpf",
        "cidade",
        "bairro",
        "profissao",
        "nacionalidade",
        "cliente__nome_completo",
    ]
    ordering_fields = [
        "nome_completo",
        "criado_em",
        "atualizado_em",
        "cliente__nome_completo",
    ]

    def get_serializer_class(self):
        from .serializers import RepresentanteSerializer
        return RepresentanteSerializer


# --------------------------------------------------------------------
# Contas Bancárias dos Réus
# --------------------------------------------------------------------
class ContaBancariaReuViewSet(viewsets.ModelViewSet):
    """
    CRUD de Contas Bancárias dos Réus.
    Bancos dos réus não estão mais atrelados a clientes específicos.
    """
    queryset = (
        ContaBancariaReu.objects.all()
        .order_by("banco_nome")
    )
    serializer_class = None
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["banco_nome", "banco_codigo", "cidade", "estado"]

    def get_permissions(self):
        return [HasCapability.for_action(self.action, {
            "list": "conta_reu.visualizar",
            "retrieve": "conta_reu.visualizar",
            "create": "conta_reu.criar",
            "update": "conta_reu.editar",
            "partial_update": "conta_reu.editar",
            "destroy": "conta_reu.deletar",
        })]
    search_fields = ["banco_nome", "cnpj", "cidade"]
    ordering_fields = ["banco_nome", "criado_em"]

    def get_serializer_class(self):
        from .serializers import ContaBancariaReuSerializer
        return ContaBancariaReuSerializer


# --------------------------------------------------------------------
# Contratos
# --------------------------------------------------------------------
class ContratoViewSet(viewsets.ModelViewSet):
    """
    CRUD de Contratos.
    - Cada contrato possui um cliente, template e um array JSONB de contratos.
    - Permite criar e deletar quantas vezes quiser.
    - Não usa CASCADE: ao deletar o contrato, não afeta cliente ou template.
    """
    queryset = (
        Contrato.objects.select_related("cliente", "template")
        .all()
        .order_by("-criado_em")
    )
    serializer_class = None

    def get_permissions(self):
        # Modelo Contrato legado em cadastro (template-based JSON array).
        # Mapeia para contratos.* — mesmas capacidades do app contracts.
        return [HasCapability.for_action(self.action, {
            "list": "contratos.visualizar",
            "retrieve": "contratos.visualizar",
            "create": "contratos.criar",
            "update": "contratos.editar",
            "partial_update": "contratos.editar",
            "destroy": "contratos.deletar",
        })]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["cliente", "template"]
    search_fields = ["cliente__nome_completo", "template__name"]
    ordering_fields = ["criado_em", "atualizado_em", "cliente__nome_completo"]

    def get_serializer_class(self):
        from .serializers import ContratoSerializer
        return ContratoSerializer

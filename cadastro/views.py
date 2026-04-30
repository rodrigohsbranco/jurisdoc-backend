# cadastro/views.py
import os

from django.conf import settings
from django.core.files.storage import default_storage

from rest_framework import viewsets, permissions, filters, decorators, response, status
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend

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
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = None  # setado no get_serializer_class
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
    permission_classes = [permissions.IsAuthenticated]
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

    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DescricaoBancoFilter
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
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = None  # setado no get_serializer_class

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
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = None
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["banco_nome", "banco_codigo", "cidade", "estado"]
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
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = None
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["cliente", "template"]
    search_fields = ["cliente__nome_completo", "template__name"]
    ordering_fields = ["criado_em", "atualizado_em", "cliente__nome_completo"]

    def get_serializer_class(self):
        from .serializers import ContratoSerializer
        return ContratoSerializer

# petitions/views.py
from __future__ import annotations

from pathlib import Path
from io import BytesIO

from django.utils.encoding import iri_to_uri
from django.http import HttpResponse

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from common.jinja_env import build_env

from .models import Petition
from .serializers import PetitionSerializer

# Template (arquivo .docx) vem do app templates_app
from templates_app.models import Template as DocTemplate
from templates_app.utils_jinja import extract_jinja_fields, detect_angle_brackets

# Import para buscar a descrição ativa do banco
from cadastro.models import DescricaoBanco

try:
    from docxtpl import DocxTemplate
except Exception:
    DocxTemplate = None


class PetitionViewSet(viewsets.ModelViewSet):
    """
    CRUD de Petitions + renderização do documento final (.docx) a partir do Template vinculado.

    Endpoints:
      - GET    /api/petitions/
      - POST   /api/petitions/
      - GET    /api/petitions/{id}/
      - PATCH  /api/petitions/{id}/
      - DELETE /api/petitions/{id}/
      - POST   /api/petitions/{id}/render/
    """

    queryset = Petition.objects.all().order_by("-created_at")
    serializer_class = PetitionSerializer
    permission_classes = [permissions.IsAuthenticated]

    # -------------------------------------------------------
    # Helpers
    # -------------------------------------------------------

    def _get_template_file_path(self, petition: Petition) -> Path:
        """Obtém o caminho do arquivo .docx do Template vinculado à Petition."""
        if isinstance(petition.template, DocTemplate):
            tpl_obj = petition.template
        else:
            tpl_obj = DocTemplate.objects.get(pk=petition.template_id)
        return Path(tpl_obj.file.path)

    def _validate_context_against_template(self, file_path: Path, context: dict) -> dict:
        """Valida o 'context' da petition com base nos campos detectados no template (.docx)."""
        syntax, fields = extract_jinja_fields(file_path)
        required = [f["name"] for f in fields] if fields else []
        provided = set(context.keys()) if isinstance(context, dict) else set()
        missing = [f for f in required if f not in provided]
        has_angle = detect_angle_brackets(file_path)

        return {
            "syntax": syntax,
            "required": required,
            "missing": missing,
            "has_angle": has_angle,
        }

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    # -------------------------------------------------------
    # Banco: resolução da descrição ativa
    # -------------------------------------------------------

    def _normalize_bank_name(self, name: str) -> str:
        """Remove sufixos como ' (104)' e espaços extras do nome do banco."""
        import re
        name = (name or "").strip()
        name = re.sub(r"\s*\(\d{1,6}\)\s*$", "", name)
        return name

    def _get_banco_descricao_ativa(self, conta) -> dict | None:
        """
        Retorna um dicionário com os dados da descrição ativa do banco
        (nome_banco, cnpj, endereco_banco), usando o registro ativo
        cadastrado em DescricaoBanco.
        """
        if not conta:
            return None

        banco_codigo = (getattr(conta, "banco_codigo", None) or "").strip()
        banco_nome = (getattr(conta, "banco_nome", None) or "").strip()

        qs = DescricaoBanco.objects.filter(is_ativa=True)
        if banco_codigo:
            qs = qs.filter(banco_id=banco_codigo)
        elif banco_nome:
            qs = qs.filter(banco_nome=self._normalize_bank_name(banco_nome))

        obj = qs.order_by("-atualizado_em").first()
        if not obj:
            return None

        return {
            # usa a descrição personalizada se houver, senão o nome de banco
            "nome_banco": (obj.nome_banco or obj.banco_nome or banco_nome or "").strip(),
            "cnpj": (obj.cnpj or "").strip(),
            "endereco_banco": (obj.endereco or "").strip(),
        }

    def _format_banco_string(self, desc: dict | None, fallback_nome: str = "") -> str:
        """
        Monta uma string única de descrição do banco para o campo legado {{ banco }},
        no formato: Nome — CNPJ: ... — Endereço
        """
        if not desc:
            return fallback_nome or ""

        parts: list[str] = []
        nome = (desc.get("nome_banco") or "").strip()
        cnpj = (desc.get("cnpj") or "").strip()
        endereco = (desc.get("endereco_banco") or "").strip()

        if nome:
            parts.append(nome)
        if cnpj:
            parts.append(f"CNPJ: {cnpj}")
        if endereco:
            parts.append(endereco)

        return " — ".join(parts) or fallback_nome or ""

    # -------------------------------------------------------
    # Ações
    # -------------------------------------------------------

    @action(detail=True, methods=["post"])
    def render(self, request, pk=None):
        """Gera e retorna o .docx da Petition {id}, usando o Template vinculado e o 'context' salvo."""
        if DocxTemplate is None:
            return Response(
                {"detail": "Dependência 'docxtpl' não instalada."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        petition = self.get_object()

        base_ctx = petition.context or {}
        override = request.data.get("context_override") or {}
        if not isinstance(base_ctx, dict) or not isinstance(override, dict):
            return Response({"detail": "Contexto inválido."}, status=status.HTTP_400_BAD_REQUEST)
        context = {**base_ctx, **override}

        # ---------------------------------------------------
        # Preenche automaticamente dados bancários do cliente
        # ---------------------------------------------------
        if petition.cliente:
            conta_principal = petition.cliente.contas.filter(is_principal=True).first()
            desc_ativa = self._get_banco_descricao_ativa(conta_principal)

            # Compatibilidade antiga: campo {{ banco }} (string única)
            if not context.get("banco"):
                fallback_nome = getattr(conta_principal, "banco_nome", "") or ""
                context["banco"] = self._format_banco_string(desc_ativa, fallback_nome)

            # Novo formato: variáveis planas
            if desc_ativa:
                def is_empty(v):
                    return v is None or (isinstance(v, str) and not v.strip())

                # Sempre sobrescreve se estiver vazio ou ausente
                if is_empty(context.get("nome_banco")):
                    context["nome_banco"] = desc_ativa.get("nome_banco", "")
                if is_empty(context.get("cnpj")):
                    context["cnpj"] = desc_ativa.get("cnpj", "")
                if is_empty(context.get("endereco_banco")):
                    context["endereco_banco"] = desc_ativa.get("endereco_banco", "")


        # ---------------------------------------------------
        # Integração com contratos (v2)
        # ---------------------------------------------------
        from contracts.models import Contrato

        contratos_ids = request.data.get("contratos_ids", [])
        contratos_qs = Contrato.objects.none()

        if petition.cliente:
            qs = Contrato.objects.filter(cliente=petition.cliente)
            if isinstance(contratos_ids, list) and contratos_ids:
                qs = qs.filter(id__in=contratos_ids)

            contratos_qs = qs.order_by("-data_inclusao").values(
                "id",
                "numero_contrato",
                "banco_nome",
                "situacao",
                "origem_averbacao",
                "data_inclusao",
                "data_inicio_desconto",
                "data_fim_desconto",
                "quantidade_parcelas",
                "valor_parcela",
                "iof",
                "valor_emprestado",
                "valor_liberado",
            )

        contratos = list(contratos_qs)
        context["contratos"] = contratos
        context["total_contratos"] = len(contratos)
        context["contratos_ids_utilizados"] = contratos_ids

        # ---------------------------------------------------
        # Validações e geração do documento
        # ---------------------------------------------------
        filename = (request.data.get("filename") or f"petition_{petition.pk}").strip() or f"petition_{petition.pk}"
        strict = bool(request.data.get("strict", True))

        try:
            file_path = self._get_template_file_path(petition)
        except DocTemplate.DoesNotExist:
            return Response({"detail": "Template associado não encontrado."}, status=status.HTTP_400_BAD_REQUEST)

        check = self._validate_context_against_template(file_path, context)
        if check["has_angle"]:
            return Response(
                {"detail": "O template associado usa '<< >>'. Atualize para Jinja {{ }} antes de renderizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if strict and check["missing"]:
            return Response(
                {
                    "detail": "Há variáveis ausentes no contexto.",
                    "missing": check["missing"],
                    "required": check["required"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            doc = DocxTemplate(str(file_path))
            env = build_env()
            doc.render(context, jinja_env=env)

            buf = BytesIO()
            doc.save(buf)
            buf.seek(0)

            safe_fn = iri_to_uri(f"{filename}.docx")
            resp = HttpResponse(
                buf.read(),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            resp["Content-Disposition"] = f'attachment; filename="{safe_fn}"'
            return resp

        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

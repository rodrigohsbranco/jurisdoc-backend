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

# 🔥 Import para buscar a descrição ativa
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

    # -------------- Helpers --------------

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

    # ---------- Banco: resolução de descrição ativa ----------

    def _normalize_bank_name(self, name: str) -> str:
        """
        Remove sufixos como ' (104)' e espaços extras do nome do banco
        para comparar com DescricaoBanco.banco_nome.
        """
        import re
        name = (name or "").strip()
        # remove " (XXXX)" no fim, ex.: "CAIXA ECONOMICA FEDERAL (104)" -> "CAIXA ECONOMICA FEDERAL"
        name = re.sub(r"\s*\(\d{1,6}\)\s*$", "", name)
        return name

    def _get_banco_descricao_ativa(self, conta) -> str | None:
        """
        Tenta resolver a descrição ativa do banco da conta principal priorizando:
        1) banco_id (usa conta.banco_codigo)
        2) banco_nome normalizado (sem sufixo '(104)')
        Retorna a descrição ativa se achar; caso contrário, None.
        """
        if not conta:
            return None

        # 1) Tenta por banco_id (preferível)
        banco_id = (getattr(conta, "banco_codigo", None) or "").strip()
        if banco_id:
            obj = (
                DescricaoBanco.objects
                .filter(banco_id=banco_id, is_ativa=True)
                .order_by("-atualizado_em")
                .first()
            )
            if obj:
                return obj.descricao

        # 2) Tenta por banco_nome normalizado
        banco_nome_norm = self._normalize_bank_name(getattr(conta, "banco_nome", "") or "")
        if banco_nome_norm:
            obj = (
                DescricaoBanco.objects
                .filter(banco_nome=banco_nome_norm, is_ativa=True)
                .order_by("-atualizado_em")
                .first()
            )
            if obj:
                return obj.descricao

        # nada encontrado
        return None

    # -------------- Actions --------------

    @action(detail=True, methods=["post"])
    def render(self, request, pk=None):
        """Gera e retorna o .docx da Petition {id}, usando o Template vinculado e o 'context' salvo."""
        if DocxTemplate is None:
            return Response(
                {"detail": "Dependência 'docxtpl' não instalada."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        petition = self.get_object()

        # context final = salvo na petition + (override opcional vindo no POST)
        base_ctx = petition.context or {}
        override = request.data.get("context_override") or {}
        if not isinstance(base_ctx, dict) or not isinstance(override, dict):
            return Response({"detail": "Contexto inválido."}, status=status.HTTP_400_BAD_REQUEST)
        context = {**base_ctx, **override}

        # 🔥 Preenche automaticamente o campo "banco" se não estiver no context
        if "banco" not in context and petition.cliente:
            conta_principal = petition.cliente.contas.filter(is_principal=True).first()
            desc_ativa = self._get_banco_descricao_ativa(conta_principal)
            if desc_ativa:
                context["banco"] = desc_ativa
            else:
                # fallback: mantém o comportamento antigo
                context["banco"] = getattr(conta_principal, "banco_nome", "") or ""

        filename = (request.data.get("filename") or f"petition_{petition.pk}").strip() or f"petition_{petition.pk}"
        strict = bool(request.data.get("strict", True))

        # validações de template/context
        try:
            file_path = self._get_template_file_path(petition)
        except DocTemplate.DoesNotExist:
            return Response({"detail": "Template associado não encontrado."}, status=status.HTTP_400_BAD_REQUEST)

        # Bloqueia padrão antigo
        check = self._validate_context_against_template(file_path, context)
        if check["has_angle"]:
            return Response(
                {"detail": "O template associado usa '<< >>'. Atualize para Jinja {{ }} antes de renderizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if strict and check["missing"]:
            return Response(
                {"detail": "Há variáveis ausentes no contexto.", "missing": check["missing"], "required": check["required"]},
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

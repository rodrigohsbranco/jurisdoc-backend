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

try:
    from docxtpl import DocxTemplate
except Exception:
    DocxTemplate = None

class PetitionViewSet(viewsets.ModelViewSet):
    """
    CRUD de Petitions + renderização do documento final (.docx) a partir do Template vinculado.

    Endpoints:
      - GET    /api/petitions/                 -> lista
      - POST   /api/petitions/                 -> cria (cliente, template, context)
      - GET    /api/petitions/{id}/            -> detalhe
      - PATCH  /api/petitions/{id}/            -> atualiza
      - DELETE /api/petitions/{id}/            -> remove

      - POST   /api/petitions/{id}/render/     -> gera o .docx com o context salvo

    Regras:
      - Jinja-only: templates com marcadores `<< >>` são rejeitados no /render (400).
      - StrictUndefined: se faltar variável, retornamos 400 com mensagem clara.
      - Validação de contexto: comparamos os campos exigidos pelo template (simples) com as chaves do context.
    """
    queryset = Petition.objects.all().order_by("-created_at")
    serializer_class = PetitionSerializer
    permission_classes = [permissions.IsAuthenticated]

    # -------------- Helpers --------------

    def _get_template_file_path(self, petition: Petition) -> Path:
        """
        Obtém o caminho do arquivo .docx do Template vinculado à Petition.
        """
        # petition.template pode ser FK direta ou apenas o id; garantindo o objeto:
        if isinstance(petition.template, DocTemplate):
            tpl_obj = petition.template
        else:
            tpl_obj = DocTemplate.objects.get(pk=petition.template_id)
        return Path(tpl_obj.file.path)

    def _validate_context_against_template(self, file_path: Path, context: dict) -> dict:
        """
        Valida o 'context' da petition com base nos campos detectados no template (.docx).

        Retorna um dicionário com:
          {
            "syntax": "...",
            "required": [str, ...],   # campos detectados {{ }}
            "missing":  [str, ...],   # required - context.keys()
            "has_angle": bool         # se ainda existirem << >>
          }
        """
        syntax, fields = extract_jinja_fields(file_path)  # -> lista de {raw, name, type}
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

    # -------------- Actions --------------

    @action(detail=True, methods=["post"])
    def render(self, request, pk=None):
        """
        Gera e retorna o .docx da Petition {id}, usando o Template vinculado e o 'context' salvo.

        Body opcional:
          {
            "filename": "nome_base_sem_ext"   # default: petition_<id>.docx
            "context_override": { ... }       # se quiser substituir/mesclar o context salvo
            "strict": true|false              # default: true (se false, não barra 'missing')
          }
        """
        if DocxTemplate is None:
            return Response(
                {"detail": "Dependência 'docxtpl' não instalada."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        petition = self.get_object()

        # context final = salvo na petition + (override opcional vindo no POST)
        base_ctx = petition.context or {}
        override  = request.data.get("context_override") or {}
        if not isinstance(base_ctx, dict) or not isinstance(override, dict):
            return Response({"detail": "Contexto inválido."}, status=status.HTTP_400_BAD_REQUEST)
        context = {**base_ctx, **override}

        # filename opcional
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

        # Se strict: exige que todas variáveis simples detectadas estejam presentes no context
        if strict and check["missing"]:
            return Response(
                {
                    "detail": "Há variáveis ausentes no contexto.",
                    "missing": check["missing"],
                    "required": check["required"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Renderização Jinja-only com StrictUndefined
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
            # Erros de template/contexto → 400 com mensagem clara
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

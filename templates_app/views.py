from pathlib import Path
from io import BytesIO

from django.http import HttpResponse
from django.utils.encoding import iri_to_uri

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from common.jinja_env import build_env

from .models import Template
from .serializers import TemplateSerializer
from .utils_jinja import extract_jinja_fields, detect_angle_brackets, find_invalid_jinja_prints

try:
    from docxtpl import DocxTemplate
except Exception:
    DocxTemplate = None


class TemplateViewSet(viewsets.ModelViewSet):
    """
    CRUD de Templates + utilitários Jinja-only:

      - GET  /api/templates/{id}/fields/  -> detecta variáveis {{ }} no .docx
      - POST /api/templates/{id}/render/  -> renderiza .docx com contexto (Jinja estrito)

    Regras importantes:
    - Apenas sintaxe Jinja é suportada. Se o arquivo contiver tags `<< >>`,
      /render retorna 400 orientando a migração.
    - Usamos StrictUndefined: se faltar variável no context, erro explícito.
    """
    queryset = Template.objects.all().order_by("name")
    serializer_class = TemplateSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=["get"])
    def fields(self, request, pk=None):
        """
        Retorna:
        {
          "syntax": "jinja" | "jinja (mixed: angle present)" | "unknown",
          "fields": [{ "raw": "cliente.nome", "name": "cliente_nome", "type": "string" }, ...]
        }
        """
        tpl = self.get_object()
        file_path = Path(tpl.file.path)

        syntax, fields = extract_jinja_fields(file_path)
        has_angle = detect_angle_brackets(file_path)
        invalid = find_invalid_jinja_prints(file_path)

        return Response({
            "syntax": ("jinja (mixed: angle present)" if has_angle else syntax),
            "fields": fields,
            "invalid_prints": invalid,
        })

    @action(detail=True, methods=["post"])
    def render(self, request, pk=None):
        """
        Body:
        {
          "context": { ... },   # valores para {{ variaveis }}
          "filename": "Opcional" # nome base (sem .docx)
        }
        """
        if DocxTemplate is None:
            return Response(
                {"detail": "Dependência 'docxtpl' não instalada."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        tpl = self.get_object()
        file_path = Path(tpl.file.path)

        # Bloqueia padrão antigo para forçar migração
        if detect_angle_brackets(file_path):
            return Response(
                {"detail": "Este template usa '<< >>'. Atualize para Jinja {{ }} antes de renderizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        context = request.data.get("context") or {}
        filename = (request.data.get("filename") or tpl.name).strip() or "documento"

        try:
            doc = DocxTemplate(str(file_path))
            env = build_env()
            # StrictUndefined: se faltar variável, Jinja lança exceção
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
            # Erro de Jinja/docxtpl (ex.: variável ausente) → 400 com detalhe
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

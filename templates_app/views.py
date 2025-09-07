from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import HttpResponse
from django.utils.encoding import iri_to_uri
from io import BytesIO
import os

from .models import Template
from .serializers import TemplateSerializer
from . import utils

try:
    from docxtpl import DocxTemplate
except Exception:
    DocxTemplate = None


class TemplateViewSet(viewsets.ModelViewSet):
    """
    CRUD de Templates + utilitários:
      - GET    /api/templates/{id}/fields/  -> detecta campos no .docx
      - POST   /api/templates/{id}/render/  -> renderiza .docx com contexto

    Permissão: qualquer usuário autenticado.
    Suporta duas sintaxes de placeholders:
      - Jinja:  {{ campo }}, {% if campo %}, etc.
      - Ângulo: << campo livre >> (normalizado para snake_case ao renderizar)
    """
    queryset = Template.objects.all().order_by("name")
    serializer_class = TemplateSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=["get"])
    def fields(self, request, pk=None):
        """
        Retorna os campos detectados no .docx.

        Resposta:
        {
          "syntax": "jinja" | "angle" | "unknown",
          "fields": [
            { "raw": "Cidade de residência", "name": "cidade_de_residencia", "type": "string" },
            ...
          ]
        }
        """
        tpl = self.get_object()
        info = utils.extract_fields(tpl.file.path)
        return Response(info)

    @action(detail=True, methods=["post"])
    def render(self, request, pk=None):
        """
        Gera o .docx preenchido.

        Body (JSON):
        {
          "context": { ... },    # valores para os placeholders (use a chave 'name' retornada em /fields/)
          "filename": "opcional" # nome base do arquivo (sem .docx)
        }
        """
        if DocxTemplate is None:
            return Response(
                {"detail": "Dependência 'docxtpl' não instalada."},
                status=500,
            )

        tpl = self.get_object()
        info = utils.extract_fields(tpl.file.path)
        context = request.data.get("context") or {}
        filename = (request.data.get("filename") or tpl.name).strip() or "peticao"

        temp_path = None
        try:
            # Se o modelo estiver na sintaxe << ... >>, converte temporariamente para Jinja
            if info.get("syntax") == "angle":
                mapping = {f["raw"]: f["name"] for f in info.get("fields", [])}
                temp_path = utils.convert_angle_to_jinja(tpl.file.path, mapping)
                path = temp_path
            else:
                path = tpl.file.path

            doc = DocxTemplate(path)
            doc.render(context)

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

        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

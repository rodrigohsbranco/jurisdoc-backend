from pathlib import Path
from io import BytesIO

from django.http import HttpResponse
from django.utils.encoding import iri_to_uri
from django.conf import settings

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from common.jinja_env import build_env

from .models import Template
from .serializers import TemplateSerializer
from .utils_jinja import extract_jinja_fields, detect_angle_brackets, find_invalid_jinja_prints

# Import extra
from cadastro.models import Cliente, DescricaoBanco

try:
    from docxtpl import DocxTemplate, InlineImage
    from docx.shared import Mm
except Exception:
    DocxTemplate = None
    InlineImage = None


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
        if DocxTemplate is None:
            return Response(
                {"detail": "Dependência 'docxtpl' não instalada."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        tpl = self.get_object()
        file_path = Path(tpl.file.path)

        # Bloqueia padrão antigo
        if detect_angle_brackets(file_path):
            return Response(
                {"detail": "Este template usa '<< >>'. Atualize para Jinja {{ }} antes de renderizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Valida sintaxe das variáveis Jinja antes de tentar renderizar
        invalid_prints = find_invalid_jinja_prints(file_path)
        if invalid_prints:
            return Response(
                {
                    "detail": "Foram encontradas expressões Jinja inválidas no template. "
                              "Verifique a sintaxe das variáveis destacadas em 'invalid_prints'.",
                    "invalid_prints": invalid_prints,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        context = request.data.get("context") or {}
        filename = (request.data.get("filename") or tpl.name).strip() or "documento"

        # 🔥 Novo: pré-preenchimento automático se cliente_id for enviado
        cliente_id = request.data.get("cliente_id")
        if cliente_id:
            try:
                cliente = Cliente.objects.get(pk=cliente_id)
                conta_principal = cliente.contas.filter(is_principal=True).first()
                if conta_principal:
                    # tenta buscar descrição ativa
                    desc = DescricaoBanco.objects.filter(
                        banco_nome=conta_principal.banco_nome,
                        is_ativa=True
                    ).order_by("-atualizado_em").first()

                    context.setdefault("banco", desc.descricao if desc else conta_principal.banco_nome)

                    # Também podemos preencher outros campos básicos do cliente
                    context.setdefault("nome_completo", cliente.nome_completo)
                    context.setdefault("cpf", cliente.cpf)
                    context.setdefault("cidade", cliente.cidade)
            except Cliente.DoesNotExist:
                pass

        try:
            doc = DocxTemplate(str(file_path))
            env = build_env()

            # Trata imagem_do_contrato enviada no context como PATH salvo em MEDIA_ROOT.
            # Ex.: MEDIA_ROOT pode ser /media_data (Docker) → arquivos em /media_data/contratos/
            # URL esperada no JSON: "/media/contratos/nome_da_imagem.png"
            img_key = "imagem_do_contrato"
            img_val = context.get(img_key)

            if InlineImage is not None and isinstance(img_val, str) and img_val.strip():
                raw_path = img_val.strip()

                # Remove prefixos "/media/" ou "media/" se existirem
                if raw_path.startswith("/media/"):
                    raw_path = raw_path[len("/media/") :]
                elif raw_path.startswith("media/"):
                    raw_path = raw_path[len("media/") :]

                # Caminho absoluto em MEDIA_ROOT
                full_path = Path(settings.MEDIA_ROOT) / raw_path

                if full_path.exists():
                    context[img_key] = InlineImage(
                        doc,
                        str(full_path),
                        width=Mm(80),  # ajuste do tamanho da imagem no documento
                    )

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
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

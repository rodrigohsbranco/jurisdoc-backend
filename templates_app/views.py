from pathlib import Path
from io import BytesIO

from django.http import HttpResponse
from django.utils.encoding import iri_to_uri
from django.conf import settings

from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from common.jinja_env import build_env

from .models import Template
from .serializers import TemplateSerializer
from .utils_jinja import analyze_jinja_docx

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
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "active"]
    ordering = ["name"]

    def perform_update(self, serializer):
        instance = serializer.instance
        # Se um novo arquivo foi enviado, exclui o anterior do disco
        if 'file' in serializer.validated_data and instance.file:
            old_file = instance.file
            if old_file.name and old_file.storage.exists(old_file.name):
                old_file.storage.delete(old_file.name)
        serializer.save()

    def perform_destroy(self, instance):
        # Exclui o arquivo do disco ao deletar o template
        if instance.file and instance.file.name:
            if instance.file.storage.exists(instance.file.name):
                instance.file.storage.delete(instance.file.name)
        instance.delete()

    @action(detail=False, methods=["post"])
    def compose(self, request):
        """Combina múltiplos .docx em um único documento com quebra de página entre cada."""
        files = request.FILES.getlist("files")
        if not files or len(files) < 2:
            return Response(
                {"detail": "Envie pelo menos 2 arquivos .docx."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from docx import Document
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
            import copy

            master = Document(files[0])
            master_body = master.element.body

            for f in files[1:]:
                # Adiciona quebra de página
                page_break_para = OxmlElement('w:p')
                run_elem = OxmlElement('w:r')
                br = OxmlElement('w:br')
                br.set(qn('w:type'), 'page')
                run_elem.append(br)
                page_break_para.append(run_elem)
                master_body.append(page_break_para)

                # Copia TODOS os elementos do body (parágrafos + tabelas) na ordem original
                doc = Document(f)
                for child in doc.element.body:
                    tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if tag in ('p', 'tbl'):
                        master_body.append(copy.deepcopy(child))

            buf = BytesIO()
            master.save(buf)
            buf.seek(0)

            response = HttpResponse(
                buf.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            response["Content-Disposition"] = 'attachment; filename="composed.docx"'
            return response
        except Exception as e:
            return Response(
                {"detail": f"Erro ao compor documentos: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"])
    def fields(self, request, pk=None):
        tpl = self.get_object()
        file_path = Path(tpl.file.path)

        if not file_path.exists():
            return Response(
                {"detail": "Arquivo do template não encontrado no servidor. Faça o upload novamente."},
                status=status.HTTP_404_NOT_FOUND,
            )

        info = analyze_jinja_docx(file_path)

        return Response({
            "syntax": ("jinja (mixed: angle present)" if info["has_angle"] else info["syntax"]),
            "fields": info["fields"],
            "invalid_prints": info["invalid_prints"],
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

        if not file_path.exists():
            return Response(
                {"detail": "Arquivo do template não encontrado no servidor. Faça o upload novamente."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Bloqueia padrão antigo
        info = analyze_jinja_docx(file_path)
        if info["has_angle"]:
            return Response(
                {"detail": "Este template usa '<< >>'. Atualize para Jinja {{ }} antes de renderizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Valida sintaxe das variáveis Jinja antes de tentar renderizar
        invalid_prints = info["invalid_prints"]
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

                    if desc:
                        banco_parts = [p for p in [desc.nome_banco or desc.banco_nome, desc.cnpj, desc.endereco] if p]
                        context.setdefault("banco", " - ".join(banco_parts) if banco_parts else conta_principal.banco_nome)
                    else:
                        context.setdefault("banco", conta_principal.banco_nome)

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

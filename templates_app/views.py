import subprocess
import tempfile
from pathlib import Path
from io import BytesIO

from django.http import HttpResponse
from django.utils.encoding import iri_to_uri
from django.conf import settings

from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from permissoes.permissions import HasCapability

from common.jinja_env import build_env
from common.bold_markers import aplicar_marcadores_negrito

from .models import Template
from .serializers import TemplateSerializer
from .utils_jinja import analyze_jinja_docx
from .docx_jinja_normalizer import normalize_docx_jinja_runs
from .docx_cleaner import strip_blank_pages
from .docx_style_flattener import flatten_inherited_formatting
from .docx_page_numbering import (
    add_page_numbering_simple,
    add_page_numbering_conditional,
)

# Import extra
from cadastro.models import Cliente, DescricaoBanco

try:
    from docxtpl import DocxTemplate, InlineImage
    from docx.shared import Mm
except Exception:
    DocxTemplate = None
    InlineImage = None


def _truthy(v) -> bool:
    """Aceita true/'true'/'1'/1 — útil pra flags vindas de FormData (sempre string)."""
    if v is True:
        return True
    if v in (1, "1", "true", "True"):
        return True
    return False


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
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def get_permissions(self):
        return [HasCapability.for_action(self.action, {
            "list": "templates.visualizar",
            "retrieve": "templates.visualizar",
            "create": "templates.criar",
            "update": "templates.editar",
            "partial_update": "templates.editar",
            "destroy": "templates.deletar",
            "fields": "templates.visualizar",
            "download": "templates.visualizar",
            "render": "templates.renderizar",
            "render_pdf": "templates.renderizar",
            "compose": "templates.renderizar",
            "convert_to_pdf": "templates.renderizar",
            "compose_to_pdf": "templates.renderizar",
        })]
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

    def _compose_docx_files(self, files):
        from docx import Document
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        import copy

        master = Document(files[0])
        master_body = master.element.body

        # O <w:sectPr> final do body deve ser SEMPRE o último elemento
        # (define margens, colunas, refs de header/footer da seção). Inserir
        # conteúdo após ele produz OOXML inválido e o LibreOffice/Word
        # passam a ignorar spacing/indent dos parágrafos colados. Inserimos
        # tudo *antes* do sectPr final, preservando-o como rodapé da estrutura.
        final_sect_pr = master_body.find(qn('w:sectPr'))

        def add_to_master(element):
            if final_sect_pr is not None:
                final_sect_pr.addprevious(element)
            else:
                master_body.append(element)

        for f in files[1:]:
            page_break_para = OxmlElement('w:p')
            run_elem = OxmlElement('w:r')
            br = OxmlElement('w:br')
            br.set(qn('w:type'), 'page')
            run_elem.append(br)
            page_break_para.append(run_elem)
            add_to_master(page_break_para)

            doc = Document(f)
            for child in doc.element.body:
                tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if tag in ('p', 'tbl'):
                    add_to_master(copy.deepcopy(child))

        buf = BytesIO()
        master.save(buf)
        return buf.getvalue()

    def _convert_docx_bytes_to_pdf(self, docx_bytes: bytes) -> bytes:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.docx"
            input_path.write_bytes(docx_bytes)

            # UserInstallation isolado por chamada: LibreOffice trava ao rodar
            # em paralelo com o mesmo profile (~/.config/libreoffice). Cada
            # conversão precisa do seu profile próprio.
            profile_dir = Path(tmpdir) / "profile"
            profile_dir.mkdir()
            user_install = f"-env:UserInstallation=file://{profile_dir}"

            result = subprocess.run(
                [
                    "libreoffice",
                    user_install,
                    "--headless",
                    "--norestore",
                    "--nolockcheck",
                    "--nodefault",
                    "--convert-to", "pdf",
                    "--outdir", tmpdir,
                    str(input_path),
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )

            pdf_path = Path(tmpdir) / "input.pdf"
            if not pdf_path.exists():
                stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
                stdout = (result.stdout or b"").decode("utf-8", errors="replace").strip()
                detail = stderr or stdout or "saída vazia"
                raise RuntimeError(
                    f"Falha na conversão para PDF (exit={result.returncode}): {detail[:500]}"
                )

            return pdf_path.read_bytes()

    def _count_pdf_pages(self, pdf_bytes: bytes) -> int:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(pdf_bytes))
        return len(reader.pages)

    def _convert_with_conditional_page_numbering(self, docx_bytes: bytes) -> bytes:
        """
        Converte .docx para PDF aplicando 'Página X de Y' apenas quando
        houver mais de uma página. Estratégia: converte uma vez sem
        numeração; se o PDF tem 1 página, devolve direto. Se >1, injeta
        a numeração com complex fields (PAGE/NUMPAGES) e re-converte.
        """
        pdf_bytes = self._convert_docx_bytes_to_pdf(docx_bytes)
        try:
            page_count = self._count_pdf_pages(pdf_bytes)
        except Exception:
            return pdf_bytes
        if page_count <= 1:
            return pdf_bytes
        numbered = add_page_numbering_simple(docx_bytes)
        return self._convert_docx_bytes_to_pdf(numbered)

    def _merge_pdfs(self, pdf_list: list[bytes]) -> bytes:
        """Concatena PDFs já renderizados, sem re-numerar. Cada PDF preserva
        a numeração 'Página X de Y' que recebeu isoladamente."""
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        for pdf in pdf_list:
            reader = PdfReader(BytesIO(pdf))
            for page in reader.pages:
                writer.add_page(page)
        out = BytesIO()
        writer.write(out)
        return out.getvalue()

    @action(detail=False, methods=["post"])
    def compose(self, request):
        """Combina múltiplos .docx em um único documento com quebra de página entre cada."""
        files = request.FILES.getlist("files")
        if not files or len(files) < 2:
            return Response(
                {"detail": "Envie pelo menos 2 arquivos .docx."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        skip_pages = _truthy(request.data.get("skip_page_numbering"))
        try:
            docx_bytes = self._compose_docx_files(files)
            if not skip_pages:
                docx_bytes = add_page_numbering_conditional(docx_bytes)
            response = HttpResponse(
                docx_bytes,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            response["Content-Disposition"] = 'attachment; filename="composed.docx"'
            return response
        except Exception as e:
            return Response(
                {"detail": f"Erro ao compor documentos: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"], url_path="convert-to-pdf")
    def convert_to_pdf(self, request):
        """Recebe um .docx via upload e retorna PDF convertido via LibreOffice."""
        file = request.FILES.get("file")
        if not file:
            return Response(
                {"detail": "Envie um arquivo .docx no campo 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        filename = request.data.get("filename", "documento")
        skip_pages = _truthy(request.data.get("skip_page_numbering"))

        try:
            docx_bytes = b"".join(chunk for chunk in file.chunks())
            # Materializa formatação herdada de estilos antes da conversão
            docx_bytes = flatten_inherited_formatting(docx_bytes)
            if skip_pages:
                pdf_bytes = self._convert_docx_bytes_to_pdf(docx_bytes)
            else:
                pdf_bytes = self._convert_with_conditional_page_numbering(docx_bytes)
            response = HttpResponse(pdf_bytes, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
            return response
        except RuntimeError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except subprocess.TimeoutExpired:
            return Response(
                {"detail": "Conversão para PDF excedeu o tempo limite."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except FileNotFoundError:
            return Response(
                {"detail": "LibreOffice não encontrado no servidor. Instale o pacote 'libreoffice' para converter para PDF."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"], url_path="compose-to-pdf")
    def compose_to_pdf(self, request):
        """Combina múltiplos .docx na ordem enviada e retorna um único PDF."""
        files = request.FILES.getlist("files")
        if not files or len(files) < 2:
            return Response(
                {"detail": "Envie pelo menos 2 arquivos .docx."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        filename = request.data.get("filename", "documentos")

        skip_pages = _truthy(request.data.get("skip_page_numbering"))
        per_document = _truthy(request.data.get("per_document_numbering"))
        try:
            if per_document:
                # Paginação por documento: cada arquivo é numerado isoladamente
                # ('Página X de Y' relativo às próprias páginas, ou nada se for
                # 1 página) e só então os PDFs são concatenados. Assim cada doc
                # reinicia em 1, independentemente da posição no PDF final.
                pdfs = []
                for f in files:
                    content = b"".join(chunk for chunk in f.chunks())
                    content = flatten_inherited_formatting(content)
                    pdfs.append(self._convert_with_conditional_page_numbering(content))
                pdf_bytes = self._merge_pdfs(pdfs)
                response = HttpResponse(pdf_bytes, content_type="application/pdf")
                response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
                return response

            # Flatten cada arquivo antes de compor: cada entrada vira self-contained
            # (formatação direta em cada run), garantindo render correto pelo
            # LibreOffice mesmo após a perda da styles.xml original na composição.
            flattened_files = []
            for f in files:
                content = b"".join(chunk for chunk in f.chunks())
                flattened_files.append(BytesIO(flatten_inherited_formatting(content)))

            docx_bytes = self._compose_docx_files(flattened_files)
            if skip_pages:
                pdf_bytes = self._convert_docx_bytes_to_pdf(docx_bytes)
            else:
                pdf_bytes = self._convert_with_conditional_page_numbering(docx_bytes)
            response = HttpResponse(pdf_bytes, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
            return response
        except RuntimeError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except subprocess.TimeoutExpired:
            return Response(
                {"detail": "Conversão para PDF excedeu o tempo limite."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except FileNotFoundError:
            return Response(
                {"detail": "LibreOffice não encontrado no servidor. Instale o pacote 'libreoffice' para converter para PDF."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            return Response(
                {"detail": f"Erro ao compor documentos em PDF: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        tpl = self.get_object()
        file_path = Path(tpl.file.path)

        if not file_path.exists():
            return Response(
                {"detail": "Arquivo do template não encontrado no servidor."},
                status=status.HTTP_404_NOT_FOUND,
            )

        safe_fn = iri_to_uri(f"{tpl.name}.docx")
        response = HttpResponse(
            file_path.read_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response["Content-Disposition"] = f'attachment; filename="{safe_fn}"'
        return response

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

    def _build_docx_bytes(self, tpl, context, cliente_id=None):
        """
        Renderiza um Template em bytes .docx aplicando pré-validações,
        pré-preenchimento de cliente e imagem_do_contrato.
        Retorna (bytes, None) em sucesso ou (None, Response) em erro.
        """
        if DocxTemplate is None:
            return None, Response(
                {"detail": "Dependência 'docxtpl' não instalada."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        file_path = Path(tpl.file.path)
        if not file_path.exists():
            return None, Response(
                {"detail": "Arquivo do template não encontrado no servidor. Faça o upload novamente."},
                status=status.HTTP_404_NOT_FOUND,
            )

        info = analyze_jinja_docx(file_path)
        if info["has_angle"]:
            return None, Response(
                {"detail": "Este template usa '<< >>'. Atualize para Jinja {{ }} antes de renderizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invalid_prints = info["invalid_prints"]
        if invalid_prints:
            return None, Response(
                {
                    "detail": "Foram encontradas expressões Jinja inválidas no template. "
                              "Verifique a sintaxe das variáveis destacadas em 'invalid_prints'.",
                    "invalid_prints": invalid_prints,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if cliente_id:
            try:
                cliente = Cliente.objects.get(pk=cliente_id)
                conta_principal = cliente.contas.filter(is_principal=True).first()
                if conta_principal:
                    desc = DescricaoBanco.objects.filter(
                        banco_nome=conta_principal.banco_nome,
                        is_ativa=True
                    ).order_by("-atualizado_em").first()

                    if desc:
                        banco_parts = [p for p in [desc.nome_banco or desc.banco_nome, desc.cnpj, desc.endereco] if p]
                        context.setdefault("banco", " - ".join(banco_parts) if banco_parts else conta_principal.banco_nome)
                    else:
                        context.setdefault("banco", conta_principal.banco_nome)

                    nome_upper = (cliente.nome_completo or "").upper()
                    context.setdefault("nome_completo", nome_upper)
                    context.setdefault("nome_cliente", nome_upper)
                    context.setdefault("cpf", cliente.cpf)
                    context.setdefault("cidade", cliente.cidade)
            except Cliente.DoesNotExist:
                pass

        normalized_path = None
        try:
            normalized_path = normalize_docx_jinja_runs(file_path)
            doc = DocxTemplate(str(normalized_path))
            env = build_env()

            # imagem_do_contrato: caminho relativo a MEDIA_ROOT ("/media/..." ou "media/...")
            img_key = "imagem_do_contrato"
            img_val = context.get(img_key)
            if InlineImage is not None and isinstance(img_val, str) and img_val.strip():
                raw_path = img_val.strip()
                if raw_path.startswith("/media/"):
                    raw_path = raw_path[len("/media/") :]
                elif raw_path.startswith("media/"):
                    raw_path = raw_path[len("media/") :]
                full_path = Path(settings.MEDIA_ROOT) / raw_path
                if full_path.exists():
                    context[img_key] = InlineImage(doc, str(full_path), width=Mm(80))

            doc.render(context, jinja_env=env)
            aplicar_marcadores_negrito(doc.docx)

            buf = BytesIO()
            doc.save(buf)
            buf.seek(0)
            try:
                buf = strip_blank_pages(buf)
            except Exception:
                buf.seek(0)
            return buf.read(), None
        except Exception as exc:
            return None, Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        finally:
            if normalized_path is not None:
                normalized_path.unlink(missing_ok=True)

    @action(detail=True, methods=["post"])
    def render(self, request, pk=None):
        tpl = self.get_object()
        context = request.data.get("context") or {}
        filename = (request.data.get("filename") or tpl.name).strip() or "documento"
        cliente_id = request.data.get("cliente_id")

        docx_bytes, error = self._build_docx_bytes(tpl, context, cliente_id)
        if error is not None:
            return error

        if not _truthy(request.data.get("skip_page_numbering")):
            # Sempre injeta "Página X de Y" usando complex fields. Docs de
            # 1 página ficam com "Página 1 de 1" — quando isso não é desejado,
            # passar skip_page_numbering=true.
            docx_bytes = add_page_numbering_conditional(docx_bytes)

        safe_fn = iri_to_uri(f"{filename}.docx")
        resp = HttpResponse(
            docx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        resp["Content-Disposition"] = f'attachment; filename="{safe_fn}"'
        return resp

    @action(detail=True, methods=["post"], url_path="render-pdf")
    def render_pdf(self, request, pk=None):
        """Mesmo do /render/ mas converte o resultado para PDF via LibreOffice headless."""
        tpl = self.get_object()
        context = request.data.get("context") or {}
        filename = (request.data.get("filename") or tpl.name).strip() or "documento"
        cliente_id = request.data.get("cliente_id")
        skip_pages = _truthy(request.data.get("skip_page_numbering"))

        docx_bytes, error = self._build_docx_bytes(tpl, context, cliente_id)
        if error is not None:
            return error

        try:
            # Materializa formatação herdada de estilos para o LibreOffice render igual ao Word
            docx_bytes = flatten_inherited_formatting(docx_bytes)
            if skip_pages:
                pdf_bytes = self._convert_docx_bytes_to_pdf(docx_bytes)
            else:
                pdf_bytes = self._convert_with_conditional_page_numbering(docx_bytes)
        except RuntimeError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except subprocess.TimeoutExpired:
            return Response(
                {"detail": "Conversão para PDF excedeu o tempo limite."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except FileNotFoundError:
            return Response(
                {"detail": "LibreOffice não encontrado no servidor. Instale o pacote 'libreoffice' para converter para PDF."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        safe_fn = iri_to_uri(f"{filename}.pdf")
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        # inline: navegador exibe no iframe; o front força download via blob quando precisar
        resp["Content-Disposition"] = f'inline; filename="{safe_fn}"'
        return resp

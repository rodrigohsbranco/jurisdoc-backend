from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from django.test import SimpleTestCase
from docx import Document
from docxtpl import DocxTemplate

from common.jinja_env import build_env
from templates_app.docx_jinja_normalizer import normalize_docx_jinja_runs


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


class DocxJinjaNormalizerTests(SimpleTestCase):
    def test_keeps_bold_when_placeholder_is_split_across_runs(self):
        with TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "template.docx"

            doc = Document()
            p = doc.add_paragraph()
            p.add_run("{{")
            styled = p.add_run("nome")
            styled.bold = True
            p.add_run("}}")
            doc.save(src)

            normalized = normalize_docx_jinja_runs(src)

            tpl = DocxTemplate(str(normalized))
            tpl.render({"nome": "JOAO TESTE"}, jinja_env=build_env())
            buf = BytesIO()
            tpl.save(buf)
            buf.seek(0)

            with ZipFile(buf) as z:
                root = ET.fromstring(z.read("word/document.xml"))

            found = False
            for run in root.findall(".//w:r", NS):
                text = "".join(node.text or "" for node in run.findall(".//w:t", NS))
                if text != "JOAO TESTE":
                    continue
                found = True
                self.assertIsNotNone(run.find("./w:rPr/w:b", NS))
                break

            self.assertTrue(found, "Texto renderizado não encontrado no documento final.")


class LimparPontuacaoVaziaTests(SimpleTestCase):
    """Vírgulas repetidas / vírgula antes de ponto deixadas por campos vazios."""

    @staticmethod
    def _paragrafo(*runs):
        """Cria um Document com um parágrafo; cada run é str ou (str, negrito)."""
        doc = Document()
        p = doc.add_paragraph()
        for r in runs:
            texto, negrito = (r, False) if isinstance(r, str) else r
            run = p.add_run(texto)
            run.bold = negrito
        return doc, p

    def _limpar(self, doc):
        from templates_app.docx_punctuation_cleaner import limpar_pontuacao_vazia
        return limpar_pontuacao_vazia(doc)

    def test_virgulas_repetidas_no_mesmo_run(self):
        doc, p = self._paragrafo("RAIMUNDO SOARES, brasileiro, , , inscrito no CPF")
        self._limpar(doc)
        self.assertEqual(p.text, "RAIMUNDO SOARES, brasileiro, inscrito no CPF")

    def test_virgulas_divididas_entre_runs_preserva_formatacao(self):
        doc, p = self._paragrafo(
            ("RAIMUNDO SOARES", True),
            ", brasileiro, ",
            ("", True),
            ", ",
            ("", False),
            ", inscrito no CPF sob nº ",
            ("123.456.789-00", True),
        )
        self._limpar(doc)
        self.assertEqual(p.text, "RAIMUNDO SOARES, brasileiro, inscrito no CPF sob nº 123.456.789-00")
        # Nenhum run foi fundido/removido e o negrito continua onde estava.
        self.assertEqual(len(p.runs), 7)
        self.assertTrue(p.runs[0].bold)
        self.assertEqual(p.runs[0].text, "RAIMUNDO SOARES")
        self.assertTrue(p.runs[6].bold)
        self.assertEqual(p.runs[6].text, "123.456.789-00")

    def test_virgula_vazia_antes_do_ponto(self):
        doc, p = self._paragrafo("residente na Rua A, ", ("", True), ", .")
        self._limpar(doc)
        self.assertEqual(p.text, "residente na Rua A.")

    def test_texto_sem_pontuacao_vazia_nao_muda(self):
        original = "Valor de R$ 1.234,56, pago em 3 parcelas. Fim... ok, certo."
        doc, p = self._paragrafo(original)
        alterados = self._limpar(doc)
        self.assertEqual(alterados, 0)
        self.assertEqual(p.text, original)

    def test_nao_atravessa_tabulacao(self):
        doc, p = self._paragrafo("a,")
        p.runs[0].add_tab()
        p.add_run(", b")
        self._limpar(doc)
        self.assertEqual(p.text, "a,\t, b")

    def test_tabela_e_cabecalho(self):
        doc = Document()
        cel = doc.add_table(rows=1, cols=1).cell(0, 0)
        cel.paragraphs[0].add_run("brasileiro, , solteiro")
        cab = doc.sections[0].header.paragraphs[0]
        cab.add_run("Fulano, , .")
        self._limpar(doc)
        self.assertEqual(cel.paragraphs[0].text, "brasileiro, solteiro")
        self.assertEqual(cab.text, "Fulano.")

    def test_render_docxtpl_com_campos_vazios(self):
        with TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "template.docx"
            d = Document()
            d.add_paragraph(
                "CONTRATANTE: {{ nome_cliente }}, {{ nacionalidade }}, {{ estado_civil }}, "
                "{{ profissao }}, inscrito no CPF sob nº {{ cpf_cliente }}, residente na {{ endereco }}, {{ extra }}."
            )
            d.save(src)
            tpl = DocxTemplate(str(src))
            tpl.render(
                {
                    "nome_cliente": "RAIMUNDO SOARES",
                    "nacionalidade": "brasileiro",
                    "estado_civil": "",
                    "profissao": "",
                    "cpf_cliente": "123",
                    "endereco": "Rua A",
                    "extra": "",
                },
                jinja_env=build_env(),
            )
            self._limpar(tpl.docx)
            self.assertEqual(
                tpl.docx.paragraphs[0].text,
                "CONTRATANTE: RAIMUNDO SOARES, brasileiro, inscrito no CPF sob nº 123, residente na Rua A.",
            )


class VariaveisVirgulaTests(SimpleTestCase):
    """Variáveis irmãs `X_v` ("valor, " ou "") para a qualificação das partes."""

    def test_campo_cheio_ganha_virgula_e_espaco(self):
        from common.variaveis_virgula import adicionar_variaveis_virgula

        ctx = adicionar_variaveis_virgula({"nome_cliente": "  RAIMUNDO SOARES ", "rg": 12345})
        self.assertEqual(ctx["nome_cliente_v"], "RAIMUNDO SOARES, ")
        self.assertEqual(ctx["rg_v"], "12345, ")
        # original intacta
        self.assertEqual(ctx["nome_cliente"], "  RAIMUNDO SOARES ")

    def test_campo_vazio_none_ou_ausente_fica_vazio(self):
        from common.variaveis_virgula import CAMPOS_COM_VIRGULA, adicionar_variaveis_virgula

        ctx = adicionar_variaveis_virgula({"nacionalidade": "   ", "profissao": None})
        self.assertEqual(ctx["nacionalidade_v"], "")
        self.assertEqual(ctx["profissao_v"], "")
        # ausentes também existem (StrictUndefined)
        for base in CAMPOS_COM_VIRGULA:
            self.assertEqual(ctx[f"{base}_v"], "")

    def test_nao_sobrescreve_v_explicito(self):
        from common.variaveis_virgula import adicionar_variaveis_virgula

        ctx = adicionar_variaveis_virgula({"cpf": "111", "cpf_v": "CUSTOM"})
        self.assertEqual(ctx["cpf_v"], "CUSTOM")

    def test_variaveis_v_nao_sao_campos_pedidos(self):
        from templates_app.utils_jinja import _extract_from_text

        info = _extract_from_text("{{ nome_cliente_v }}{{ nacionalidade_v }}{{ inscrito }} {{ outro_v }}")
        nomes = [f["name"] for f in info["fields"]]
        self.assertEqual(nomes, ["inscrito", "outro_v"])
        self.assertEqual(info["invalid_prints"], [])

    def test_render_docxtpl_linha_contratante(self):
        from common.variaveis_virgula import adicionar_variaveis_virgula

        linha = (
            "CONTRATANTE: {{ nome_cliente_v }}{{ nacionalidade_v }}{{ estado_civil_v }}"
            "{{ profissao_v }}{{ inscrito }} no CPF sob nº {{ cpf_cliente_v }}residente e "
            "{{ domiciliado }} na {{ endereco }}. TELEFONE: {{ telefone }}."
        )
        base = {
            "nome_cliente": "RAIMUNDO SOARES",
            "inscrito": "inscrito",
            "cpf_cliente": "314.545.932-53",
            "domiciliado": "domiciliado",
            "endereco": "Rua A, 10",
            "telefone": "(91) 99999-0000",
        }
        casos = [
            (
                {"nacionalidade": "brasileiro", "estado_civil": "casado", "profissao": "lavrador"},
                "CONTRATANTE: RAIMUNDO SOARES, brasileiro, casado, lavrador, inscrito no CPF sob nº "
                "314.545.932-53, residente e domiciliado na Rua A, 10. TELEFONE: (91) 99999-0000.",
            ),
            (
                {"nacionalidade": "", "estado_civil": "", "profissao": ""},
                "CONTRATANTE: RAIMUNDO SOARES, inscrito no CPF sob nº 314.545.932-53, "
                "residente e domiciliado na Rua A, 10. TELEFONE: (91) 99999-0000.",
            ),
        ]
        for extra, esperado in casos:
            with self.subTest(extra=extra), TemporaryDirectory() as tmpdir:
                src = Path(tmpdir) / "template.docx"
                d = Document()
                d.add_paragraph(linha)
                d.save(src)
                tpl = DocxTemplate(str(src))
                tpl.render(adicionar_variaveis_virgula({**base, **extra}), jinja_env=build_env())
                self.assertEqual(tpl.docx.paragraphs[0].text, esperado)

"""
Injeta "Página X de Y" no rodapé de cada seção de um .docx.

Usa campos nativos do OOXML (PAGE e NUMPAGES) que Word e LibreOffice
calculam na hora de renderizar/converter para PDF. Não tenta calcular
o número de páginas em Python — isso depende do layout final.

Comportamento:
- Adiciona um parágrafo centralizado ao final do rodapé existente
  (mantém qualquer conteúdo prévio: logo, endereço do escritório, etc.).
- Aplica a todas as seções do documento.
- Se a seção tem "primeira página diferente" (<w:titlePg/>), adiciona
  também no rodapé da primeira página.
- Skip automático se o rodapé já tem um campo PAGE — evita duplicação
  em re-renders ou em templates que já fizeram manualmente.
- Em caso de erro, retorna os bytes originais.
"""
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _footer_has_page_field(footer) -> bool:
    """True se o rodapé já tem o padrão 'X de Y' (campo NUMPAGES presente).
    Templates com apenas PAGE simples não são considerados — ainda queremos
    adicionar o formato 'Página X de Y' que o usuário pediu."""
    xml = footer._element.xml if hasattr(footer._element, "xml") else ""
    if not xml:
        for p in footer.paragraphs:
            text = getattr(p._p, "xml", "")
            if "NUMPAGES" in text:
                return True
        return False
    return "NUMPAGES" in xml


def _make_text_run(text: str):
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    if text != text.strip():
        t.set(qn("xml:space"), "preserve")
    r.append(t)
    return r


def _make_simple_field(instr: str):
    """<w:fldSimple w:instr=" PAGE "> com run placeholder dentro."""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), f" {instr} ")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    return fld


def _append_page_paragraph(footer):
    """Adiciona ao final do rodapé um parágrafo centralizado: 'Página PAGE de NUMPAGES'."""
    p = footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_el = p._p
    p_el.append(_make_text_run("Página "))
    p_el.append(_make_simple_field("PAGE"))
    p_el.append(_make_text_run(" de "))
    p_el.append(_make_simple_field("NUMPAGES"))


def _section_has_different_first_page(section) -> bool:
    sect_pr = section._sectPr
    return sect_pr.find(qn("w:titlePg")) is not None


def _add_impl(docx_bytes: bytes) -> bytes:
    doc = Document(BytesIO(docx_bytes))

    for section in doc.sections:
        footer = section.footer
        if not _footer_has_page_field(footer):
            _append_page_paragraph(footer)

        # Quando a seção tem primeira página diferente, o footer default
        # não cobre a página 1 — precisa adicionar no first_page_footer também.
        if _section_has_different_first_page(section):
            first_footer = section.first_page_footer
            if not _footer_has_page_field(first_footer):
                _append_page_paragraph(first_footer)

    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def add_page_numbering(docx_bytes: bytes) -> bytes:
    """
    Adiciona 'Página X de Y' centralizado ao final do rodapé de cada seção.
    Em caso de erro, retorna os bytes originais para não quebrar o pipeline.
    """
    try:
        return _add_impl(docx_bytes)
    except Exception:
        return docx_bytes

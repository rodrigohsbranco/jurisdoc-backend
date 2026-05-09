"""
Injeta "Página X de Y" no rodapé de cada seção de um .docx.

Duas estratégias:

- add_page_numbering_simple(bytes): injeta um campo PAGE/NUMPAGES sempre
  visível ("Página X de Y"). Funciona em qualquer renderizador. Usado
  no caminho do PDF, depois de já termos detectado que o documento tem
  mais de uma página.

- add_page_numbering_conditional(bytes): injeta um campo IF aninhado
  que esconde a numeração em documentos de página única. Funciona
  perfeitamente no Word (que avalia fields aninhados). LibreOffice
  versões < 7.5 têm bug com fields aninhados em IF — não usar para
  o caminho do PDF.

Ambas mantêm qualquer rodapé existente (logo, endereço, etc.) — só
anexam um novo parágrafo. Em caso de erro, retornam os bytes originais
sem quebrar o pipeline.
"""
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _footer_has_page_field(footer) -> bool:
    """True se o rodapé já tem o padrão 'X de Y' (campo NUMPAGES presente)."""
    xml = footer._element.xml if hasattr(footer._element, "xml") else ""
    if not xml:
        for p in footer.paragraphs:
            text = getattr(p._p, "xml", "")
            if "NUMPAGES" in text:
                return True
        return False
    return "NUMPAGES" in xml


def _make_run_with_child(child):
    r = OxmlElement("w:r")
    r.append(child)
    return r


def _fld_char(char_type: str):
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), char_type)
    return _make_run_with_child(fc)


def _instr_text(text: str):
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = text
    return _make_run_with_child(it)


def _text_run(text: str):
    t = OxmlElement("w:t")
    t.text = text
    if not text or text != text.strip():
        t.set(qn("xml:space"), "preserve")
    return _make_run_with_child(t)


def _make_simple_field(instr: str):
    """<w:fldSimple w:instr=" PAGE "> com placeholder dentro."""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), f" {instr} ")
    fld.append(_text_run("1"))
    return fld


def _append_simple_paragraph(footer):
    """Sem condição: 'Página { PAGE } de { NUMPAGES }' alinhado à direita."""
    p = footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_el = p._p
    p_el.append(_text_run("Página "))
    p_el.append(_make_simple_field("PAGE"))
    p_el.append(_text_run(" de "))
    p_el.append(_make_simple_field("NUMPAGES"))


def _append_conditional_paragraph(footer):
    """
    Com IF aninhado:
        { IF { NUMPAGES } > 1 "Página { PAGE } de { NUMPAGES }" "" }
    Funciona em Word; LibreOffice 7.4 não avalia campos aninhados.
    """
    p = footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_el = p._p

    p_el.append(_fld_char("begin"))
    p_el.append(_instr_text("IF "))

    p_el.append(_fld_char("begin"))
    p_el.append(_instr_text("NUMPAGES"))
    p_el.append(_fld_char("end"))

    p_el.append(_instr_text(' > 1 "Página '))

    p_el.append(_fld_char("begin"))
    p_el.append(_instr_text("PAGE"))
    p_el.append(_fld_char("end"))

    p_el.append(_instr_text(" de "))

    p_el.append(_fld_char("begin"))
    p_el.append(_instr_text("NUMPAGES"))
    p_el.append(_fld_char("end"))

    p_el.append(_instr_text('" ""'))

    p_el.append(_fld_char("separate"))
    p_el.append(_text_run(""))
    p_el.append(_fld_char("end"))


def _section_has_different_first_page(section) -> bool:
    sect_pr = section._sectPr
    return sect_pr.find(qn("w:titlePg")) is not None


def _add(docx_bytes: bytes, append_fn) -> bytes:
    doc = Document(BytesIO(docx_bytes))

    for section in doc.sections:
        footer = section.footer
        if not _footer_has_page_field(footer):
            append_fn(footer)

        if _section_has_different_first_page(section):
            first_footer = section.first_page_footer
            if not _footer_has_page_field(first_footer):
                append_fn(first_footer)

    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def add_page_numbering_simple(docx_bytes: bytes) -> bytes:
    """Injeta 'Página X de Y' sempre visível. Use após detectar multi-página."""
    try:
        return _add(docx_bytes, _append_simple_paragraph)
    except Exception:
        return docx_bytes


def add_page_numbering_conditional(docx_bytes: bytes) -> bytes:
    """Injeta IF que esconde em página única. Para Word; LibreOffice < 7.5 não avalia."""
    try:
        return _add(docx_bytes, _append_conditional_paragraph)
    except Exception:
        return docx_bytes


# Mantém retrocompat com call existente que usa add_page_numbering — defaulta
# para o conditional (caso .docx que abre no Word).
add_page_numbering = add_page_numbering_conditional

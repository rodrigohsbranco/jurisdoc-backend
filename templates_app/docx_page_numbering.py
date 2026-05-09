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
    if text != text.strip() or not text:
        t.set(qn("xml:space"), "preserve")
    return _make_run_with_child(t)


def _append_page_paragraph(footer):
    """
    Adiciona ao final do rodapé um parágrafo alinhado à direita com campo IF:
        { IF { NUMPAGES } > 1 "Página { PAGE } de { NUMPAGES }" "" }
    Resultado:
        - Documentos com 2+ páginas mostram "Página X de Y" alinhado à direita.
        - Documentos com 1 página o campo avalia como string vazia (não aparece).
    """
    p = footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_el = p._p

    # BEGIN do IF externo
    p_el.append(_fld_char("begin"))
    p_el.append(_instr_text("IF "))

    # NUMPAGES aninhado na condição
    p_el.append(_fld_char("begin"))
    p_el.append(_instr_text("NUMPAGES"))
    p_el.append(_fld_char("end"))

    # Continuação da instrução do IF: > 1 "Página
    p_el.append(_instr_text(' > 1 "Página '))

    # PAGE aninhado no ramo verdadeiro
    p_el.append(_fld_char("begin"))
    p_el.append(_instr_text("PAGE"))
    p_el.append(_fld_char("end"))

    p_el.append(_instr_text(" de "))

    # NUMPAGES aninhado no ramo verdadeiro
    p_el.append(_fld_char("begin"))
    p_el.append(_instr_text("NUMPAGES"))
    p_el.append(_fld_char("end"))

    # Fecha o IF: ramo falso vazio
    p_el.append(_instr_text('" ""'))

    # Separador (entre instrução e resultado cacheado)
    p_el.append(_fld_char("separate"))

    # Resultado placeholder (Word/LibreOffice substitui na render)
    p_el.append(_text_run(""))

    # END do IF externo
    p_el.append(_fld_char("end"))


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

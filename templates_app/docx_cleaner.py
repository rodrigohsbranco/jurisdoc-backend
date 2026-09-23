from io import BytesIO

from docx import Document

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _is_empty_paragraph(p) -> bool:
    text = "".join((t.text or "") for t in p.iter(f"{W}t"))
    if text.strip():
        return False
    if p.find(f".//{W}drawing") is not None:
        return False
    if p.find(f".//{W}pict") is not None:
        return False
    return True


def _has_page_break(p) -> bool:
    for br in p.iter(f"{W}br"):
        if br.get(f"{W}type") == "page":
            return True
    return False


def _has_section_props(p) -> bool:
    return p.find(f"{W}pPr/{W}sectPr") is not None


def strip_blank_pages_document(doc) -> None:
    """Remove páginas em branco de um Document já aberto, in-place.

    Existe para evitar o ciclo salvar -> reabrir -> salvar: quem acabou de
    renderizar o documento já o tem em memória, e reserializar só para limpá-lo
    custa um round-trip de zip inteiro (~0,6s por documento, multiplicado pelo
    número de ações do kit).
    """
    body = doc.element.body
    paragraphs = body.findall(f"{W}p")

    i = len(paragraphs) - 1
    while i >= 1:
        p = paragraphs[i]
        if _has_section_props(p):
            i -= 1
            continue
        if _is_empty_paragraph(p):
            body.remove(p)
            i -= 1
            continue
        break

    paragraphs = body.findall(f"{W}p")
    prev_was_break_only = False
    for p in list(paragraphs):
        only_break = _is_empty_paragraph(p) and _has_page_break(p)
        if only_break and prev_was_break_only:
            body.remove(p)
            continue
        prev_was_break_only = only_break


def strip_blank_pages(buf: BytesIO) -> BytesIO:
    """Versão em bytes, para quem só tem o .docx serializado em mãos."""
    buf.seek(0)
    doc = Document(buf)
    strip_blank_pages_document(doc)
    out = BytesIO()
    doc.save(out)
    out.seek(0)
    return out

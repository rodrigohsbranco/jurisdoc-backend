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


def strip_blank_pages(buf: BytesIO) -> BytesIO:
    buf.seek(0)
    doc = Document(buf)
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

    out = BytesIO()
    doc.save(out)
    out.seek(0)
    return out

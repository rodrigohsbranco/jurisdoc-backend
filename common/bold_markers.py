"""Negrito por trecho via marcadores no texto renderizado.

O RichText do docxtpl injeta XML inválido quando o placeholder divide um run
(caso do {{ advogados_estado }}), fazendo o texto sumir. Aqui usamos marcadores
invisíveis (Private Use Area) delimitando os trechos que devem ficar em negrito.

Fluxo:
  1. O contexto entrega uma STRING comum com os trechos negrito envoltos pelos
     marcadores (use `marcar_negrito`). Como é string, o docxtpl insere sem
     aninhar runs.
  2. Após `doc.render(...)`, chame `aplicar_marcadores_negrito(doc.docx)`: ele
     percorre os runs, quebra cada run que contém marcadores em runs reais —
     herdando o rPr (fonte etc.) do run original e ligando/desligando <w:b/> —
     e remove os marcadores.

Uso:
    doc.render(context, jinja_env=env)
    aplicar_marcadores_negrito(doc.docx)   # doc.docx = python-docx Document
    doc.save(buf)
"""
from __future__ import annotations

from copy import deepcopy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# Caracteres da Private Use Area (não aparecem em texto real) usados como delimitadores.
NEGRITO_INICIO = chr(0xE000)
NEGRITO_FIM = chr(0xE001)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def marcar_negrito(texto: str) -> str:
    """Envolve `texto` com os marcadores de negrito."""
    return f"{NEGRITO_INICIO}{texto}{NEGRITO_FIM}"


def _segmentos(texto: str) -> list[tuple[str, bool]]:
    """Divide o texto em (trecho, negrito?) conforme os marcadores."""
    segs: list[tuple[str, bool]] = []
    negrito = False
    buf: list[str] = []
    for ch in texto:
        if ch == NEGRITO_INICIO:
            if buf:
                segs.append(("".join(buf), negrito))
                buf = []
            negrito = True
        elif ch == NEGRITO_FIM:
            if buf:
                segs.append(("".join(buf), negrito))
                buf = []
            negrito = False
        else:
            buf.append(ch)
    if buf:
        segs.append(("".join(buf), negrito))
    return segs


def _novo_run(rpr, texto: str, negrito: bool):
    r = OxmlElement("w:r")
    novo_rpr = deepcopy(rpr) if rpr is not None else OxmlElement("w:rPr")
    b = novo_rpr.find(qn("w:b"))
    if negrito:
        if b is None:
            novo_rpr.insert(0, OxmlElement("w:b"))
        else:
            b.attrib.pop(qn("w:val"), None)  # garante negrito ligado
    elif b is not None:
        novo_rpr.remove(b)
    r.append(novo_rpr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = texto
    r.append(t)
    return r


def aplicar_marcadores_negrito(document) -> None:
    """Quebra os runs com marcadores em runs reais de negrito/normal (in-place).

    `document` é um python-docx Document (ex.: DocxTemplate.docx após render).
    """
    ns = {"w": _W}
    for run in document.element.findall(".//w:r", ns):
        texto = "".join((t.text or "") for t in run.findall("w:t", ns))
        if NEGRITO_INICIO not in texto and NEGRITO_FIM not in texto:
            continue
        rpr = run.find("w:rPr", ns)
        parent = run.getparent()
        idx = parent.index(run)
        novos = [_novo_run(rpr, seg, neg) for seg, neg in _segmentos(texto) if seg]
        for i, nr in enumerate(novos):
            parent.insert(idx + i, nr)
        parent.remove(run)

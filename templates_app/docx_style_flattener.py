"""
Achata formatação herdada de estilos no .docx antes da conversão para PDF.

Word resolve a cadeia de estilos (docDefaults -> pStyle -> rStyle -> direto)
de um jeito que o LibreOffice nem sempre interpreta igual — em particular,
negrito/itálico que vivem só no estilo (Heading 1, Title, etc.) somem ao
converter.

Este módulo recebe bytes de um .docx, percorre todos os runs e força como
formatação direta na própria run as propriedades efetivas (b, i, u, caps,
smallCaps, strike). Não toca em runs que já tenham a propriedade definida
diretamente.

Uso:
    flattened = flatten_inherited_formatting(docx_bytes)
    pdf = convert(flattened)
"""
import zipfile
from io import BytesIO

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"

# Propriedades que herdam pela cadeia de estilos e que mais comumente somem
# na conversão LibreOffice
TRACKED_PROPS = ("b", "i", "u", "caps", "smallCaps", "strike")


def _is_truthy_val(val):
    """No OOXML, presença de <w:b/> significa True. <w:b w:val="0"/> ou
    val="false" significa False. Qualquer outro val é True."""
    return val != "0" and val != "false"


def _read_rpr_props(rpr):
    if rpr is None:
        return {}
    out = {}
    for prop in TRACKED_PROPS:
        el = rpr.find(f"{W}{prop}")
        if el is not None:
            out[prop] = _is_truthy_val(el.get(f"{W}val"))
    return out


def _resolve_style_chain(style_id, styles_root):
    """Percorre basedOn -> ... -> raiz, acumula props (pai sobrescrito por filho)."""
    if not style_id or styles_root is None:
        return {}
    visited = set()
    chain = []
    current_id = style_id
    while current_id and current_id not in visited:
        visited.add(current_id)
        style_el = styles_root.find(f"{W}style[@{W}styleId='{current_id}']")
        if style_el is None:
            break
        chain.append(style_el)
        based_on = style_el.find(f"{W}basedOn")
        current_id = based_on.get(f"{W}val") if based_on is not None else None

    accumulated = {}
    for style_el in reversed(chain):
        rpr = style_el.find(f"{W}rPr")
        accumulated.update(_read_rpr_props(rpr))
    return accumulated


def _doc_defaults(styles_root):
    """rPrDefault dentro de docDefaults — propriedades padrão do documento."""
    if styles_root is None:
        return {}
    doc_defaults = styles_root.find(f"{W}docDefaults")
    if doc_defaults is None:
        return {}
    rpr_default = doc_defaults.find(f"{W}rPrDefault")
    if rpr_default is None:
        return {}
    return _read_rpr_props(rpr_default.find(f"{W}rPr"))


def _ensure_rpr(r_el):
    """Garante existência do <w:rPr> como primeiro filho do run."""
    rpr = r_el.find(f"{W}rPr")
    if rpr is None:
        rpr = etree.SubElement(r_el, f"{W}rPr")
        r_el.remove(rpr)
        r_el.insert(0, rpr)
    return rpr


def _set_direct_prop(r_el, prop_name):
    rpr = _ensure_rpr(r_el)
    if rpr.find(f"{W}{prop_name}") is None:
        etree.SubElement(rpr, f"{W}{prop_name}")


def _process_xml_root(root, styles_root, defaults):
    """Para cada parágrafo no XML, calcula formatação efetiva por run e
    materializa as propriedades True que ainda não estão diretas."""
    for p in root.iter(f"{W}p"):
        ppr = p.find(f"{W}pPr")
        p_style_id = None
        p_level_rpr = None
        if ppr is not None:
            pstyle = ppr.find(f"{W}pStyle")
            if pstyle is not None:
                p_style_id = pstyle.get(f"{W}val")
            p_level_rpr = ppr.find(f"{W}rPr")

        p_style_props = _resolve_style_chain(p_style_id, styles_root)
        p_level_props = _read_rpr_props(p_level_rpr)

        for r in p.findall(f"{W}r"):
            rpr = r.find(f"{W}rPr")
            r_style_id = None
            if rpr is not None:
                rstyle = rpr.find(f"{W}rStyle")
                if rstyle is not None:
                    r_style_id = rstyle.get(f"{W}val")

            r_style_props = _resolve_style_chain(r_style_id, styles_root)
            r_direct_props = _read_rpr_props(rpr)

            # Cadeia: docDefaults < pStyle < pPr/rPr < rStyle < direto
            effective = {}
            effective.update(defaults)
            effective.update(p_style_props)
            effective.update(p_level_props)
            effective.update(r_style_props)
            effective.update(r_direct_props)

            for prop, val in effective.items():
                if val and prop not in r_direct_props:
                    _set_direct_prop(r, prop)


def _flatten_impl(docx_bytes: bytes) -> bytes:
    in_buf = BytesIO(docx_bytes)
    out_buf = BytesIO()

    with zipfile.ZipFile(in_buf, "r") as zin:
        try:
            styles_root = etree.fromstring(zin.read("word/styles.xml"))
        except (KeyError, etree.XMLSyntaxError):
            # Sem styles.xml -> nada a achatar
            return docx_bytes

        defaults = _doc_defaults(styles_root)

        target_files = {"word/document.xml"}
        for name in zin.namelist():
            if (name.startswith("word/header") or name.startswith("word/footer")) and name.endswith(".xml"):
                target_files.add(name)

        with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in zin.namelist():
                data = zin.read(name)
                if name in target_files:
                    try:
                        root = etree.fromstring(data)
                        _process_xml_root(root, styles_root, defaults)
                        data = etree.tostring(
                            root,
                            xml_declaration=True,
                            encoding="UTF-8",
                            standalone=True,
                        )
                    except etree.XMLSyntaxError:
                        pass
                zout.writestr(name, data, zipfile.ZIP_DEFLATED)

    return out_buf.getvalue()


def flatten_inherited_formatting(docx_bytes: bytes) -> bytes:
    """
    Materializa formatação herdada de estilos como formatação direta nos runs.

    Em caso de erro (estrutura inesperada, XML inválido, etc.), retorna os
    bytes originais — preferimos perder a melhoria de formatação a quebrar
    a geração do PDF.
    """
    try:
        return _flatten_impl(docx_bytes)
    except Exception:
        return docx_bytes

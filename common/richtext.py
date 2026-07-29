"""Conversão de marcações de RichText (JSON) em objetos docxtpl.RichText.

Convenção: um valor de contexto no formato

    {"__richtext__": [{"texto": "...", "negrito": true}, {"texto": "...", "negrito": false}, ...]}

é convertido em `docxtpl.RichText` na hora de renderizar. Isso permite negrito
(ou itálico/sublinhado) POR TRECHO dentro de uma única variável Jinja, sem
precisar de loop no template.

Funciona igual nos dois caminhos de render, porque a marcação viaja como JSON:
  - server-side (kits/services_documentos._render_template_to_docx);
  - endpoint /api/templates/{id}/render/ (usado pelo preview do frontend).

Basta chamar `apply_richtext(context)` logo antes de `doc.render(...)`.

Obs.: o RichText do docxtpl nem sempre herda a fonte do local onde entra. Se o
trecho sair com fonte diferente, dá pra passar "fonte"/"tamanho" em cada segmento
(add() aceita font/size) ou migrar aquele trecho para loop no template.
"""
from __future__ import annotations

try:
    from docxtpl import RichText
except ImportError:  # pragma: no cover
    RichText = None

RICHTEXT_KEY = "__richtext__"


def _segmentos_para_richtext(segmentos: list) -> "RichText":
    rt = RichText()
    for seg in segmentos:
        if not isinstance(seg, dict):
            continue
        rt.add(
            str(seg.get("texto", "")),
            # bold explícito (True/False): False sobrescreve um placeholder negrito.
            bold=bool(seg.get("negrito", False)),
            italic=bool(seg.get("italico", False)),
            underline=bool(seg.get("sublinhado", False)) or None,
            font=seg.get("fonte") or None,
            size=seg.get("tamanho") or None,
        )
    return rt


def apply_richtext(value):
    """Percorre o contexto e troca marcações __richtext__ por RichText.

    Retorna uma nova estrutura (não muta a original). Valores comuns (str, int,
    objetos como InlineImage) passam inalterados.
    """
    if RichText is None:
        return value
    if isinstance(value, dict):
        seg = value.get(RICHTEXT_KEY)
        if isinstance(seg, list):
            return _segmentos_para_richtext(seg)
        return {k: apply_richtext(v) for k, v in value.items()}
    if isinstance(value, list):
        return [apply_richtext(v) for v in value]
    return value

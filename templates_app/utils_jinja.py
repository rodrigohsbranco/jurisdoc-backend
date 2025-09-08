# templates_app/utils_jinja.py
# Utilitários para extrair variáveis Jinja de arquivos .docx
# e detectar marcadores antigos (<< >>).
#
# Estratégia:
# - Lê os XMLs internos do .docx (document, headers, footers, notes).
# - Concatena o conteúdo e remove as tags XML, colando os <w:t>.
# - Aplica regex sobre o TEXTO PLANO para capturar {{ variaveis }}.
# - Mantém um detector simples de << ... >> para orientar a migração.

from __future__ import annotations

import re
from pathlib import Path
from zipfile import ZipFile
from typing import List, Tuple, Dict

# {{ variavel }} ou {{ cliente.nome }}
JINJA_VAR_RE   = re.compile(r"{{\s*([a-zA-Z_][\w\.]*)\s*}}")
# blocos de controle Jinja (apenas para diagnóstico de sintaxe)
JINJA_BLOCK_RE = re.compile(r"{%\s*(if|for|elif|endif|endfor)\b.*?%}")
# << variavel >>  (legado)
ANGLE_TAG_RE   = re.compile(r"<<\s*([^<>]+?)\s*>>")


def _xml_to_plain(xml: str) -> str:
    """
    Remove tags <...> e cola os textos. Isso evita que quebras em <w:t>
    'quebrem' sequências como '{{ nome }}' em múltiplos runs.
    """
    # Junta runs adjacentes de texto do Word para evitar separação de tokens
    xml = re.sub(r"</w:t>\s*<w:t[^>]*>", "", xml, flags=re.IGNORECASE)
    # Remove quaisquer tags XML
    xml = re.sub(r"<[^>]+>", "", xml)
    # Normaliza espaços
    xml = re.sub(r"\s+", " ", xml)
    return xml


def _read_xml_from_docx(docx_path: Path) -> str:
    """
    Lê as partes relevantes do .docx e devolve um único texto plano.
    Considera document.xml, headers, footers, notas.
    """
    with ZipFile(docx_path) as z:
        parts: List[str] = []
        for name in z.namelist():
            if not (name.startswith("word/") and name.endswith(".xml")):
                continue
            if any(
                name.endswith(x) for x in (
                    "document.xml",
                    "header1.xml", "header2.xml", "header3.xml",
                    "footer1.xml", "footer2.xml", "footer3.xml",
                    "footnotes.xml", "endnotes.xml",
                )
            ):
                raw = z.read(name).decode("utf-8", errors="ignore")
                parts.append(_xml_to_plain(raw))
        return "\n".join(parts)


def _snake_case(s: str) -> str:
    """
    Converte 'Cliente Nome' ou 'cliente.nome' em 'cliente_nome'.
    """
    s = s.strip()
    s = s.replace(".", "_")
    s = re.sub(r"[^\w]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_{2,}", "_", s)
    return s.strip("_").lower()


def extract_jinja_fields(docx_path: Path) -> Tuple[str, List[Dict[str, str]]]:
    """
    Extrai variáveis Jinja do .docx.

    Retorna:
      syntax: "jinja" | "unknown"
      fields: [{ raw, name, type }]
    """
    txt = _read_xml_from_docx(Path(docx_path))
    vars_ = sorted({m.group(1) for m in JINJA_VAR_RE.finditer(txt)})

    fields = [
        {"raw": v, "name": _snake_case(v), "type": "string"}
        for v in vars_
    ]

    syntax = "jinja" if fields or JINJA_BLOCK_RE.search(txt) else "unknown"
    return syntax, fields


def detect_angle_brackets(docx_path: Path) -> bool:
    """
    True se o documento contiver marcadores antigos no formato << ... >>.
    """
    txt = _read_xml_from_docx(Path(docx_path))
    return bool(ANGLE_TAG_RE.search(txt))

# Detecta {{ ... }} com sintaxe inválida (nomes com espaços, filtros mal formados etc.)
PRINT_ANY_RE = re.compile(r"{{\s*(.*?)\s*}}")
# var(.var)*  |  com filtros:  foo | bar | baz(arg)
_ALLOWED_EXPR_RE = re.compile(
    r"^[A-Za-z_][\w\.]*"                  # var ou var.aninhada
    r"(?:\s*\|\s*[A-Za-z_]\w*(?:\([^\)]*\))?)*$"  # filtros encadeados opcionais
)

def find_invalid_jinja_prints(docx_path: Path):
    txt = _read_xml_from_docx(Path(docx_path))
    bad = []
    for m in PRINT_ANY_RE.finditer(txt):
        inner = m.group(1).strip()
        if not _ALLOWED_EXPR_RE.match(inner):
            bad.append(inner)
    return bad

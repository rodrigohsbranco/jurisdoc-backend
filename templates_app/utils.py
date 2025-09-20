import os
import re
import zipfile
import tempfile
import unicodedata
from typing import List, Set, Dict, Any

# --- Regex para placeholders ---
# Jinja (docxtpl)
PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z_][\w\.\-]*)[^}]*}}")
TAG_RE         = re.compile(r"{%\s*(if|for)\s+([a-zA-Z_][\w\.\-]*)")
# Sintaxe "ângulo": << ... >>
ANGLE_RE       = re.compile(r"<<\s*([^<>]+?)\s*>>")


def _iter_xml_strings(docx_path: str):
    """Itera pelos XMLs relevantes dentro do .docx (documento + headers/footers),
    decodificando como UTF-8 (ignorando erros).
    """
    with zipfile.ZipFile(docx_path) as z:
        for name in z.namelist():
            if not (name.startswith("word/") and name.endswith(".xml")):
                continue
            if not (
                name == "word/document.xml"
                or name.startswith("word/header")
                or name.startswith("word/footer")
            ):
                continue
            try:
                xml_bytes = z.read(name)
                yield xml_bytes.decode("utf-8", errors="ignore")
            except KeyError:
                continue


def slugify_placeholder(s: str) -> str:
    """Normaliza nomes livres (com espaços/acentos/barras) para snake_case seguro.
    Ex.: 'Cidade de residência' -> 'cidade_de_residencia'
    """
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "campo"


def extract_placeholders(docx_path: str) -> List[str]:
    """Retrocompatibilidade: extrai apenas placeholders Jinja ({{ var }} e {% if var %}).
    """
    names: Set[str] = set()
    for xml in _iter_xml_strings(docx_path):
        for m in PLACEHOLDER_RE.finditer(xml):
            names.add(m.group(1))
        for m in TAG_RE.finditer(xml):
            names.add(m.group(2))
    cleaned = []
    for n in names:
        base = n.split("|", 1)[0]
        cleaned.append(base.strip())
    return sorted(set(cleaned))


def extract_fields(docx_path: str) -> Dict[str, Any]:
    """Detecção "dual":
      - Se houver placeholders Jinja -> syntax='jinja'
      - Caso contrário, procurar tokens << ... >> -> syntax='angle'
      - Se nada encontrado -> syntax='unknown'
    """
    names_jinja: Set[str] = set()
    names_angle: Set[str] = set()

    for xml in _iter_xml_strings(docx_path):
        names_jinja.update(m.group(1) for m in PLACEHOLDER_RE.finditer(xml))
        names_jinja.update(m.group(2) for m in TAG_RE.finditer(xml))
        for m in ANGLE_RE.finditer(xml):
            raw = m.group(1).split("|", 1)[0].strip()
            if raw:
                names_angle.add(raw)

    if names_jinja:
        fields = []
        for n in sorted(set(x.split("|", 1)[0].strip() for x in names_jinja)):
            fields.append({"raw": n, "name": n, "type": guess_field_type(n)})
        return {"syntax": "jinja", "fields": fields}

    if names_angle:
        fields = []
        for raw in sorted(names_angle):
            safe = slugify_placeholder(raw)
            fields.append({"raw": raw, "name": safe, "type": guess_field_type(safe)})
        return {"syntax": "angle", "fields": fields}

    return {"syntax": "unknown", "fields": []}


def convert_angle_to_jinja(docx_path: str, mapping: Dict[str, str]) -> str:
    """Converte tokens << raw >> em {{ safe }} usando 'mapping' (raw->safe).
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
    tmp.close()

    with zipfile.ZipFile(docx_path) as zin, zipfile.ZipFile(tmp.name, "w") as zout:
        for name in zin.namelist():
            data = zin.read(name)
            if name.startswith("word/") and name.endswith(".xml"):
                xml = data.decode("utf-8", errors="ignore")

                def repl(m: re.Match) -> str:
                    raw = m.group(1).split("|", 1)[0].strip()
                    safe = mapping.get(raw) or slugify_placeholder(raw)
                    return "{{ " + safe + " }}"

                xml = ANGLE_RE.sub(repl, xml)
                data = xml.encode("utf-8")

            zout.writestr(name, data)

    return tmp.name


def guess_field_type(name: str) -> str:
    """Heurística simples para sugerir tipos de campo a partir do nome.
    Inclui suporte para 'banco' -> string (preenchido com descrição ativa).
    """
    n = (name or "").lower()
    if any(k in n for k in ["valor", "quantia", "preco", "preço", "montante"]):
        return "currency"
    if any(k in n for k in ["data", "competencia"]):
        return "date"
    if "cpf" in n:
        return "cpf"
    if "cnpj" in n:
        return "cnpj"
    if "cep" in n:
        return "cep"
    if any(k in n for k in ["telefone", "celular", "fone"]):
        return "phone"
    if n.startswith("is_") or n.startswith("se") or n.endswith("_bool"):
        return "bool"
    if "email" in n:
        return "email"
    if any(k in n for k in ["qtd", "quantidade", "parcelas"]):
        return "int"
    # fallback
    return "string"

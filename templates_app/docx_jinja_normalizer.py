import re
import tempfile
from pathlib import Path
from zipfile import ZipFile

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
TEXT_TAG = f"{W}t"
RUN_TAG = f"{W}r"
RUN_PROPS_TAG = f"{W}rPr"
PARAGRAPH_TAG = f"{W}p"

TOKEN_RE = re.compile(r"{{.*?}}|{#.*?#}|{%.*?%}|<<.*?>>", re.DOTALL)
XML_PART_RE = re.compile(r"word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml$")


def normalize_docx_jinja_runs(docx_path: str | Path) -> Path:
    """
    Reescreve partes XML do .docx para consolidar tokens Jinja quebrados em
    múltiplos runs do Word. Isso reduz perda de formatação ao renderizar com
    docxtpl quando um placeholder foi editado com estilos mistos no Word.
    """
    src = Path(docx_path)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
    tmp.close()
    out_path = Path(tmp.name)

    with ZipFile(src) as zin, ZipFile(out_path, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if XML_PART_RE.match(info.filename):
                data = _normalize_xml_part(data)
            zout.writestr(info, data)

    return out_path


def _normalize_xml_part(xml_bytes: bytes) -> bytes:
    root = etree.fromstring(xml_bytes)
    for paragraph in root.iter(PARAGRAPH_TAG):
        _normalize_paragraph(paragraph)
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def _normalize_paragraph(paragraph: etree._Element) -> None:
    runs = [child for child in paragraph if child.tag == RUN_TAG]
    if not runs:
        return

    texts = [_run_text(run) for run in runs]
    full_text = "".join(texts)
    if not full_text or not TOKEN_RE.search(full_text):
        return

    offsets = []
    pos = 0
    for text in texts:
        start = pos
        pos += len(text)
        offsets.append((start, pos))

    for match in reversed([*TOKEN_RE.finditer(full_text)]):
        token_text = match.group(0)
        token_start, token_end = match.span()
        involved = [
            idx for idx, (start, end) in enumerate(offsets)
            if texts[idx] and start < token_end and end > token_start
        ]
        if len(involved) <= 1:
            continue

        keep_idx = _pick_keep_run(runs, texts, offsets, involved, token_start, token_end)
        for idx in involved:
            start, end = offsets[idx]
            overlap_start = max(start, token_start) - start
            overlap_end = min(end, token_end) - start
            replacement = token_text if idx == keep_idx else ""
            texts[idx] = texts[idx][:overlap_start] + replacement + texts[idx][overlap_end:]

    for run, text in zip(runs, texts):
        _set_run_text(run, text)

    for run in list(paragraph):
        if run.tag == RUN_TAG and _run_is_empty(run):
            paragraph.remove(run)


def _pick_keep_run(runs, texts, offsets, involved, token_start: int, token_end: int) -> int:
    def score(idx: int) -> tuple[int, int, int]:
        start, end = offsets[idx]
        overlap = texts[idx][max(start, token_start) - start:min(end, token_end) - start]
        meaningful = len(re.sub(r"[{}\s%#<>]+", "", overlap))
        has_props = 1 if runs[idx].find(RUN_PROPS_TAG) is not None else 0
        return (meaningful, has_props, len(overlap))

    return max(involved, key=score)


def _run_text(run) -> str:
    return "".join(node.text or "" for node in run.iter(TEXT_TAG))


def _set_run_text(run, text: str) -> None:
    text_nodes = [node for node in run.iter(TEXT_TAG)]
    if not text_nodes:
        if not text:
            return
        text_node = etree.Element(TEXT_TAG)
        text_node.text = text
        if text.startswith(" ") or text.endswith(" "):
            text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        insert_at = 1 if len(run) and run[0].tag == RUN_PROPS_TAG else 0
        run.insert(insert_at, text_node)
        return

    first = text_nodes[0]
    first.text = text
    if text.startswith(" ") or text.endswith(" "):
        first.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    elif "{http://www.w3.org/XML/1998/namespace}space" in first.attrib:
        del first.attrib["{http://www.w3.org/XML/1998/namespace}space"]

    for extra in text_nodes[1:]:
        parent = extra.getparent()
        if parent is not None:
            parent.remove(extra)


def _run_is_empty(run) -> bool:
    if _run_text(run):
        return False

    for child in run:
        if child.tag == RUN_PROPS_TAG:
            continue
        return False
    return True

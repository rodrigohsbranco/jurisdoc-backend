"""Memoização das transformações que dependem apenas do arquivo do template.

`normalize_docx_jinja_runs` e `analyze_jinja_docx` releem e reparseiam o .docx
inteiro a cada chamada. Num kit com N ações o mesmo template é renderizado N
vezes (uma por ação), e esse trabalho idêntico era refeito N vezes — com 120
procurações são 120 descompactações + parses de lxml do mesmo arquivo.

A chave inclui mtime e tamanho: quando o arquivo do template é substituído,
a entrada antiga simplesmente deixa de ser encontrada — não há invalidação
manual a fazer no fluxo de upload.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from typing import Any

from .docx_jinja_normalizer import normalize_docx_jinja_runs
from .utils_jinja import analyze_jinja_docx

# Poucos templates ficam quentes de cada vez (os do kit em edição); o teto
# existe só para o processo não acumular versões antigas indefinidamente.
_MAX_ENTRIES = 32

_lock = threading.Lock()
_normalized: "OrderedDict[tuple, bytes]" = OrderedDict()
_analyses: "OrderedDict[tuple, dict]" = OrderedDict()


def _cache_key(path: Path) -> tuple:
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _get(store: OrderedDict, key: tuple) -> Any:
    with _lock:
        if key not in store:
            return None
        store.move_to_end(key)
        return store[key]


def _put(store: OrderedDict, key: tuple, value: Any) -> None:
    with _lock:
        store[key] = value
        store.move_to_end(key)
        while len(store) > _MAX_ENTRIES:
            store.popitem(last=False)


def normalized_docx_bytes(docx_path: str | Path) -> bytes:
    """Bytes do .docx com os tokens Jinja consolidados, memoizados por arquivo."""
    path = Path(docx_path)
    key = _cache_key(path)

    cached = _get(_normalized, key)
    if cached is not None:
        return cached

    tmp_path = normalize_docx_jinja_runs(path)
    try:
        data = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    _put(_normalized, key, data)
    return data


def normalized_docx_stream(docx_path: str | Path) -> BytesIO:
    """Stream novo sobre os bytes normalizados — pronto para o DocxTemplate.

    Cada chamada devolve um BytesIO próprio: o python-docx consome o stream
    na leitura, então compartilhá-lo entre renders quebraria o segundo.
    """
    return BytesIO(normalized_docx_bytes(docx_path))


def analyze_jinja_docx_cached(docx_path: str | Path) -> dict:
    """Idem `analyze_jinja_docx`, memoizado por arquivo."""
    path = Path(docx_path)
    key = _cache_key(path)

    cached = _get(_analyses, key)
    if cached is not None:
        return cached

    info = analyze_jinja_docx(path)
    _put(_analyses, key, info)
    return info

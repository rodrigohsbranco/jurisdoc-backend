"""Limpeza de pontuação "vazia" deixada por placeholders sem valor.

Linhas de qualificação como
    "{{ nome }}, {{ nacionalidade }}, {{ estado_civil }}, {{ profissao }}, inscrito..."
saem com vírgulas repetidas quando algum campo vem vazio:
    "RAIMUNDO SOARES, brasileiro, , , inscrito..."
Aqui, depois do render, corrigimos por parágrafo:
  1. vírgulas repetidas separadas só por espaços  -> uma vírgula só
     ("brasileiro, , , inscrito" -> "brasileiro, inscrito");
  2. vírgula vazia antes de ponto final           -> só o ponto
     ("advogado, ." -> "advogado.").

O texto de um parágrafo fica espalhado em vários <w:r>/<w:t> (com formatações
diferentes — o negrito por marcadores, por exemplo, cria runs extras). Por isso
concatenamos o texto dos <w:t> do parágrafo guardando de qual nó veio cada
caractere, calculamos as faixas a remover no texto concatenado e apagamos os
caracteres em cada <w:t> de origem. Nenhum run é criado, fundido ou removido:
o rPr de cada run fica intacto.

<w:tab>, <w:br>, <w:cr> e desenhos entram no texto como uma "barreira" (caractere
que não é espaço), então a limpeza nunca atravessa uma tabulação ou quebra de linha.

Uso:
    doc.render(context, jinja_env=env)
    aplicar_marcadores_negrito(doc.docx)
    limpar_pontuacao_vazia(doc.docx)   # doc.docx = python-docx Document
"""
from __future__ import annotations

import re

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_P = f"{_W}p"
_R = f"{_W}r"
_T = f"{_W}t"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# Elementos de run que separam visualmente o texto: viram barreira.
_BARREIRAS = {f"{_W}tab", f"{_W}br", f"{_W}cr", f"{_W}drawing", f"{_W}pict", f"{_W}sym"}
_BARREIRA = "￿"  # não é espaço (\s), então nenhum padrão casa através dela

# ", , ,  " -> mantém a primeira vírgula e um único espaço depois dela.
_RE_VIRGULAS_REPETIDAS = re.compile(r",(?:\s*,)+(\s*)")
# " , ." -> "."
_RE_VIRGULA_ANTES_PONTO = re.compile(r"\s*,\s*\.")

_RELS_CABECALHO_RODAPE = ("/header", "/footer")


def _nos_do_paragrafo(p) -> list:
    """Retorna, em ordem, os <w:t> e barreiras que pertencem diretamente a `p`.

    Exclui parágrafos aninhados (caixas de texto dentro de um run), que são
    tratados separadamente quando o loop chegar neles.
    """
    nos = []
    for el in p.iter(_T, *_BARREIRAS):
        dono = next(el.iterancestors(_P), None)
        if dono is not p:
            continue
        if el.tag == _T:
            nos.append(el)
        elif el.getparent() is not None and el.getparent().tag == _R:
            # <w:tab> também existe em <w:pPr><w:tabs> (definição de tabulação):
            # só conta como barreira quando está dentro de um run.
            nos.append(el)
    return nos


def _limpar_paragrafo(p) -> bool:
    nos = _nos_do_paragrafo(p)
    if not any(n.tag == _T for n in nos):
        return False

    alterou = False
    # Cada passada aplica a primeira correção encontrada e recalcula o texto.
    # Simples e seguro: os parágrafos são curtos e as correções, poucas.
    for _ in range(200):
        partes: list[str] = []
        origem: list[tuple[object, int]] = []  # (nó <w:t>, índice local) por caractere
        for n in nos:
            if n.tag == _T:
                txt = n.text or ""
                partes.append(txt)
                origem.extend((n, i) for i in range(len(txt)))
            else:
                partes.append(_BARREIRA)
                origem.append((None, -1))
        texto = "".join(partes)

        faixa = _primeira_faixa(texto)
        if faixa is None:
            break
        ini, fim = faixa
        if ini >= fim:
            break

        apagar: dict[object, set[int]] = {}
        for pos in range(ini, fim):
            no, idx = origem[pos]
            if no is not None:
                apagar.setdefault(no, set()).add(idx)
        for no, idxs in apagar.items():
            txt = no.text or ""
            novo = "".join(ch for i, ch in enumerate(txt) if i not in idxs)
            no.text = novo
            if novo != novo.strip():
                no.set(_XML_SPACE, "preserve")
        alterou = True
    return alterou


def _primeira_faixa(texto: str) -> tuple[int, int] | None:
    """Primeira faixa [ini, fim) a remover, ou None se o texto já está limpo."""
    m = _RE_VIRGULAS_REPETIDAS.search(texto)
    if m:
        # Mantém a primeira vírgula e, se havia espaço depois da última, um espaço só.
        fim = m.end() - 1 if m.group(1) else m.end()
        return m.start() + 1, fim
    m = _RE_VIRGULA_ANTES_PONTO.search(texto)
    if m:
        # Remove espaços + vírgula + espaços, mantém o ponto.
        return m.start(), m.end() - 1
    return None


def _elementos_raiz(document) -> list:
    """Corpo do documento + partes de cabeçalho e rodapé."""
    raizes = [document.element.body]
    vistos = set()
    for rel in document.part.rels.values():
        if rel.is_external or not rel.reltype.endswith(_RELS_CABECALHO_RODAPE):
            continue
        part = rel.target_part
        if id(part) in vistos:
            continue
        vistos.add(id(part))
        el = getattr(part, "element", None)
        if el is not None:
            raizes.append(el)
    return raizes


def limpar_pontuacao_vazia(document) -> int:
    """Corrige vírgulas repetidas / vírgula antes de ponto, in-place.

    `document` é um python-docx Document (ex.: DocxTemplate.docx após render).
    Cobre corpo (incluindo tabelas e caixas de texto), cabeçalhos e rodapés.
    Retorna quantos parágrafos foram alterados.
    """
    alterados = 0
    for raiz in _elementos_raiz(document):
        for p in raiz.iter(_P):
            if _limpar_paragrafo(p):
                alterados += 1
    return alterados

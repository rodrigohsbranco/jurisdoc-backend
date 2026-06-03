"""Helpers para resolver advogados de um Kit.

A regra de pré-seleção replica a UI antiga:
- Sócios da UF (sempre, com fallback OAB/SC)
- Não-sócios que atuam nos tipos de ação do kit

Para o snapshot, aplica a cascata de OAB:
  1. UF do cliente
  2. OAB/SC
  3. Primeira OAB cadastrada
  4. Placeholder '(OAB pendente)' + warning
"""
from __future__ import annotations

from typing import Iterable

from advogados.models import Advogado, OabUf


# ---------------------------------------------------------------------------
# Cascata de OAB
# ---------------------------------------------------------------------------

def resolver_oab(advogado: Advogado, uf_cliente: str) -> tuple[OabUf | None, str]:
    """Aplica a cascata e retorna (oab, fonte).

    fonte ∈ {"uf_cliente", "fallback_sc", "fallback_primeira", "pendente"}.
    Quando "pendente", o OabUf é None.
    """
    uf_cliente = (uf_cliente or "").strip().upper()
    oabs = list(advogado.oabs.all())

    if uf_cliente:
        for o in oabs:
            if o.uf.upper() == uf_cliente:
                return o, "uf_cliente"

    for o in oabs:
        if o.uf.upper() == "SC":
            return o, "fallback_sc"

    if oabs:
        return oabs[0], "fallback_primeira"

    return None, "pendente"


# ---------------------------------------------------------------------------
# Serialização para snapshot
# ---------------------------------------------------------------------------

def advogado_para_snapshot(advogado: Advogado, uf_cliente: str) -> tuple[dict, str | None]:
    """Monta o item do snapshot para um advogado. Retorna (item, warning_ou_None)."""
    oab, fonte = resolver_oab(advogado, uf_cliente)
    warning: str | None = None

    if oab is None:
        numero_oab = "(OAB pendente)"
        oab_uf = ""
        unidade_nome = ""
        unidade_end = ""
        warning = (
            f"Advogado '{advogado.nome_completo}' não possui nenhuma OAB cadastrada — "
            f"usando placeholder '{numero_oab}' no documento."
        )
    else:
        numero_oab = oab.numero_oab
        oab_uf = oab.uf.upper()
        unidade_nome = oab.unidade_apoio_nome or ""
        unidade_end = oab.unidade_apoio_endereco or ""

    return {
        "id": advogado.id,
        "nome_completo": advogado.nome_completo,
        "is_socio": bool(advogado.is_socio),
        "numero_oab": numero_oab,
        "oab_uf": oab_uf,
        "oab_fonte": fonte,
        "nacionalidade": advogado.nacionalidade or "",
        "estado_civil": advogado.estado_civil or "",
        "profissao": "advogado",
        "genero": advogado.genero or "masculino",
        "escritorio_nome": advogado.escritorio_nome or "",
        "escritorio_cnpj": advogado.escritorio_cnpj or "",
        "escritorio_endereco": advogado.escritorio_endereco or "",
        "unidade_apoio_nome": unidade_nome,
        "unidade_apoio_endereco": unidade_end,
    }, warning


def montar_snapshot(advogados_ids: Iterable[int], uf_cliente: str) -> tuple[list[dict], list[str]]:
    """Recebe IDs, carrega Advogados ordenados (sócios primeiro, nome ASC),
    monta o array do snapshot aplicando a cascata. Retorna (snapshot, warnings).
    """
    ids = [int(i) for i in advogados_ids if i is not None]
    advs = list(
        Advogado.objects.filter(id__in=ids, ativo=True)
        .order_by("-is_socio", "nome_completo")
        .prefetch_related("oabs")
    )
    snapshot: list[dict] = []
    warnings: list[str] = []
    for adv in advs:
        item, w = advogado_para_snapshot(adv, uf_cliente)
        snapshot.append(item)
        if w:
            warnings.append(w)
    return snapshot, warnings


# ---------------------------------------------------------------------------
# Pré-seleção (sugeridos)
# ---------------------------------------------------------------------------

def _advogado_atua_no_kit(tipos_acao_advogado: list[str], tipos_acao_kit: set[str]) -> bool:
    if not tipos_acao_advogado:
        return True
    if "todas" in tipos_acao_advogado:
        return True
    return any(t in tipos_acao_kit for t in tipos_acao_advogado)


def sugerir_advogados(uf_cliente: str, tipos_acao_kit: set[str]) -> list[int]:
    """Retorna lista de IDs de Advogados sugeridos pra UF/tipos_acao do kit.

    Regra (mesma do `por-uf` + filtro do front):
    - Sócios ativos que têm OAB na UF do cliente OU OAB/SC entram sempre.
    - Não-sócios ativos com OAB na UF do cliente entram se atuam em algum
      tipo de ação do kit (ou se 'todas' / sem filtro).
    """
    uf_cliente = (uf_cliente or "").strip().upper()
    if not uf_cliente:
        return []

    advogados = (
        Advogado.objects.filter(ativo=True)
        .prefetch_related("oabs")
    )
    out: list[int] = []
    for adv in advogados:
        oab_uf = adv.oabs.filter(uf=uf_cliente).first()
        oab_sc = adv.oabs.filter(uf="SC").first()

        if adv.is_socio:
            # Sócio entra se tem OAB na UF ou em SC (cascata futura cobre o resto).
            if oab_uf or oab_sc:
                out.append(adv.id)
            continue

        # Não-sócio precisa ter OAB na UF do cliente E atuar em algum tipo.
        if not oab_uf:
            continue
        if _advogado_atua_no_kit(list(oab_uf.tipos_acao or []), tipos_acao_kit):
            out.append(adv.id)

    return out

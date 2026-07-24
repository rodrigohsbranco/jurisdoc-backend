"""Proxy para a Google Places API (autocomplete de endereço + detalhes).

Motivo do proxy:
  A chave `GOOGLE_MAPS_API_KEY` é restrita por *HTTP referrer* (funciona a
  partir de localhost, mas não do domínio de produção quando chamada direto do
  navegador). A Places *Web Service* (REST) respeita o header `Referer`, então
  o backend faz a chamada enviando um Referer permitido pela chave
  (`GOOGLE_MAPS_PLACES_REFERER`) — assim a mesma chave passa a funcionar em
  produção sem expor o tráfego às restrições de origem do navegador.

Endpoints usados (Places API legada — retorna geometry/lat-lng direto):
  - /maps/api/place/autocomplete/json
  - /maps/api/place/details/json

Autenticação Google: chave estática (GOOGLE_MAPS_API_KEY no .env / EasyPanel).
Usa stdlib `urllib` — mesmo padrão de kits/services_zapsign.py, sem dependência extra.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

PLACES_API_BASE = "https://maps.googleapis.com/maps/api/place"


class MapsConfigError(RuntimeError):
    """Configuração ausente (chave não definida)."""


class MapsUpstreamError(RuntimeError):
    """Falha ao falar com a Google Places API."""


def _api_key() -> str:
    key = getattr(settings, "GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise MapsConfigError(
            "GOOGLE_MAPS_API_KEY não configurada. "
            "Defina a variável de ambiente no servidor."
        )
    return key


def _referer() -> str:
    # Referer que a chave restrita aceita (por padrão localhost do front em dev).
    return getattr(settings, "GOOGLE_MAPS_PLACES_REFERER", "http://localhost:3000").strip()


def _get(endpoint: str, params: dict) -> dict:
    """GET JSON na Places API enviando o Referer permitido. Lança MapsUpstreamError."""
    params = {**params, "key": _api_key()}
    url = f"{PLACES_API_BASE}{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            # É isto que faz a chave restrita por referrer aceitar a chamada.
            "Referer": _referer(),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise MapsUpstreamError(f"Erro Google Places (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise MapsUpstreamError(f"Falha de conexão com Google Places: {exc.reason}") from exc

    status = data.get("status")
    # ZERO_RESULTS é resposta válida (nenhuma sugestão), não erro.
    if status not in ("OK", "ZERO_RESULTS"):
        msg = data.get("error_message") or status or "erro desconhecido"
        raise MapsUpstreamError(f"Google Places retornou status {status}: {msg}")
    return data


# ---------------------------------------------------------------------------
# API pública do serviço
# ---------------------------------------------------------------------------

def autocomplete(entrada: str, session_token: str = "") -> list[dict]:
    """Sugestões de endereço (Brasil, pt-BR).

    Retorna: [{ description, place_id }].
    """
    entrada = (entrada or "").strip()
    if len(entrada) < 3:
        return []

    params = {
        "input": entrada,
        "language": "pt-BR",
        "components": "country:br",
    }
    if session_token:
        params["sessiontoken"] = session_token

    data = _get("/autocomplete/json", params)
    return [
        {"description": p.get("description", ""), "place_id": p.get("place_id", "")}
        for p in data.get("predictions", [])
        if p.get("place_id")
    ]


# Mapeia os `types` do address_component do Google para os campos do cadastro.
def _componentes_para_endereco(componentes: list[dict]) -> dict:
    out = {
        "rua": "",
        "numero": "",
        "bairro": "",
        "cidade": "",
        "estado": "",
        "cep": "",
    }
    for comp in componentes:
        tipos = comp.get("types", [])
        longo = comp.get("long_name", "")
        curto = comp.get("short_name", "")
        if "route" in tipos:
            out["rua"] = longo
        elif "street_number" in tipos:
            out["numero"] = longo
        elif "postal_code" in tipos:
            out["cep"] = longo
        elif "administrative_area_level_1" in tipos:
            out["estado"] = curto  # UF (ex.: SP)
        elif not out["cidade"] and (
            "locality" in tipos or "administrative_area_level_2" in tipos
        ):
            out["cidade"] = longo
        elif not out["bairro"] and (
            "sublocality_level_1" in tipos
            or "sublocality" in tipos
            or "neighborhood" in tipos
        ):
            out["bairro"] = longo
    return out


def place_details(place_id: str, session_token: str = "") -> dict:
    """Detalhes de um place_id: endereço quebrado em campos + lat/long.

    Retorna: { endereco_formatado, rua, numero, bairro, cidade, estado, cep,
               latitude, longitude }.
    """
    place_id = (place_id or "").strip()
    if not place_id:
        raise MapsUpstreamError("place_id vazio.")

    params = {
        "place_id": place_id,
        "language": "pt-BR",
        "fields": "address_component,formatted_address,geometry",
    }
    if session_token:
        params["sessiontoken"] = session_token

    data = _get("/details/json", params)
    result = data.get("result", {}) or {}

    endereco = _componentes_para_endereco(result.get("address_components", []))
    location = (result.get("geometry", {}) or {}).get("location", {}) or {}

    return {
        "endereco_formatado": result.get("formatted_address", ""),
        **endereco,
        "latitude": location.get("lat"),
        "longitude": location.get("lng"),
    }

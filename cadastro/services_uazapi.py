"""Integração com o uazapi — envio do código de acesso do cliente por WhatsApp.

Usado somente pela área "Sou cliente" do app FlowALR. Nada aqui é chamado pelo
JurisDoc em si.

O uazapi automatiza uma conta real de WhatsApp (não é a API oficial da Meta).
Consequência prática registrada na própria documentação dele: o WhatsApp impõe
um teto para **iniciar novas conversas** e, ao estourar, responde com o erro
`463 / WHATSAPP_REACHOUT_TIMELOCK`. Login por código é exatamente esse padrão —
uma conversa nova a cada acesso. Por isso:

  - `RestricaoWhatsAppError` é uma exceção própria, para a view oferecer o
    acesso alternativo em vez de mostrar erro genérico;
  - `limites_mensagens()` existe para diagnóstico antes que o problema apareça.

Endpoints usados (todos autenticados pelo token da instância no header `token`):
  POST /chat/check                    → o número existe no WhatsApp?
  POST /send/text                     → envia o código
  GET  /instance/status               → a instância está conectada?
  GET  /instance/wa_messages_limits   → diagnóstico do teto de novas conversas
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 30


class UazapiError(RuntimeError):
    """Falha genérica de comunicação com o uazapi."""


class RestricaoWhatsAppError(UazapiError):
    """O WhatsApp recusou por restrição de novas conversas (erro 463).

    Não é erro nosso nem do uazapi: a conta conectada estourou o teto de
    conversas novas. A saída para o cliente é o acesso alternativo.
    """


class NumeroSemWhatsAppError(UazapiError):
    """O número informado não tem WhatsApp."""


# ---------------------------------------------------------------------------
# Normalização de número
# ---------------------------------------------------------------------------

def normalizar_telefone(valor: str) -> str | None:
    """Converte o que o cliente digitou em dígitos com DDI do Brasil.

    Aceita "(48) 99999-9999", "48999999999", "+55 48 99999-9999".
    Retorna None quando não dá para interpretar como telefone brasileiro.

    Atenção: esta é a normalização *sintática*. A canônica — que resolve a
    variação do nono dígito — é o `jid` devolvido por `verificar_numero`.
    """
    digitos = re.sub(r"\D", "", str(valor or ""))
    if not digitos:
        return None

    if digitos.startswith("55"):
        resto = digitos[2:]
        # DDD (2) + 8 ou 9 dígitos
        if len(resto) in (10, 11):
            return digitos
        return None

    if len(digitos) in (10, 11):
        return f"55{digitos}"
    return None


def telefone_do_jid(jid: str) -> str:
    """Extrai só os dígitos do jid ("5548999999999@s.whatsapp.net")."""
    return re.sub(r"\D", "", str(jid or "").split("@")[0])


def variantes_telefone(telefone: str) -> list[str]:
    """Formas equivalentes do mesmo celular brasileiro (com e sem o nono dígito).

    O WhatsApp trata "5548999998888" e "554899998888" como o mesmo número, e o
    `/chat/check` confirma isso devolvendo o mesmo jid. Aqui reproduzimos essa
    equivalência sem gastar uma chamada de rede — usado para localizar conta e
    código a partir do que o cliente digitou.
    """
    digitos = re.sub(r"\D", "", str(telefone or ""))
    if not digitos.startswith("55"):
        return [digitos] if digitos else []

    ddd, resto = digitos[2:4], digitos[4:]
    variantes = {digitos}
    if len(resto) == 9 and resto.startswith("9"):
        variantes.add(f"55{ddd}{resto[1:]}")
    elif len(resto) == 8:
        variantes.add(f"55{ddd}9{resto}")
    return sorted(variantes)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _config() -> tuple[str, str]:
    base = (getattr(settings, "UAZAPI_BASE_URL", "") or "").strip().rstrip("/")
    token = (getattr(settings, "UAZAPI_INSTANCE_TOKEN", "") or "").strip()
    if not base or not token:
        raise UazapiError(
            "Integração de WhatsApp não configurada no servidor "
            "(UAZAPI_BASE_URL / UAZAPI_INSTANCE_TOKEN)."
        )
    return base, token


def _request(path: str, method: str = "GET", body: dict | None = None):
    base, token = _config()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={"token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        bruto = exc.read().decode("utf-8", errors="replace")[:800]
        _levantar_erro_http(exc.code, bruto, path)
    except urllib.error.URLError as exc:
        raise UazapiError(f"Falha de conexão com o WhatsApp: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UazapiError("Resposta inesperada do serviço de WhatsApp.") from exc


def _levantar_erro_http(codigo: int, corpo: str, path: str):
    """Traduz o erro do uazapi, separando restrição do WhatsApp de falha nossa."""
    try:
        dados = json.loads(corpo)
    except json.JSONDecodeError:
        dados = {}

    if dados.get("error_key") == "WHATSAPP_REACHOUT_TIMELOCK" or dados.get("provider_code") == 463:
        logger.error(
            "uazapi: WhatsApp bloqueou novas conversas (463) — "
            f"{dados.get('provider_message_ptbr') or dados.get('provider_message')}"
        )
        raise RestricaoWhatsAppError(
            "O WhatsApp está temporariamente limitando novas conversas a partir "
            "do número do escritório."
        )

    if codigo == 401:
        logger.error("uazapi: token da instância inválido ou ausente")
        raise UazapiError("Credencial do serviço de WhatsApp inválida.")

    if codigo == 429:
        logger.warning("uazapi: rate limit atingido")
        raise UazapiError("Muitos envios em sequência. Tente novamente em instantes.")

    logger.error(f"uazapi: HTTP {codigo} em {path} — {corpo[:300]}")
    raise UazapiError("Não foi possível enviar a mensagem pelo WhatsApp agora.")


# ---------------------------------------------------------------------------
# Operações
# ---------------------------------------------------------------------------

def verificar_numero(telefone: str) -> dict:
    """Confere se o número tem WhatsApp e devolve a forma canônica.

    Retorna {"telefone": <dígitos do jid>, "jid": str, "nome": str}.
    Lança NumeroSemWhatsAppError quando não há conta no número.
    """
    resultado = _request("/chat/check", "POST", {"numbers": [telefone]})

    item = resultado[0] if isinstance(resultado, list) and resultado else {}
    if not item.get("isInWhatsapp"):
        raise NumeroSemWhatsAppError("Este número não tem WhatsApp.")

    jid = item.get("jid") or ""
    canonico = telefone_do_jid(jid) or telefone
    return {"telefone": canonico, "jid": jid, "nome": item.get("verifiedName") or ""}


def enviar_texto(telefone: str, texto: str) -> dict:
    """Envia uma mensagem de texto. `telefone` deve ser só dígitos com DDI."""
    return _request("/send/text", "POST", {"number": telefone, "text": texto})


def status_instancia() -> dict:
    """Estado da conexão da instância (diagnóstico)."""
    dados = _request("/instance/status")
    instancia = dados.get("instance") or {}
    status = dados.get("status") or {}
    return {
        "status": instancia.get("status"),
        "conectada": bool(status.get("connected")),
        "logada": bool(status.get("loggedIn")),
        "nome": instancia.get("name"),
        "numero": instancia.get("owner"),
    }


def limites_mensagens() -> dict:
    """Teto atual de novas conversas reportado pelo WhatsApp (diagnóstico)."""
    dados = _request("/instance/wa_messages_limits")
    return {
        "pode_iniciar_conversas": dados.get("can_send_new_messages"),
        "mensagem": dados.get("message_ptbr") or dados.get("message"),
        "restricao_ativa": (dados.get("reachout_timelock") or {}).get("active"),
        "restricao_ate": (dados.get("reachout_timelock") or {}).get("until"),
        "cota_usada": (dados.get("new_chat_message_capping") or {}).get("used_quota"),
        "cota_total": (dados.get("new_chat_message_capping") or {}).get("total_quota"),
    }

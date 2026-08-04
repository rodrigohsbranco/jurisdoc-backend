"""Integração com a API ZapSign para assinatura eletrônica de kits.

Fluxo atual (um documento ZapSign por DocumentoKit + portal de link único):
  1. enviar_para_assinatura(kit, config, base_url) → cria UM documento no ZapSign
     para CADA DocumentoKit. Cada documento é assinado separadamente pelo cliente
     (assinatura individual por documento, exigência jurídica do escritório).
     O `redirect_link` de cada signatário aponta de volta ao portal do JurisDoc,
     de modo que o cliente recebe um ÚNICO link e o portal o conduz de um
     documento ao próximo.
  2. Webhook recebe "doc_signed" por documento (busca por DocumentoKit.zapsign_doc_token)
     → baixa o PDF assinado e atualiza o status. Quando todos os documentos enviados
     estão assinados, kit.status = "assinado".

Por que não usar envelope (extra_docs): no ZapSign um envelope é assinado em uma
única cerimônia — o cliente desenha a assinatura uma vez e ela vale para todos os
documentos do envelope. Pastas (folder_path/folder_token) são apenas organização
do acervo e não geram link de assinatura. Portanto, assinatura individual exige
documentos separados; o link único vem do portal do JurisDoc.

Config dict aceita:
  nivel: "basico" | "medio" | "avancado"
  medio_tipo: "email" | "sms"  (usado apenas quando nivel == "medio")
  assinatura_paginas: bool  (adiciona bloco de assinatura nas primeiras 2 páginas)

Autenticação: token estático Bearer (ZAPSIGN_API_TOKEN no .env / EasyPanel).
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
import uuid
from io import BytesIO

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from .models import Kit

logger = logging.getLogger(__name__)

ZAPSIGN_API_BASE = "https://api.zapsign.com.br/api/v1"

# Cache do status consultado ao vivo no ZapSign (o webhook é assíncrono e pode
# demorar alguns segundos; o portal consulta a API para não mostrar como pendente
# um documento que o cliente acabou de assinar).
_STATUS_CACHE_TTL = 20


# ---------------------------------------------------------------------------
# Helpers HTTP (usa stdlib — sem dependência extra)
# ---------------------------------------------------------------------------

def _auth_headers() -> dict:
    token = getattr(settings, "ZAPSIGN_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "ZAPSIGN_API_TOKEN não configurado. "
            "Defina a variável de ambiente no servidor."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _post(endpoint: str, payload: dict) -> dict:
    """POST JSON para a API ZapSign. Lança RuntimeError em caso de falha."""
    headers = _auth_headers()
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{ZAPSIGN_API_BASE}{endpoint}",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Erro ZapSign (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexão com ZapSign: {exc.reason}") from exc


def _get(endpoint: str) -> dict:
    """GET JSON na API ZapSign. Lança RuntimeError em caso de falha."""
    req = urllib.request.Request(
        f"{ZAPSIGN_API_BASE}{endpoint}",
        headers=_auth_headers(),
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Erro ZapSign (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexão com ZapSign: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Portal de assinatura (link único do JurisDoc)
# ---------------------------------------------------------------------------

def base_url_from_request(request) -> str:
    """Origem pública derivada do request (respeita X-Forwarded-Proto do proxy)."""
    return request.build_absolute_uri("/").rstrip("/")


def _resolve_base_url(base_url: str | None) -> str:
    """Resolve a origem pública do backend (sem barra final).

    PUBLIC_BASE_URL tem prioridade — em produção o backend responde por mais de
    um host e o link precisa ser estável. Sem ela, usa o valor derivado do
    request (caso de desenvolvimento e de túneis como o ngrok).
    """
    candidato = (
        getattr(settings, "PUBLIC_BASE_URL", "") or base_url or ""
    ).strip()
    if not candidato:
        raise RuntimeError(
            "Não foi possível determinar a URL pública do JurisDoc para montar o "
            "link de assinatura. Defina PUBLIC_BASE_URL no .env do servidor."
        )
    return candidato.rstrip("/")


def portal_url(kit: Kit, base_url: str | None = None) -> str:
    """Retorna (criando o token se necessário) a URL pública do portal do kit."""
    if not kit.zapsign_portal_token:
        kit.zapsign_portal_token = uuid.uuid4()
        kit.save(update_fields=["zapsign_portal_token", "atualizado_em"])
    caminho = reverse("assinatura-portal", args=[str(kit.zapsign_portal_token)])
    return f"{_resolve_base_url(base_url)}{caminho}"


def _chave_cache_status(doc_token: str) -> str:
    return f"zapsign:doc_status:{doc_token}"


def invalidar_cache_status(doc_token: str) -> None:
    """Descarta o status cacheado — chamado quando o webhook traz a versão final."""
    if doc_token:
        cache.delete(_chave_cache_status(doc_token))


def documento_assinado_no_zapsign(doc_token: str) -> bool | None:
    """Consulta ao vivo se o documento já foi assinado no ZapSign.

    Retorna True/False, ou None quando a consulta falha (o chamador deve então
    usar o status local gravado pelo webhook). Resultado positivo é cacheado.
    """
    if not doc_token:
        return None

    chave = _chave_cache_status(doc_token)
    cacheado = cache.get(chave)
    if cacheado is not None:
        return cacheado

    try:
        data = _get(f"/docs/{doc_token}/")
    except RuntimeError as exc:
        logger.warning(f"ZapSign: falha ao consultar status de {doc_token[:8]}… — {exc}")
        return None

    assinado = data.get("status") == "signed"
    cache.set(chave, assinado, _STATUS_CACHE_TTL)
    return assinado


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _get_assinatura_list(pdf_bytes: bytes, max_pages: int = 2) -> list[dict]:
    """Retorna lista de assinaturas posicionais nas primeiras páginas do documento.

    Usa type='signature' (assinatura completa) com dimensões recomendadas pelo ZapSign
    para A4 vertical. Posicionada no canto inferior esquerdo de cada página.
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(pdf_bytes))
        page_count = len(reader.pages)
    except Exception:
        page_count = max_pages

    pages = min(page_count, max_pages)
    return [
        {
            "page": p + 1,
            "relative_position_bottom": 3,
            "relative_position_left": 2,
            "relative_size_x": 20,
            "relative_size_y": 9,
            "type": "signature",
        }
        for p in range(pages)
    ]


def _build_signer(
    kit: Kit,
    config: dict,
    pdf_bytes: bytes | None = None,
    redirect_link: str | None = None,
) -> dict:
    """Monta o objeto signer com auth_mode, opções de segurança e assinatura posicional."""
    nivel = config.get("nivel", "basico")
    com_assinatura_paginas = config.get("assinatura_paginas", False)

    cliente = kit.cliente
    nome = (cliente.nome_completo or "Cliente").strip()

    # Auth mode baseado no nível
    if nivel == "medio":
        medio_tipo = config.get("medio_tipo", "email")
        if medio_tipo == "sms":
            auth_mode = "assinaturaTela-tokenSms"
        else:
            auth_mode = "assinaturaTela-tokenEmail"
    else:
        auth_mode = "assinaturaTela"

    signer: dict = {
        "name": nome,
        "auth_mode": auth_mode,
        "send_automatic_email": False,
        "send_automatic_whatsapp": False,
        "blank_email": True,
        "lock_name": True,
    }

    # Volta ao portal do JurisDoc depois de assinar, para seguir ao próximo documento
    if redirect_link:
        signer["redirect_link"] = redirect_link

    # Selfie + foto de documento para nível avançado (sem validação Receita Federal)
    if nivel == "avancado":
        signer["require_selfie_photo"] = True
        signer["require_document_photo"] = True

    # Telefone se disponível (necessário para SMS)
    telefone_digits = "".join(c for c in (cliente.telefone or "") if c.isdigit())
    if len(telefone_digits) >= 10:
        signer["phone_country"] = "55"
        signer["phone_number"] = telefone_digits
        signer["blank_phone"] = False

    # Assinatura posicional nas primeiras 2 páginas
    if com_assinatura_paginas and pdf_bytes:
        signer["rubric_list"] = _get_assinatura_list(pdf_bytes)

    return signer


# ---------------------------------------------------------------------------
# Integração principal
# ---------------------------------------------------------------------------

def enviar_para_assinatura(
    kit: Kit,
    config: dict | None = None,
    base_url: str | None = None,
) -> dict:
    """Envia cada DocumentoKit como um documento separado ao ZapSign.

    Cada documento tem sua própria cerimônia de assinatura (o cliente assina um a
    um). O link entregue ao cliente é o do portal do JurisDoc, que encadeia os
    documentos e é retomável a qualquer momento.

    Parâmetros:
        kit: instância do Kit com documentos já gerados.
        config: dict com nivel, medio_tipo, assinatura_paginas (ver cabeçalho).
        base_url: origem pública do backend (ex.: "https://api.exemplo.com.br").

    Retorna dict com:
        sign_url: link único do portal (para o cliente)
        documentos: lista de {tipo, tipo_display} dos documentos enviados

    Grava zapsign_doc_token + zapsign_sign_url + zapsign_status em cada DocumentoKit
    e zapsign_sign_url (portal) + zapsign_status no Kit.
    Lança RuntimeError com mensagem legível em caso de falha.
    """
    if config is None:
        config = {}

    docs = list(
        kit.documentos
        .exclude(tipo="assinado_zapsign")
        .order_by("tipo")
    )
    if not docs:
        raise RuntimeError(
            "Nenhum documento gerado para este kit. "
            "Gere os documentos antes de enviar para assinatura."
        )

    nome_cliente = (kit.cliente.nome_completo or "Cliente").strip()

    # Carrega todos os PDFs válidos antes de falar com o ZapSign
    docs_validos: list[tuple] = []
    for doc in docs:
        if not doc.arquivo or not doc.arquivo.name:
            logger.warning(f"DocumentoKit #{doc.id} sem arquivo — pulado")
            continue
        try:
            with doc.arquivo.open("rb") as f:
                pdf_bytes = f.read()
            docs_validos.append((doc, pdf_bytes))
        except FileNotFoundError:
            logger.warning(f"Arquivo não encontrado: {doc.arquivo.name} — pulado")

    if not docs_validos:
        raise RuntimeError(
            "Nenhum arquivo de documento encontrado. "
            "Regenere os documentos antes de enviar para assinatura."
        )

    # Portal precisa existir antes de criar os documentos (vai no redirect_link)
    url_portal = portal_url(kit, base_url)

    # Zera o estado anterior: se o envio falhar no meio, o kit não fica "pending"
    # com um link parcial — a próxima tentativa reenvia tudo.
    kit.documentos.exclude(tipo="assinado_zapsign").update(
        zapsign_doc_token=None,
        zapsign_sign_url=None,
        zapsign_status=None,
    )
    if kit.zapsign_doc_token or kit.zapsign_status:
        kit.zapsign_doc_token = None  # fluxo de bundle não é mais usado
        kit.zapsign_status = None
        kit.save(update_fields=["zapsign_doc_token", "zapsign_status", "atualizado_em"])

    enviados: list[dict] = []
    for doc, pdf_bytes in docs_validos:
        signer = _build_signer(kit, config, pdf_bytes, redirect_link=url_portal)
        payload = {
            "name": f"{doc.get_tipo_display()} — {nome_cliente}",
            "base64_pdf": base64.b64encode(pdf_bytes).decode("utf-8"),
            "lang": "pt-br",
            "disable_signer_emails": True,
            "signers": [signer],
        }

        try:
            data = _post("/docs/", payload)
        except RuntimeError as exc:
            if enviados:
                logger.error(
                    f"Kit #{kit.id}: falha ao enviar '{doc.tipo}' após já ter criado "
                    f"{len(enviados)} documento(s) no ZapSign "
                    f"({', '.join(d['tipo'] for d in enviados)}). "
                    f"Cancele-os no painel do ZapSign antes de reenviar."
                )
            raise RuntimeError(
                f"Falha ao enviar '{doc.get_tipo_display()}' ao ZapSign: {exc}"
            ) from exc

        doc_token = data.get("token")
        signers_resp = data.get("signers", [])
        sign_url = signers_resp[0].get("sign_url") if signers_resp else None

        if not doc_token or not sign_url:
            raise RuntimeError(
                f"Resposta inválida do ZapSign para '{doc.get_tipo_display()}': "
                "token ou sign_url ausente."
            )

        doc.zapsign_doc_token = doc_token
        doc.zapsign_sign_url = sign_url
        doc.zapsign_status = "pending"
        doc.save(update_fields=["zapsign_doc_token", "zapsign_sign_url", "zapsign_status"])

        enviados.append({"tipo": doc.tipo, "tipo_display": doc.get_tipo_display()})
        logger.info(
            f"Kit #{kit.id} — '{doc.tipo}' enviado ao ZapSign (token={doc_token[:8]}…)"
        )

    kit.zapsign_sign_url = url_portal
    kit.zapsign_status = "pending"
    kit.save(update_fields=["zapsign_sign_url", "zapsign_status", "atualizado_em"])

    logger.info(
        f"Kit #{kit.id}: {len(enviados)} documento(s) enviados individualmente — "
        f"portal {url_portal}"
    )

    return {"sign_url": url_portal, "documentos": enviados}


def baixar_arquivo_assinado(url: str) -> bytes:
    """Baixa o PDF assinado da URL temporária do ZapSign (válida 60 min)."""
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha ao baixar PDF assinado do ZapSign: {exc.reason}") from exc

"""Integração com a API ZapSign para assinatura eletrônica de kits.

Fluxo:
  1. enviar_para_assinatura(kit) → mescla PDFs, envia ao ZapSign, salva doc_token + sign_url no kit
  2. Webhook recebe "doc_signed" → baixar_arquivo_assinado(url) → caller salva como DocumentoKit

Autenticação: token estático Bearer (ZAPSIGN_API_TOKEN no .env / EasyPanel).
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from io import BytesIO

from django.conf import settings

from .models import Kit

logger = logging.getLogger(__name__)

ZAPSIGN_API_BASE = "https://api.zapsign.com.br/api/v1"


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
        raise RuntimeError(
            f"Erro ZapSign (HTTP {exc.code}): {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexão com ZapSign: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Geração do PDF unificado
# ---------------------------------------------------------------------------

def _build_unified_pdf_b64(kit: Kit) -> str:
    """Mescla todos os PDFs do kit (exceto assinado_zapsign) em base64."""
    from pypdf import PdfWriter

    docs = list(kit.documentos.exclude(tipo="assinado_zapsign").order_by("tipo"))
    if not docs:
        raise RuntimeError(
            "Nenhum documento gerado para este kit. "
            "Gere os documentos na etapa 'Kit Final' antes de enviar para assinatura."
        )

    writer = PdfWriter()
    for doc in docs:
        if not doc.arquivo or not doc.arquivo.name:
            continue
        try:
            with doc.arquivo.open("rb") as f:
                writer.append(f)
        except FileNotFoundError:
            logger.warning(f"Arquivo não encontrado ao montar PDF unificado: {doc.arquivo.name}")

    buf = BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    if not pdf_bytes:
        raise RuntimeError("Nenhum arquivo válido encontrado nos documentos do kit.")

    return base64.b64encode(pdf_bytes).decode("utf-8")


# ---------------------------------------------------------------------------
# Integração principal
# ---------------------------------------------------------------------------

def enviar_para_assinatura(kit: Kit) -> dict:
    """Envia o kit unificado para assinatura eletrônica no ZapSign.

    Retorna {"doc_token": str, "sign_url": str}.
    Atualiza os campos zapsign_* do kit no banco.
    Lança RuntimeError com mensagem legível em caso de falha.
    """
    pdf_b64 = _build_unified_pdf_b64(kit)

    cliente = kit.cliente
    nome_cliente = (cliente.nome_completo or "Cliente").strip()

    # Signatário: assinatura na tela (mais simples, sem exigir email ou SMS)
    signer: dict = {
        "name": nome_cliente,
        "auth_mode": "assinaturaTela",
        "send_automatic_email": False,
        "send_automatic_whatsapp": False,
        "blank_email": True,
        "lock_name": True,
    }

    # Inclui telefone se disponível
    telefone = (cliente.telefone or "").strip()
    telefone_digits = "".join(c for c in telefone if c.isdigit())
    if len(telefone_digits) >= 10:
        signer["phone_country"] = "55"
        signer["phone_number"] = telefone_digits
        signer["blank_phone"] = False

    doc_name = f"Kit {kit.get_tipo_display()} — {nome_cliente}"

    payload = {
        "name": doc_name,
        "base64_pdf": pdf_b64,
        "lang": "pt-br",
        "disable_signer_emails": True,
        "signers": [signer],
    }

    data = _post("/docs/", payload)

    doc_token = data.get("token")
    signers_resp = data.get("signers", [])
    sign_url = signers_resp[0].get("sign_url") if signers_resp else None

    if not doc_token or not sign_url:
        raise RuntimeError(
            "Resposta inesperada do ZapSign: campos 'token' ou 'sign_url' ausentes."
        )

    kit.zapsign_doc_token = doc_token
    kit.zapsign_sign_url = sign_url
    kit.zapsign_status = "pending"
    kit.save(update_fields=["zapsign_doc_token", "zapsign_sign_url", "zapsign_status", "atualizado_em"])

    logger.info(f"Kit #{kit.id} enviado ao ZapSign — doc_token={doc_token[:8]}…")
    return {"doc_token": doc_token, "sign_url": sign_url}


def baixar_arquivo_assinado(url: str) -> bytes:
    """Baixa o PDF assinado da URL temporária do ZapSign (válida 60 min)."""
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha ao baixar PDF assinado do ZapSign: {exc.reason}") from exc

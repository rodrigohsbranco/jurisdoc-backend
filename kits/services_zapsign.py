"""Integração com a API ZapSign para assinatura eletrônica de kits.

Fluxo:
  1. enviar_para_assinatura(kit, config) → envia cada DocumentoKit como documento
     separado no ZapSign, salva doc_token + sign_url em cada DocumentoKit.
  2. Webhook recebe "doc_signed" por documento → baixa PDF assinado, atualiza status.
     Quando todos os documentos estão assinados, kit.status = "assinado".

Config dict aceita:
  nivel: "basico" | "medio" | "avancado"
  medio_tipo: "email" | "sms"  (usado apenas quando nivel == "medio")
  rubrica: bool  (adiciona rubrica nas primeiras 2 páginas de cada documento)

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

from .models import DocumentoKit, Kit

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
        raise RuntimeError(f"Erro ZapSign (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexão com ZapSign: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _get_rubrica_list(pdf_bytes: bytes, max_pages: int = 2) -> list[dict]:
    """Retorna lista de rubricas posicionais nas primeiras páginas do documento."""
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
            "relative_size_x": 15,
            "relative_size_y": 4,
            "type": "visto",
        }
        for p in range(pages)
    ]


def _build_signer(kit: Kit, config: dict, pdf_bytes: bytes | None = None) -> dict:
    """Monta o objeto signer com auth_mode, opções de segurança e rubrica."""
    nivel = config.get("nivel", "basico")
    com_rubrica = config.get("rubrica", False)

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

    # Rubrica nas primeiras 2 páginas
    if com_rubrica and pdf_bytes:
        signer["rubric_list"] = _get_rubrica_list(pdf_bytes)

    return signer


# ---------------------------------------------------------------------------
# Integração principal
# ---------------------------------------------------------------------------

def enviar_para_assinatura(kit: Kit, config: dict | None = None) -> list[dict]:
    """Envia cada DocumentoKit como documento separado ao ZapSign.

    Parâmetros:
        kit: instância do Kit com documentos já gerados.
        config: dict com nivel, medio_tipo, rubrica (ver cabeçalho do módulo).

    Retorna lista de {tipo, tipo_display, sign_url, doc_token} por documento enviado.
    Atualiza zapsign_doc_token, zapsign_sign_url, zapsign_status em cada DocumentoKit.
    Atualiza kit.zapsign_status = "pending".
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

    cliente = kit.cliente
    nome_cliente = (cliente.nome_completo or "Cliente").strip()
    results = []

    for doc in docs:
        if not doc.arquivo or not doc.arquivo.name:
            logger.warning(f"DocumentoKit #{doc.id} sem arquivo — pulado")
            continue

        try:
            with doc.arquivo.open("rb") as f:
                pdf_bytes = f.read()
        except FileNotFoundError:
            logger.warning(f"Arquivo não encontrado: {doc.arquivo.name} — pulado")
            continue

        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        signer = _build_signer(kit, config, pdf_bytes)
        doc_name = f"{doc.get_tipo_display()} — {nome_cliente}"

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
            logger.warning(
                f"Resposta ZapSign sem token/sign_url para {doc.tipo} — pulado"
            )
            continue

        doc.zapsign_doc_token = doc_token
        doc.zapsign_sign_url = sign_url
        doc.zapsign_status = "pending"
        doc.save(update_fields=["zapsign_doc_token", "zapsign_sign_url", "zapsign_status"])

        results.append({
            "tipo": doc.tipo,
            "tipo_display": doc.get_tipo_display(),
            "sign_url": sign_url,
            "doc_token": doc_token,
        })

        logger.info(
            f"Kit #{kit.id} — {doc.tipo} enviado ao ZapSign (token={doc_token[:8]}…)"
        )

    if not results:
        raise RuntimeError(
            "Nenhum documento pôde ser enviado ao ZapSign. "
            "Verifique se os arquivos estão acessíveis."
        )

    kit.zapsign_status = "pending"
    kit.save(update_fields=["zapsign_status", "atualizado_em"])

    return results


def baixar_arquivo_assinado(url: str) -> bytes:
    """Baixa o PDF assinado da URL temporária do ZapSign (válida 60 min)."""
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha ao baixar PDF assinado do ZapSign: {exc.reason}") from exc

"""Integração com a API ZapSign para assinatura eletrônica de kits.

Fluxo:
  1. enviar_para_assinatura(kit, config) → cria UM documento no ZapSign com o
     primeiro PDF como principal e os demais como extra_docs. O cliente recebe
     um único link e assina todos os documentos em sequência.
  2. Webhook recebe "doc_signed" (um evento para o bundle inteiro) com o token
     do documento principal → marca kit + todos os DocumentoKit como assinados.

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


def _build_signer(kit: Kit, config: dict, pdf_bytes: bytes | None = None) -> dict:
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

def enviar_para_assinatura(kit: Kit, config: dict | None = None) -> dict:
    """Cria um único documento ZapSign com todos os PDFs do kit.

    O primeiro DocumentoKit vira o documento principal; os demais são adicionados
    como extra_docs via POST /docs/{token}/upload-extra-doc/. O signatário recebe
    um único link e assina todos os documentos em sequência.

    Parâmetros:
        kit: instância do Kit com documentos já gerados.
        config: dict com nivel, medio_tipo, rubrica (ver cabeçalho do módulo).

    Retorna dict com:
        sign_url: link único de assinatura (para o cliente)
        documentos: lista de {tipo, tipo_display} dos documentos incluídos

    Salva zapsign_doc_token + zapsign_sign_url no Kit.
    Marca todos os DocumentoKit como zapsign_status="pending" (sem token individual).
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
    kit_label = kit.get_tipo_display()

    # Carrega todos os PDFs válidos
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

    # ── Documento principal (primeiro PDF) ──
    doc_principal, pdf_bytes_principal = docs_validos[0]
    signer = _build_signer(kit, config, pdf_bytes_principal)

    payload = {
        "name": f"Kit {kit_label} — {nome_cliente}",
        "base64_pdf": base64.b64encode(pdf_bytes_principal).decode("utf-8"),
        "lang": "pt-br",
        "disable_signer_emails": True,
        "signers": [signer],
    }

    data = _post("/docs/", payload)

    main_token = data.get("token")
    signers_resp = data.get("signers", [])
    sign_url = signers_resp[0].get("sign_url") if signers_resp else None

    if not main_token or not sign_url:
        raise RuntimeError(
            "Resposta inválida do ZapSign ao criar documento principal: "
            "token ou sign_url ausente."
        )

    logger.info(
        f"Kit #{kit.id} — documento principal '{doc_principal.tipo}' criado "
        f"(token={main_token[:8]}…)"
    )

    # ── Extra docs (demais PDFs) ──
    for doc, pdf_bytes in docs_validos[1:]:
        try:
            _post(
                f"/docs/{main_token}/upload-extra-doc/",
                {
                    "name": doc.get_tipo_display(),
                    "base64_pdf": base64.b64encode(pdf_bytes).decode("utf-8"),
                },
            )
            logger.info(f"Kit #{kit.id} — '{doc.tipo}' adicionado como extra_doc")
        except RuntimeError as exc:
            logger.error(
                f"Kit #{kit.id} — falha ao adicionar '{doc.tipo}' como extra_doc: {exc}"
            )
            raise

    # ── Persiste estado ──
    # Limpa tokens individuais (não existem mais no novo fluxo) e marca tudo como pending
    kit.documentos.exclude(tipo="assinado_zapsign").update(
        zapsign_doc_token=None,
        zapsign_sign_url=None,
        zapsign_status="pending",
    )

    kit.zapsign_doc_token = main_token
    kit.zapsign_sign_url = sign_url
    kit.zapsign_status = "pending"
    kit.save(
        update_fields=["zapsign_doc_token", "zapsign_sign_url", "zapsign_status", "atualizado_em"]
    )

    return {
        "sign_url": sign_url,
        "documentos": [
            {"tipo": d.tipo, "tipo_display": d.get_tipo_display()}
            for d, _ in docs_validos
        ],
    }


def baixar_arquivo_assinado(url: str) -> bytes:
    """Baixa o PDF assinado da URL temporária do ZapSign (válida 60 min)."""
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha ao baixar PDF assinado do ZapSign: {exc.reason}") from exc

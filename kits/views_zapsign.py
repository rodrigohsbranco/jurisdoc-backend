"""Webhook público para receber notificações de eventos do ZapSign.

Fluxo atual: um documento ZapSign por DocumentoKit — o webhook chega uma vez por
documento e é localizado por DocumentoKit.zapsign_doc_token (_handle_signed).

Fluxo legado (bundle extra_docs): um único evento para o envelope inteiro,
localizado por Kit.zapsign_doc_token (_handle_signed_bundle). Mantido para os
kits enviados antes da migração para assinatura individual.
"""
import json
import logging

from django.core.files.base import ContentFile
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DocumentoKit, Kit
from .services_documentos import slug_nome_cliente
from .services_zapsign import baixar_arquivo_assinado, invalidar_cache_status

logger = logging.getLogger(__name__)


def _extrair_token_e_evento(data: dict) -> tuple[str, str, str | None]:
    """Extrai event_type, doc_token e signed_file do payload do ZapSign.

    O ZapSign pode enviar o payload em dois formatos dependendo da versão/plano:

    Formato 1 (flat):
      {"event_type": "doc_signed", "token": "DOC_TOKEN", "signed_file": "URL"}

    Formato 2 (aninhado):
      {"event_type": "doc_signed", "document": {"token": "DOC_TOKEN", "signed_file": "URL"}}

    Retorna (event_type, doc_token, signed_file).
    """
    event_type = data.get("event_type", "")

    # Formato flat (mais comum)
    doc_token = data.get("token", "")
    signed_file = data.get("signed_file")

    # Formato aninhado
    if not doc_token and isinstance(data.get("document"), dict):
        doc = data["document"]
        doc_token = doc.get("token", "")
        if not signed_file:
            signed_file = doc.get("signed_file")

    return event_type, doc_token, signed_file


@method_decorator(csrf_exempt, name="dispatch")
class ZapSignWebhookView(APIView):
    """Recebe eventos do ZapSign via POST (um evento por documento).

    Endpoint público (AllowAny) — autenticidade verificada pelo doc_token:
    se o token não existir em DocumentoKit, a requisição é ignorada silenciosamente.
    Sempre retorna HTTP 200 para o ZapSign não retentar.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # LOG DIAGNÓSTICO: captura tudo que o ZapSign envia
        try:
            payload_str = json.dumps(dict(request.data), ensure_ascii=False, indent=2)
        except Exception:
            payload_str = str(request.data)
        logger.info(f"ZapSign webhook recebido — payload: {payload_str[:2000]}")

        event_type, doc_token, signed_file = _extrair_token_e_evento(request.data)

        if not doc_token:
            logger.warning("ZapSign webhook: token ausente no payload — ignorado")
            return Response({"detail": "ok"})

        extra_docs = request.data.get("extra_docs") or []
        logger.info(
            f"ZapSign webhook: event_type='{event_type}' token='{doc_token[:16]}…' "
            f"extra_docs={len(extra_docs)}"
        )

        # Busca por DocumentoKit (fluxo antigo — um doc ZapSign por DocumentoKit)
        doc_kit = (
            DocumentoKit.objects
            .select_related("kit__cliente")
            .filter(zapsign_doc_token=doc_token)
            .first()
        )

        if doc_kit:
            logger.info(
                f"ZapSign webhook: DocumentoKit #{doc_kit.id} ({doc_kit.tipo}) "
                f"encontrado para Kit #{doc_kit.kit_id}"
            )
            if event_type == "doc_signed":
                self._handle_signed(doc_kit, signed_file)
            elif event_type == "doc_refused":
                self._handle_refused_doc(doc_kit)
            else:
                logger.info(f"ZapSign webhook: evento '{event_type}' — ignorado")
            return Response({"detail": "ok"})

        # Busca pelo Kit (fluxo extra_docs — token do bundle armazenado no Kit)
        kit = Kit.objects.select_related("cliente").filter(zapsign_doc_token=doc_token).first()
        if kit:
            logger.info(
                f"ZapSign webhook (extra_docs): Kit #{kit.id} encontrado pelo doc_token"
            )
            if event_type == "doc_signed":
                self._handle_signed_bundle(kit, signed_file, extra_docs)
            elif event_type == "doc_refused":
                kit.zapsign_status = "refused"
                kit.save(update_fields=["zapsign_status", "atualizado_em"])
            return Response({"detail": "ok"})

        logger.warning(
            f"ZapSign webhook: nenhum DocumentoKit ou Kit com token '{doc_token[:16]}…' "
            f"encontrado no banco — ignorado"
        )
        return Response({"detail": "ok"})

    # ------------------------------------------------------------------

    def _handle_signed(self, doc_kit: DocumentoKit, signed_file: str | None):
        """Atualiza status do documento e baixa PDF assinado."""
        doc_kit.zapsign_status = "signed"
        doc_kit.save(update_fields=["zapsign_status"])
        invalidar_cache_status(doc_kit.zapsign_doc_token)

        kit = doc_kit.kit
        logger.info(f"Kit #{kit.id} — {doc_kit.tipo}: marcado como assinado")

        if signed_file:
            try:
                pdf_bytes = baixar_arquivo_assinado(signed_file)
                doc_kit.arquivo.delete(save=False)
                cliente_slug = slug_nome_cliente(kit.cliente.nome_completo or "")
                doc_kit.arquivo.save(
                    f"kits/{kit.id}/assinado_{doc_kit.tipo}_{cliente_slug}.pdf",
                    ContentFile(pdf_bytes),
                    save=True,
                )
                logger.info(
                    f"Kit #{kit.id} — {doc_kit.tipo}: PDF assinado salvo em {doc_kit.arquivo.name}"
                )
            except Exception as exc:
                logger.error(
                    f"Kit #{kit.id} — {doc_kit.tipo}: falha ao salvar PDF assinado — {exc}"
                )

        # Verifica se todos os documentos enviados ao ZapSign foram assinados
        sent_docs = kit.documentos.filter(zapsign_doc_token__isnull=False)
        all_signed = sent_docs.exists() and not sent_docs.exclude(zapsign_status="signed").exists()
        if all_signed:
            kit.status = "assinado"
            kit.zapsign_status = "signed"
            kit.save(update_fields=["status", "zapsign_status", "atualizado_em"])
            logger.info(f"Kit #{kit.id}: todos os documentos assinados — kit marcado como assinado")

    def _handle_refused_doc(self, doc_kit: DocumentoKit):
        doc_kit.zapsign_status = "refused"
        doc_kit.save(update_fields=["zapsign_status"])
        kit = doc_kit.kit
        kit.zapsign_status = "refused"
        kit.save(update_fields=["zapsign_status", "atualizado_em"])
        logger.info(f"Kit #{kit.id} — {doc_kit.tipo}: assinatura recusada")

    def _handle_signed_bundle(self, kit: Kit, signed_file: str | None, extra_docs: list):
        """Fluxo extra_docs: bundle assinado, um único evento para o kit inteiro.

        O payload do ZapSign inclui:
          - signed_file: URL do PDF assinado do documento principal
          - extra_docs[]: [{token, name, signed_file, ...}] para cada extra_doc

        O documento principal (index 0 em order_by("tipo")) recebe signed_file.
        Os extra_docs são mapeados pelo campo "name" (que definimos como
        get_tipo_display() no envio), independente da ordem em que o ZapSign
        os retorna no webhook.
        """
        docs = list(
            kit.documentos
            .exclude(tipo="assinado_zapsign")
            .order_by("tipo")
        )
        cliente_slug = slug_nome_cliente(kit.cliente.nome_completo or "")

        # Monta pares (DocumentoKit, url_signed)
        pares: list[tuple] = []

        # Documento principal → sempre docs[0] (mesmo que enviamos como principal)
        if signed_file and docs:
            pares.append((docs[0], signed_file))

        # Extra docs → mapeia por name (tipo_display) para não depender da ordem do ZapSign
        tipo_display_map = {doc.get_tipo_display(): doc for doc in docs[1:]}
        matched_by_name = False

        for extra in extra_docs or []:
            url = extra.get("signed_file")
            if not url:
                continue
            name = extra.get("name", "")
            doc = tipo_display_map.get(name)
            if doc:
                pares.append((doc, url))
                matched_by_name = True
            else:
                logger.warning(
                    f"Kit #{kit.id}: extra_doc name='{name}' não corresponde a "
                    f"nenhum DocumentoKit — esperados: {list(tipo_display_map.keys())}"
                )

        # Fallback posicional se ZapSign não retornou name nos extra_docs
        if extra_docs and not matched_by_name:
            logger.warning(
                f"Kit #{kit.id}: name-matching não funcionou — usando mapeamento posicional "
                f"(ZapSign pode não ter retornado o campo 'name' nos extra_docs)"
            )
            pares = []
            if signed_file and docs:
                pares.append((docs[0], signed_file))
            for i, extra in enumerate(extra_docs or []):
                idx = i + 1
                if idx < len(docs):
                    url = extra.get("signed_file")
                    if url:
                        pares.append((docs[idx], url))

        logger.info(
            f"Kit #{kit.id}: bundle assinado — {len(pares)} PDF(s) disponível(is) "
            f"de {len(docs)} DocumentoKit(s)"
        )

        # Baixa e salva cada PDF assinado individualmente
        ids_processados: set[int] = set()
        for doc, url in pares:
            try:
                pdf_bytes = baixar_arquivo_assinado(url)
                doc.arquivo.delete(save=False)
                doc.arquivo.save(
                    f"kits/{kit.id}/assinado_{doc.tipo}_{cliente_slug}.pdf",
                    ContentFile(pdf_bytes),
                    save=False,
                )
                doc.zapsign_status = "signed"
                doc.save(update_fields=["arquivo", "zapsign_status"])
                ids_processados.add(doc.id)
                logger.info(f"Kit #{kit.id} — {doc.tipo}: PDF assinado salvo em {doc.arquivo.name}")
            except Exception as exc:
                logger.error(f"Kit #{kit.id} — {doc.tipo}: falha ao salvar PDF assinado — {exc}")

        # Marca como signed os docs sem URL de assinatura (incomum, mas defensivo)
        for doc in docs:
            if doc.id not in ids_processados and doc.zapsign_status != "signed":
                doc.zapsign_status = "signed"
                doc.save(update_fields=["zapsign_status"])

        # Marca o kit
        kit.zapsign_status = "signed"
        kit.status = "assinado"
        kit.save(update_fields=["zapsign_status", "status", "atualizado_em"])
        logger.info(f"Kit #{kit.id}: marcado como assinado (bundle extra_docs)")

"""Webhook público para receber notificações de eventos do ZapSign."""
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
from .services_zapsign import baixar_arquivo_assinado

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

        logger.info(f"ZapSign webhook: event_type='{event_type}' token='{doc_token[:16]}…'")

        # Busca por DocumentoKit (novo formato — múltiplos documentos)
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

        # Fallback: busca pelo Kit direto (formato legado — PDF unificado)
        kit = Kit.objects.filter(zapsign_doc_token=doc_token).first()
        if kit:
            logger.info(
                f"ZapSign webhook (legado): Kit #{kit.id} encontrado pelo doc_token do kit"
            )
            if event_type == "doc_signed":
                self._handle_signed_legacy(kit, signed_file)
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

    def _handle_signed_legacy(self, kit: Kit, signed_file: str | None):
        """Processa doc_signed via token do Kit (fluxo extra_docs ou formato legado).

        Com o fluxo extra_docs, o ZapSign dispara um único evento com o token
        do documento principal (armazenado em Kit.zapsign_doc_token). Marca
        todos os DocumentoKit como assinados e salva o PDF assinado retornado
        (que pode ser somente o doc principal — comportamento a verificar em teste).
        """
        # Marca todos os DocumentoKit do kit como assinados
        kit.documentos.exclude(tipo="assinado_zapsign").update(zapsign_status="signed")
        kit.zapsign_status = "signed"
        kit.status = "assinado"
        kit.save(update_fields=["zapsign_status", "status", "atualizado_em"])
        logger.info(
            f"Kit #{kit.id}: marcado como assinado via ZapSign "
            f"(extra_docs / legado — signed_file={'sim' if signed_file else 'não'})"
        )

        if signed_file:
            try:
                pdf_bytes = baixar_arquivo_assinado(signed_file)
                # Remove qualquer PDF assinado anterior para evitar duplicata
                for doc in kit.documentos.filter(tipo="assinado_zapsign"):
                    doc.arquivo.delete(save=False)
                kit.documentos.filter(tipo="assinado_zapsign").delete()
                cliente_slug = slug_nome_cliente(kit.cliente.nome_completo or "")
                doc = DocumentoKit(kit=kit, tipo="assinado_zapsign")
                doc.arquivo.save(
                    f"kits/{kit.id}/assinado_{cliente_slug}.pdf",
                    ContentFile(pdf_bytes),
                    save=True,
                )
                logger.info(
                    f"Kit #{kit.id}: PDF assinado salvo em {doc.arquivo.name}"
                )
            except Exception as exc:
                logger.error(f"Kit #{kit.id}: falha ao salvar PDF assinado — {exc}")

"""Webhook público para receber notificações de eventos do ZapSign."""
import logging

from django.core.files.base import ContentFile
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DocumentoKit
from .services_documentos import slug_nome_cliente
from .services_zapsign import baixar_arquivo_assinado

logger = logging.getLogger(__name__)


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
        data = request.data
        event_type = data.get("event_type", "")
        doc_token = data.get("token", "")

        if not doc_token:
            return Response({"detail": "ok"})

        doc_kit = (
            DocumentoKit.objects
            .select_related("kit__cliente")
            .filter(zapsign_doc_token=doc_token)
            .first()
        )
        if not doc_kit:
            logger.debug(f"ZapSign webhook: token desconhecido ({doc_token[:12]}…) — ignorado")
            return Response({"detail": "ok"})

        if event_type == "doc_signed":
            self._handle_signed(doc_kit, data)
        elif event_type == "doc_refused":
            doc_kit.zapsign_status = "refused"
            doc_kit.save(update_fields=["zapsign_status"])
            kit = doc_kit.kit
            kit.zapsign_status = "refused"
            kit.save(update_fields=["zapsign_status", "atualizado_em"])
            logger.info(
                f"Kit #{kit.id} — {doc_kit.tipo}: assinatura recusada no ZapSign"
            )
        else:
            logger.debug(
                f"ZapSign webhook: evento '{event_type}' para doc {doc_kit.tipo} "
                f"(Kit #{doc_kit.kit_id}) — ignorado"
            )

        return Response({"detail": "ok"})

    def _handle_signed(self, doc_kit: DocumentoKit, data: dict):
        """Processa doc_signed: baixa PDF assinado, substitui arquivo, atualiza status."""
        doc_kit.zapsign_status = "signed"
        doc_kit.save(update_fields=["zapsign_status"])

        kit = doc_kit.kit
        logger.info(f"Kit #{kit.id} — {doc_kit.tipo}: assinado no ZapSign")

        signed_file_url = data.get("signed_file")
        if signed_file_url:
            try:
                pdf_bytes = baixar_arquivo_assinado(signed_file_url)
                # Substitui o arquivo existente pela versão assinada
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

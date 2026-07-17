"""Webhook público para receber notificações de eventos do ZapSign."""
import logging

from django.core.files.base import ContentFile
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DocumentoKit, Kit
from .services_documentos import slug_nome_cliente
from .services_zapsign import baixar_arquivo_assinado

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class ZapSignWebhookView(APIView):
    """Recebe eventos do ZapSign via POST.

    Endpoint público (AllowAny) — a autenticidade é verificada pelo doc_token:
    se o token não existir no banco, a requisição é ignorada silenciosamente
    (retorna 200 para o ZapSign não retentar).
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        event_type = data.get("event_type", "")
        doc_token = data.get("token", "")

        if not doc_token:
            return Response({"detail": "ok"})

        kit = Kit.objects.filter(zapsign_doc_token=doc_token).first()
        if not kit:
            logger.debug(f"ZapSign webhook: token desconhecido ({doc_token[:12]}…) — ignorado")
            return Response({"detail": "ok"})

        if event_type == "doc_signed":
            self._handle_signed(kit, data)
        elif event_type == "doc_refused":
            kit.zapsign_status = "refused"
            kit.save(update_fields=["zapsign_status", "atualizado_em"])
            logger.info(f"Kit #{kit.id}: assinatura recusada no ZapSign")
        else:
            logger.debug(f"ZapSign webhook: evento '{event_type}' para Kit #{kit.id} — ignorado")

        return Response({"detail": "ok"})

    def _handle_signed(self, kit: Kit, data: dict):
        """Processa doc_signed: baixa PDF assinado, salva e atualiza status do kit."""
        kit.zapsign_status = "signed"
        kit.status = "assinado"
        kit.save(update_fields=["zapsign_status", "status", "atualizado_em"])
        logger.info(f"Kit #{kit.id}: marcado como assinado via ZapSign")

        signed_file_url = data.get("signed_file")
        if not signed_file_url:
            logger.warning(f"Kit #{kit.id}: doc_signed sem signed_file URL")
            return

        try:
            pdf_bytes = baixar_arquivo_assinado(signed_file_url)
        except RuntimeError as exc:
            logger.error(f"Kit #{kit.id}: falha ao baixar PDF assinado — {exc}")
            return

        try:
            # Remove versão anterior assinada se existir
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
            logger.info(f"Kit #{kit.id}: PDF assinado salvo em {doc.arquivo.name}")
        except Exception as exc:
            logger.error(f"Kit #{kit.id}: falha ao salvar PDF assinado localmente — {exc}")

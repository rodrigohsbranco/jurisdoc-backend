"""Portal público de assinatura — link único entregue ao cliente.

Cada documento do kit é um documento independente no ZapSign (assinatura
individual por documento). Esta página é o único link compartilhado com o
cliente: ela lista os documentos, mostra o que já foi assinado e conduz ao
próximo pendente. Como o `redirect_link` de cada signatário aponta para cá,
o cliente volta ao portal a cada assinatura concluída.

A página é pública e identificada por um UUID não enumerável
(Kit.zapsign_portal_token); não expõe dados sensíveis do kit além do nome do
cliente e dos títulos dos documentos.
"""
from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

from .models import Kit
from .services_zapsign import documento_assinado_no_zapsign

logger = logging.getLogger(__name__)


class AssinaturaPortalView(TemplateView):
    """GET /assinar/<uuid:token>/ — lista os documentos e o próximo a assinar."""

    template_name = "kits/assinatura_portal.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)

        kit = get_object_or_404(
            Kit.objects.select_related("cliente"),
            zapsign_portal_token=kwargs["token"],
        )

        documentos = []
        for doc in kit.documentos.exclude(tipo="assinado_zapsign").order_by("tipo"):
            assinado = doc.zapsign_status == "signed"

            # O webhook é assíncrono: logo após assinar, o status local ainda pode
            # estar "pending". Confirma ao vivo no ZapSign para não oferecer de
            # novo um documento que o cliente acabou de assinar.
            if not assinado and doc.zapsign_doc_token:
                ao_vivo = documento_assinado_no_zapsign(doc.zapsign_doc_token)
                if ao_vivo is not None:
                    assinado = ao_vivo

            documentos.append({
                "titulo": doc.get_tipo_display(),
                "assinado": assinado,
                "sign_url": doc.zapsign_sign_url or "",
            })

        pendentes = [d for d in documentos if not d["assinado"] and d["sign_url"]]

        contexto.update({
            "kit": kit,
            "cliente_nome": (kit.cliente.nome_completo or "").strip(),
            "documentos": documentos,
            "total": len(documentos),
            "assinados": sum(1 for d in documentos if d["assinado"]),
            "proximo": pendentes[0] if pendentes else None,
            "concluido": bool(documentos) and not pendentes,
        })
        return contexto

"""Convergência do funil de assinatura e ciclo da esteira.

Um kit pode ser assinado por duas vias — digital (ZapSign) e presencial
(cliente analfabeto assina a rogo, o operador digitaliza e sobe o PDF). As duas
terminam no mesmo lugar: kit assinado e disponível na esteira para a aplicação
externa consumir.

Este módulo é o ÚNICO ponto que fecha uma assinatura. O `status = "assinado"`
era escrito em quatro lugares diferentes (action `assinar`, webhook do ZapSign,
fluxo legado de extra_docs e `mudar_status` do app FlowALR); com a promoção
automática para a esteira acoplada a esse momento, espalhar a regra significaria
que um quinto ponto futuro deixaria o kit preso fora da fila. Todos passam a
chamar `marcar_assinado()`.

Eixos independentes (ver Kit no models.py):
  status         → rascunho | acoes | finalizado | assinado   (produção)
  status_esteira → aguardando | na_esteira | concluido        (fila de saída)
"""
from __future__ import annotations

from pathlib import Path

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import DocumentoKit, Kit

# Um documento vale como prova de assinatura se veio assinado do ZapSign ou se é
# a digitalização do kit assinado à mão.
Q_ASSINADO = Q(zapsign_status="signed") | Q(tipo__in=["assinado_zapsign", "assinado_presencial"])


def documentos_assinados(kit: Kit):
    """Documentos que comprovam a assinatura do kit, por qualquer via.

    Na via digital cada DocumentoKit vira um documento no ZapSign e volta com
    `zapsign_status="signed"` e o PDF assinado no lugar do gerado; na presencial
    existe um único `assinado_presencial` com a digitalização.
    """
    return kit.documentos.filter(Q_ASSINADO).exclude(arquivo="")


def tem_prova_de_assinatura(kit: Kit) -> bool:
    """Há ao menos um arquivo assinado anexado ao kit?

    É o que separa "o operador clicou em assinado" de "o kit está assinado": sem
    arquivo não há o que a esteira entregue à aplicação externa.
    """
    return documentos_assinados(kit).exists()


@transaction.atomic
def marcar_assinado(kit: Kit, *, via: str = "") -> Kit:
    """Fecha a assinatura do kit e o disponibiliza para a aplicação externa.

    `via` registra por onde a assinatura veio quando o chamador sabe (webhook do
    ZapSign, upload presencial); quando vem vazio preserva o que já estava no
    kit. Assinar leva o kit a `aguardando` — daí em diante quem move a esteira
    é a aplicação externa.
    """
    campos: list[str] = []

    if via and kit.via_assinatura != via:
        kit.via_assinatura = via
        campos.append("via_assinatura")

    if kit.status != "assinado":
        kit.status = "assinado"
        campos.append("status")

    # Só disponibiliza uma vez: um kit que a aplicação externa já assumiu ou
    # baixou não volta para o começo da fila porque o webhook do ZapSign
    # reprocessou um evento repetido.
    if kit.status_esteira == "em_producao":
        kit.status_esteira = "aguardando"
        kit.entrou_esteira_em = timezone.now()
        campos += ["status_esteira", "entrou_esteira_em"]

    if campos:
        kit.save(update_fields=[*campos, "atualizado_em"])

    return kit


@transaction.atomic
def assumir_na_esteira(kit: Kit) -> bool:
    """A aplicação externa assume o kit e passa a processá-lo.

    Retorna False se o kit não estava `aguardando` — assumir de novo o que já
    foi assumido (ou já concluído) não é erro, só não muda nada.
    """
    if kit.status_esteira != "aguardando":
        return False

    kit.status_esteira = "na_esteira"
    kit.assumido_em = timezone.now()
    kit.save(update_fields=["status_esteira", "assumido_em", "atualizado_em"])
    return True


@transaction.atomic
def marcar_concluido(kit: Kit) -> bool:
    """Fecha o ciclo depois que a aplicação externa baixou o kit.

    Aceita tanto `aguardando` quanto `na_esteira`: a aplicação externa pode
    baixar direto, sem passar por `assumir`, e nesse caso o kit vai de uma vez
    até o fim. Retorna False quando não havia o que mudar — download repetido de
    um kit já concluído é operação normal, não erro.
    """
    if kit.status_esteira not in ("aguardando", "na_esteira"):
        return False

    agora = timezone.now()
    campos = ["status_esteira", "baixado_em", "atualizado_em"]

    # Baixar sem assumir ainda registra a passagem pelo estado intermediário —
    # sem isso, um kit concluído ficaria sem nenhuma data de quando a aplicação
    # externa o pegou.
    if kit.assumido_em is None:
        kit.assumido_em = agora
        campos.append("assumido_em")

    kit.status_esteira = "concluido"
    kit.baixado_em = agora
    kit.save(update_fields=campos)
    return True


def documentos_presenciais(kit: Kit):
    """As digitalizações já anexadas, na ordem em que foram enviadas."""
    return kit.documentos.filter(tipo="assinado_presencial").order_by("id")


def salvar_documentos_presenciais(kit: Kit, arquivos) -> list[DocumentoKit]:
    """Anexa digitalizações do kit assinado à mão, ACUMULANDO com as anteriores.

    O escritório colhe a assinatura peça por peça e digitaliza em partes, então
    cada envio soma ao que já existe — trocar tudo a cada upload faria o operador
    perder o que já tinha subido. Para remover, use `remover_documento_presencial`.

    O arquivo é renomeado para `kit_<id>_assinado_<n>.<ext>`: o nome que vem do
    scanner é longo e opaco, e a coluna `arquivo` é varchar(100) — nome previsível
    evita truncamento e deixa o diretório legível.
    """
    salvos: list[DocumentoKit] = []
    # Continua a numeração de onde parou, para não reciclar nomes de arquivos
    # que já foram removidos e podem estar referenciados em algum lugar.
    proximo = (documentos_presenciais(kit).count() or 0) + 1

    for arquivo in arquivos:
        extensao = Path(getattr(arquivo, "name", "") or "").suffix.lower() or ".pdf"
        doc = DocumentoKit(kit=kit, tipo="assinado_presencial")
        doc.arquivo.save(f"kit_{kit.id}_assinado_{proximo}{extensao}", arquivo, save=True)
        salvos.append(doc)
        proximo += 1

    return salvos


def remover_documento_presencial(kit: Kit, documento_id: int) -> bool:
    """Remove uma digitalização específica. False se ela não é deste kit.

    O arquivo em disco sai junto pelo signal `post_delete` (ver signals.py) —
    aqui basta apagar o registro.
    """
    doc = kit.documentos.filter(pk=documento_id, tipo="assinado_presencial").first()
    if doc is None:
        return False

    doc.delete()
    return True

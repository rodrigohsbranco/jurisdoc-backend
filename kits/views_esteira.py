"""Esteira: a fila de kits assinados que a aplicação externa consome.

Autenticação é a mesma já usada pelo app FlowALR — Client Credentials
(`POST /api/auth/app-token/` → JWT de serviço). Basta cadastrar um `AppClient`
próprio para a aplicação da esteira; nenhuma infraestrutura nova.

Ciclo:
  aguardando  → kit assinado e disponível para a aplicação externa assumir
  na_esteira  → a aplicação externa assumiu e está processando
  concluido   → a aplicação externa baixou

O download é o que conclui o kit. Um kit já concluído continua acessível e
continua baixando: repetir o download depois de uma falha de rede é operação
normal, não erro — só não muda o status de novo.
"""
from __future__ import annotations

import io
import logging
import zipfile

from django.core.files.storage import default_storage
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.service_auth import IsServiceClient, ServiceClientAuthentication

from .models import Kit
from .serializers_esteira import EsteiraKitDetailSerializer, EsteiraKitListSerializer
from .services_documentos import slug_nome_cliente
from .services_esteira import assumir_na_esteira, documentos_assinados, marcar_concluido

logger = logging.getLogger(__name__)

# Blocos que a aplicação externa pode pedir no download.
CONTEUDOS_VALIDOS = {"assinados", "anexos", "pessoais"}
CONTEUDO_PADRAO = "assinados"

# Cabeçalho oficial. `?incluir=` aceita os mesmos valores e existe para permitir
# testar o endpoint com um curl simples ou direto no navegador.
HEADER_CONTEUDO = "HTTP_X_ESTEIRA_CONTEUDO"


def _conteudos_pedidos(request) -> tuple[set[str], list[str]]:
    """Lê o que a aplicação externa pediu. Retorna (válidos, desconhecidos)."""
    bruto = request.META.get(HEADER_CONTEUDO) or request.query_params.get("incluir") or ""
    itens = [p.strip().lower() for p in bruto.split(",") if p.strip()]

    if not itens:
        return {CONTEUDO_PADRAO}, []

    validos = {i for i in itens if i in CONTEUDOS_VALIDOS}
    desconhecidos = [i for i in itens if i not in CONTEUDOS_VALIDOS]
    return validos, desconhecidos


def _iter_paths(valor) -> list[str]:
    """Normaliza os campos JSON de anexo, que têm duas formas no banco.

    `documentos_pessoais` guarda uma lista de strings; os demais (comprovantes,
    docs do rogado, das testemunhas, anexos das ações) guardam {path, name}.
    """
    paths: list[str] = []
    if not valor:
        return paths
    if isinstance(valor, dict):
        valor = [valor]
    for item in valor:
        if isinstance(item, str):
            paths.append(item)
        elif isinstance(item, dict) and item.get("path"):
            paths.append(item["path"])
    return paths


class EsteiraViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/app/esteira/ — kits prontos para a aplicação externa."""

    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceClient]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["tipo", "status_esteira", "via_assinatura"]
    search_fields = ["cliente__nome_completo", "cliente__cpf"]
    ordering_fields = ["entrou_esteira_em", "baixado_em"]
    ordering = ["entrou_esteira_em"]

    def get_queryset(self):
        """Kits já assinados — em qualquer fase da esteira, concluídos inclusive.

        Manter os concluídos acessíveis é o que permite repetir um download que
        falhou no meio. A listagem, essa sim, mostra por padrão só os que estão
        `aguardando`: é a fila de trabalho novo que a aplicação externa procura
        quando consulta a esteira.
        """
        qs = (
            Kit.objects
            .exclude(status_esteira="em_producao")
            .select_related("cliente")
            .prefetch_related("acoes", "documentos")
        )
        if self.action == "list" and "status_esteira" not in self.request.query_params:
            qs = qs.filter(status_esteira="aguardando")
        return qs

    def get_serializer_class(self):
        return EsteiraKitListSerializer if self.action == "list" else EsteiraKitDetailSerializer

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Baixa o kit em ZIP e o marca como concluído.

        O conteúdo vem do header `X-Esteira-Conteudo` (ou `?incluir=`), com um ou
        mais de: `assinados` (padrão), `anexos`, `pessoais`.
        """
        kit = self.get_object()
        conteudos, desconhecidos = _conteudos_pedidos(request)

        if desconhecidos:
            return Response(
                {
                    "detail": f"Conteúdo desconhecido: {', '.join(desconhecidos)}.",
                    "validos": sorted(CONTEUDOS_VALIDOS),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        buffer = io.BytesIO()
        incluidos = 0

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            if "assinados" in conteudos:
                for doc in documentos_assinados(kit):
                    incluidos += self._escrever(zf, f"assinados/{doc.tipo}", doc.arquivo.name)

            if "anexos" in conteudos:
                for acao in kit.acoes.all():
                    for campo in (
                        "historico_emprestimo_arquivos",
                        "historico_credito_arquivos",
                        "extrato_bancario_arquivos",
                    ):
                        rotulo = campo.replace("_arquivos", "")
                        for path in _iter_paths(getattr(acao, campo)):
                            incluidos += self._escrever(
                                zf, f"anexos/acao_{acao.id}/{rotulo}", path
                            )

            if "pessoais" in conteudos:
                c = kit.cliente
                for campo, pasta in (
                    ("documentos_pessoais", "cliente"),
                    ("comprovantes_residencia", "comprovantes"),
                    ("rogado_documentos", "rogado"),
                    ("testemunha1_documentos", "testemunha1"),
                    ("testemunha2_documentos", "testemunha2"),
                    ("responsavel_legal_documentos", "responsavel_legal"),
                ):
                    for path in _iter_paths(getattr(c, campo, None)):
                        incluidos += self._escrever(zf, f"pessoais/{pasta}", path)

        if incluidos == 0:
            return Response(
                {"detail": "Nenhum arquivo encontrado para o conteúdo solicitado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Só conclui com o ZIP inteiro montado: se a leitura de algum arquivo
        # estourasse no meio, o kit continuaria na esteira para nova tentativa.
        concluido_agora = marcar_concluido(kit)

        nome = f"kit_{kit.id}_{slug_nome_cliente(kit.cliente.nome_completo)}.zip"
        resposta = HttpResponse(buffer.getvalue(), content_type="application/zip")
        resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
        resposta["X-Esteira-Kit-Id"] = str(kit.id)
        resposta["X-Esteira-Status"] = kit.status_esteira
        resposta["X-Esteira-Arquivos"] = str(incluidos)

        logger.info(
            f"Esteira: kit #{kit.id} baixado por {request.user} "
            f"({incluidos} arquivo(s), conteudo={sorted(conteudos)}, "
            f"concluido_agora={concluido_agora})"
        )
        return resposta

    def _escrever(self, zf: zipfile.ZipFile, pasta: str, path: str) -> int:
        """Copia um arquivo do storage para dentro do ZIP. Retorna 1 se entrou.

        Arquivo faltando não derruba o download: um anexo perdido não pode
        impedir o kit inteiro de chegar na aplicação externa — fica no log.
        """
        if not path:
            return 0
        try:
            with default_storage.open(path, "rb") as fh:
                zf.writestr(self._nome_livre(zf, pasta, path.split("/")[-1]), fh.read())
            return 1
        except (FileNotFoundError, OSError) as exc:
            logger.warning(f"Esteira: arquivo ausente no storage '{path}' — {exc}")
            return 0

    @staticmethod
    def _nome_livre(zf: zipfile.ZipFile, pasta: str, nome: str) -> str:
        """Evita que dois arquivos de mesmo nome se sobrescrevam dentro do ZIP.

        Acontece de verdade: várias digitalizações do mesmo kit podem chegar do
        scanner como "digitalizar.pdf", e um `writestr` repetido faria a segunda
        substituir a primeira silenciosamente.
        """
        destino = f"{pasta}/{nome}"
        if destino not in zf.namelist():
            return destino

        base, _, ext = nome.rpartition(".")
        base, ext = (base, f".{ext}") if base else (nome, "")
        contador = 2
        while f"{pasta}/{base}_{contador}{ext}" in zf.namelist():
            contador += 1
        return f"{pasta}/{base}_{contador}{ext}"

    @action(detail=True, methods=["post"])
    def assumir(self, request, pk=None):
        """A aplicação externa assume o kit: `aguardando` → `na_esteira`.

        Existe como POST explícito, e não como efeito de um GET, para que
        inspecionar o kit (ou repetir uma listagem) não mude o estado dele.
        """
        kit = self.get_object()
        mudou = assumir_na_esteira(kit)
        logger.info(
            f"Esteira: kit #{kit.id} assumido por {request.user} (alterado={mudou})"
        )
        return Response(
            {
                "status_esteira": kit.status_esteira,
                "assumido_em": kit.assumido_em,
                "alterado": mudou,
            }
        )

    @action(detail=True, methods=["post"])
    def concluir(self, request, pk=None):
        """Confirmação explícita, para quem prefere não depender do download.

        A aplicação externa pode pedir `?incluir=` quantas vezes precisar e só
        chamar isto quando tiver gravado os arquivos do lado dela.
        """
        kit = self.get_object()
        mudou = marcar_concluido(kit)
        return Response(
            {
                "status_esteira": kit.status_esteira,
                "baixado_em": kit.baixado_em,
                "alterado": mudou,
            }
        )

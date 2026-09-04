"""Login do cliente final por código no WhatsApp (área "Sou cliente" do app).

Fluxo, todo orquestrado pelo JurisDoc — o app só repassa o que o cliente digita:

  1. `solicitar-codigo/`  telefone → confere se tem WhatsApp, gera o código,
     guarda o hash com prazo e envia pelo uazapi
  2. `validar-codigo/`    telefone + código → confere e devolve o MESMO token de
     sessão de 12h já usado pela área de dados

Depois do passo 2 nada muda: `meus-dados` e os uploads continuam idênticos.

Por que o código vive aqui e não no app: é o JurisDoc que guarda a identidade do
cliente. Se o código fosse gerado no app, não haveria como validá-lo aqui.

A conta nasce só com o telefone. A ficha (`Cliente`), que exige CPF único, só é
criada quando o cliente salva o cadastro — ver `views_cliente_app.py`.
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import response, status, throttling
from rest_framework.views import APIView

from accounts.service_auth import (
    IsServiceClient,
    ServiceClientAuthentication,
    issue_cliente_token,
)

from . import services_uazapi as uazapi
from .models import Cliente, CodigoAcessoCliente, ContaClienteApp
from .views_cliente_app import resolver_indicador

logger = logging.getLogger(__name__)

CODIGO_DIGITOS = 6
CODIGO_VALIDADE = timedelta(minutes=5)
MAX_TENTATIVAS = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gerar_codigo() -> str:
    """Código numérico com entropia criptográfica (nunca `random`)."""
    return f"{secrets.randbelow(10 ** CODIGO_DIGITOS):0{CODIGO_DIGITOS}d}"


def _mascarar(telefone: str) -> str:
    """"5548999998888" → "(48) *****-8888" — para a tela confirmar o destino."""
    if len(telefone) < 6:
        return "número informado"
    return f"({telefone[2:4]}) *****-{telefone[-4:]}"


def _texto_mensagem(codigo: str) -> str:
    from django.conf import settings

    nome = getattr(settings, "APP_CLIENTE_NOME", "") or "FlowALR"
    return (
        f"*{nome}*\n\n"
        f"Seu código de acesso é: *{codigo}*\n\n"
        f"Ele vale por {int(CODIGO_VALIDADE.total_seconds() // 60)} minutos. "
        "Não compartilhe este código com ninguém."
    )


def _conta_por_telefone(telefone: str, incluir_inativas: bool = False) -> ContaClienteApp | None:
    """Conta ligada ao número, considerando as duas grafias do nono dígito.

    `incluir_inativas` é usado só no login: o telefone é único, então uma conta
    desativada precisa ser encontrada para ser reativada — senão o número fica
    bloqueado para sempre.
    """
    qs = ContaClienteApp.objects.select_related("cliente").filter(
        telefone__in=uazapi.variantes_telefone(telefone)
    )
    if not incluir_inativas:
        qs = qs.filter(is_active=True)
    return qs.first()


def _ficha_sugerida(telefone: str) -> Cliente | None:
    """Ficha do escritório cujo telefone bate com o número autenticado.

    Só é oferecida DEPOIS que o cliente prova ser dono do número, validando o
    código — mostrar antes revelaria o nome de um cliente a quem digitasse o
    telefone dele. A busca usa os 8 últimos dígitos para não varrer a tabela e
    depois compara já normalizado.
    """
    variantes = set(uazapi.variantes_telefone(telefone))
    if not variantes or len(telefone) < 4:
        return None

    # `Cliente.telefone` é texto livre e costuma vir com máscara ("(11) 96666-5555"),
    # então não dá para casar dígitos direto no banco. Os 4 últimos dígitos são o
    # maior trecho que nenhum formato quebra — usamos como peneira e comparamos já
    # normalizado em Python.
    candidatos = (
        Cliente.objects
        .filter(is_active=True, telefone__contains=telefone[-4:], conta_app__isnull=True)
        .only("id", "nome_completo", "telefone")[:200]
    )
    for cliente in candidatos:
        normalizado = uazapi.normalizar_telefone(cliente.telefone)
        if normalizado and set(uazapi.variantes_telefone(normalizado)) & variantes:
            return cliente
    return None


def _payload_sessao(conta: ContaClienteApp) -> dict:
    token, expira_em = issue_cliente_token(conta.id)
    dados = {
        "token": token,
        "expira_em": expira_em,
        "cliente_id": conta.cliente_id,
        "cadastro_pendente": conta.cliente_id is None,
        "indicado_por_id": conta.indicado_por_id,
        "vinculo_sugerido": None,
    }

    if conta.cliente_id is None and not conta.vinculo_recusado:
        ficha = _ficha_sugerida(conta.telefone or "")
        if ficha is not None:
            dados["vinculo_sugerido"] = {
                "cliente_id": ficha.id,
                "nome_completo": ficha.nome_completo,
            }
    return dados


# ---------------------------------------------------------------------------
# Throttles — por telefone, não por IP (o app chama sempre do mesmo servidor)
# ---------------------------------------------------------------------------

class _ThrottlePorTelefone(throttling.SimpleRateThrottle):
    def get_cache_key(self, request, view):
        bruto = (request.data or {}).get("telefone")
        alvo = uazapi.normalizar_telefone(bruto) or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": alvo}


class SolicitarCodigoThrottle(_ThrottlePorTelefone):
    scope = "cliente_app_codigo_envio"


class ValidarCodigoThrottle(_ThrottlePorTelefone):
    scope = "cliente_app_codigo_validacao"


class _BaseWhatsAppView(APIView):
    """Pré-sessão: autenticado pelo token de serviço do app."""

    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceClient]


# ---------------------------------------------------------------------------
# Passo 1 — pedir o código
# ---------------------------------------------------------------------------

class SolicitarCodigoView(_BaseWhatsAppView):
    """POST /api/app/cliente/whatsapp/solicitar-codigo/ — body {telefone}."""

    throttle_classes = [SolicitarCodigoThrottle]

    def post(self, request):
        bruto = (request.data or {}).get("telefone")
        telefone = uazapi.normalizar_telefone(bruto)
        if not telefone:
            return response.Response(
                {"detail": "Informe um número de telefone válido com DDD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            info = uazapi.verificar_numero(telefone)
        except uazapi.NumeroSemWhatsAppError:
            return response.Response(
                {
                    "detail": "Este número não tem WhatsApp. Confira o número informado.",
                    "motivo": "sem_whatsapp",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except uazapi.RestricaoWhatsAppError as exc:
            return self._indisponivel(telefone, str(exc))
        except uazapi.UazapiError as exc:
            logger.error(f"Código de acesso: falha ao verificar número — {exc}")
            return self._indisponivel(telefone, str(exc))

        canonico = info["telefone"]
        codigo = _gerar_codigo()

        registro = CodigoAcessoCliente(
            telefone=canonico,
            expira_em=timezone.now() + CODIGO_VALIDADE,
        )
        registro.set_codigo(codigo)

        try:
            uazapi.enviar_texto(canonico, _texto_mensagem(codigo))
        except uazapi.RestricaoWhatsAppError as exc:
            return self._indisponivel(canonico, str(exc))
        except uazapi.UazapiError as exc:
            logger.error(f"Código de acesso: falha no envio — {exc}")
            return self._indisponivel(canonico, str(exc))

        # Só persiste depois do envio: código guardado sem mensagem entregue
        # deixaria o cliente esperando por algo que nunca chegou.
        registro.save()
        CodigoAcessoCliente.objects.filter(
            telefone=canonico, usado_em__isnull=True
        ).exclude(pk=registro.pk).update(usado_em=timezone.now())

        logger.info(f"Código de acesso enviado para {_mascarar(canonico)}")
        return response.Response(
            {
                "enviado": True,
                "telefone": canonico,
                "telefone_mascarado": _mascarar(canonico),
                "expira_em": int(CODIGO_VALIDADE.total_seconds()),
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _indisponivel(telefone: str, detalhe: str):
        """503 + informa se aquele número tem acesso alternativo configurado."""
        conta = _conta_por_telefone(telefone)
        return response.Response(
            {
                "detail": detalhe,
                "motivo": "whatsapp_indisponivel",
                "acesso_alternativo_disponivel": bool(conta and conta.email and conta.senha_hash),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


# ---------------------------------------------------------------------------
# Passo 2 — validar o código
# ---------------------------------------------------------------------------

class ValidarCodigoView(_BaseWhatsAppView):
    """POST /api/app/cliente/whatsapp/validar-codigo/ — body {telefone, codigo}.

    Sempre HTTP 200 quando o token de serviço é válido; `valido` diz o resultado.
    Cria a conta no primeiro acesso — sem ficha ainda (ela exige CPF).
    """

    throttle_classes = [ValidarCodigoThrottle]

    def post(self, request):
        dados = request.data or {}
        telefone = uazapi.normalizar_telefone(dados.get("telefone"))
        codigo = str(dados.get("codigo") or "").strip()

        if not telefone or not codigo:
            return self._invalido()

        agora = timezone.now()
        registro = (
            CodigoAcessoCliente.objects
            .filter(
                telefone__in=uazapi.variantes_telefone(telefone),
                usado_em__isnull=True,
                expira_em__gt=agora,
            )
            .order_by("-criado_em")
            .first()
        )

        if registro is None:
            return self._invalido("codigo_expirado")

        if registro.tentativas >= MAX_TENTATIVAS:
            registro.usado_em = agora  # queima o código: força pedir outro
            registro.save(update_fields=["usado_em"])
            logger.warning(f"Código de acesso: tentativas esgotadas para {_mascarar(telefone)}")
            return self._invalido("tentativas_excedidas")

        if not registro.confere(codigo):
            registro.tentativas += 1
            registro.save(update_fields=["tentativas"])
            return self._invalido(
                restantes=max(0, MAX_TENTATIVAS - registro.tentativas)
            )

        registro.usado_em = agora
        registro.save(update_fields=["usado_em"])

        conta = self._obter_ou_criar_conta(registro.telefone)
        if conta is None:
            return response.Response(
                {"detail": "Não foi possível iniciar a sessão. Tente novamente."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Ficha desativada pelo escritório: recusa aqui, e não a cada requisição.
        # Sem isto o login "funciona" (o token é emitido) mas toda chamada
        # seguinte falha na autenticação, deixando o cliente sem entender o
        # motivo. Contas sem ficha seguem normalmente — é o estado de quem
        # ainda vai se cadastrar.
        if conta.cliente_id and not conta.cliente.is_active:
            logger.info(
                f"Login recusado para a conta #{conta.id}: ficha #{conta.cliente_id} inativa"
            )
            return response.Response(
                {
                    "valido": False,
                    "motivo": "cadastro_inativo",
                    "detail": (
                        "Seu cadastro está inativo. Entre em contato com o "
                        "escritório para reativar o acesso."
                    ),
                },
                status=status.HTTP_200_OK,
            )

        campos = ["ultimo_login_em"]
        conta.ultimo_login_em = agora

        # Quem enviou o link do pré-cadastro: guardado no primeiro acesso para
        # que o kit gerado depois caia na produção desse colaborador.
        if not conta.indicado_por_id:
            indicador = resolver_indicador(dados.get("indicado_por_id"))
            if indicador is not None:
                conta.indicado_por = indicador
                campos.append("indicado_por")
                logger.info(f"Conta #{conta.id}: pré-cadastro indicado por {indicador.username}")

        conta.save(update_fields=campos)

        logger.info(f"Cliente autenticado por WhatsApp: conta #{conta.id}")
        return response.Response(
            {"valido": True, **_payload_sessao(conta)}, status=status.HTTP_200_OK
        )

    @staticmethod
    def _obter_ou_criar_conta(telefone: str) -> ContaClienteApp | None:
        """Devolve a conta do número, reativando a que existir.

        Quem acabou de provar que é dono do telefone tem direito de voltar. Uma
        conta desativada (o cliente excluiu a própria ficha, por exemplo) é
        reativada em vez de bloquear o número: como `telefone` é único, tentar
        criar outra esbarraria na restrição e o cliente ficaria sem acesso para
        sempre.
        """
        conta = _conta_por_telefone(telefone, incluir_inativas=True)
        if conta is not None:
            if not conta.is_active:
                conta.is_active = True
                conta.save(update_fields=["is_active"])
                logger.info(f"Conta #{conta.id} reativada no login por WhatsApp")
            return conta
        try:
            with transaction.atomic():
                return ContaClienteApp.objects.create(telefone=telefone)
        except IntegrityError:
            # Corrida entre duas validações do mesmo número
            return _conta_por_telefone(telefone, incluir_inativas=True)

    @staticmethod
    def _invalido(motivo: str = "codigo_invalido", restantes: int | None = None):
        corpo = {"valido": False, "motivo": motivo}
        if restantes is not None:
            corpo["tentativas_restantes"] = restantes
        return response.Response(corpo, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Diagnóstico (para o escritório, não para o cliente)
# ---------------------------------------------------------------------------

class DiagnosticoWhatsAppView(_BaseWhatsAppView):
    """GET /api/app/cliente/whatsapp/diagnostico/ — instância e teto de conversas."""

    def get(self, request):
        try:
            return response.Response(
                {"instancia": uazapi.status_instancia(), "limites": uazapi.limites_mensagens()}
            )
        except uazapi.UazapiError as exc:
            return response.Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

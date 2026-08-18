"""Área "Sou cliente" do app FlowALR — autoatendimento do cliente final.

O cliente se cadastra no app, preenche os próprios dados e para por aí: não vê
ações, advogados nem kit final. O objetivo é adiantar o cadastro para o advogado
que depois monta o kit.

Dois níveis de autenticação:
  - registrar / login / alterar-senha → token de serviço do app (IsServiceClient),
    porque ainda não há sessão de cliente
  - meus-dados e uploads → token de sessão do cliente (IsClienteApp), sempre
    resolvido para o próprio cadastro, nunca por id vindo da requisição

Decisões de produto (tomadas pelo escritório em 2026-08-17):
  - CPF já existente no JurisDoc é VINCULADO à conta nova, conferindo nome
    completo + data de nascimento. Não há verificação por e-mail.
  - Troca de senha esquecida é feita com CPF + data de nascimento, sem e-mail.
  - O pré-cadastro cria um Kit em rascunho para o escritório enxergar a demanda.
  - O cliente só exclui a própria ficha enquanto não houver kit em andamento.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import decorators, exceptions, response, status, throttling
from rest_framework.views import APIView

from accounts.service_auth import (
    ClienteAppAuthentication,
    IsClienteApp,
    IsServiceClient,
    ServiceClientAuthentication,
    issue_cliente_token,
)

from .models import Cliente, ContaClienteApp
from .serializers import ClienteSerializer
from .validators import validate_cpf
from .views_app import ClienteAppViewSet

logger = logging.getLogger(__name__)

SENHA_MIN = 6
_APP_SYSTEM_USERNAME = "app_flowalr"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _so_digitos(valor: str) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _normalizar_nome(nome: str) -> str:
    """Caixa alta, sem acento e sem espaço duplicado — para comparar nomes."""
    texto = unicodedata.normalize("NFKD", str(nome or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.upper().split())


def _data_iso(valor: str) -> str | None:
    """Aceita apenas YYYY-MM-DD dentro de um intervalo plausível.

    Sem isso, um valor malformado chega ao banco e vira erro 500 em vez de um
    400 explicando o problema para o cliente.
    """
    try:
        data = date.fromisoformat(str(valor).strip())
    except (TypeError, ValueError):
        return None
    if not (date(1900, 1, 1) <= data <= date.today()):
        return None
    return data.isoformat()


def _cpf_valido(cpf: str) -> bool:
    """Valida o CPF do autocadastro.

    Além do validador do projeto, barra sequências de dígito repetido: o
    `python-stdnum` aceita "11111111111" (o dígito verificador fecha), o que
    passa despercebido quando é o operador quem digita, mas vira porta de
    cadastro-lixo quando o próprio cliente se registra.
    """
    if len(set(cpf)) == 1:
        return False
    try:
        validate_cpf(cpf)
    except Exception:
        return False
    return True


def _resumo_cliente(cliente: Cliente) -> dict:
    return {
        "id": cliente.id,
        "nome_completo": cliente.nome_completo,
        "cpf": cliente.cpf,
    }


def _criar_kit_rascunho(cliente: Cliente) -> int | None:
    """Cria o kit em rascunho do pré-cadastro, quando faz sentido.

    Não cria quando o cliente já tem qualquer kit: se o escritório já abriu um
    caso para ele, um rascunho novo só polui a lista de produção.

    Falha aqui não derruba o cadastro — o kit é conveniência para o escritório,
    não parte da identidade do cliente. O savepoint é o que garante isso: sem
    ele, um erro de banco aqui dentro invalidaria a transação inteira do
    registro, e o cadastro seria perdido junto.
    """
    from kits.models import Kit

    try:
        with transaction.atomic():
            if Kit.objects.filter(cliente=cliente).exists():
                return None

            User = get_user_model()
            operador = User.objects.filter(username=_APP_SYSTEM_USERNAME).first()
            if operador is None:
                logger.error(
                    f"Kit do pré-cadastro não criado: usuário '{_APP_SYSTEM_USERNAME}' não existe."
                )
                return None

            kit = Kit.objects.create(
                cliente=cliente,
                criado_por=operador,
                tipo="bancario",
                status="rascunho",
                origem="app",
                app_criado_por_nome=f"Pré-cadastro — {cliente.nome_completo}",
            )
            return kit.id
    except Exception as exc:
        logger.error(f"Falha ao criar kit do pré-cadastro do cliente #{cliente.id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Throttles (o app chama sempre do mesmo IP — chaveamos por CPF/e-mail)
# ---------------------------------------------------------------------------

class _ThrottlePorCampo(throttling.SimpleRateThrottle):
    campo = "email"

    def get_cache_key(self, request, view):
        valor = str((request.data or {}).get(self.campo) or "").strip().lower()[:150]
        return self.cache_format % {
            "scope": self.scope,
            "ident": valor or self.get_ident(request),
        }


class RegistroThrottle(_ThrottlePorCampo):
    scope = "cliente_app_registro"
    campo = "cpf"


class LoginClienteThrottle(_ThrottlePorCampo):
    scope = "cliente_app_login"
    campo = "email"


class SenhaClienteThrottle(_ThrottlePorCampo):
    scope = "cliente_app_senha"
    campo = "cpf"


class _BaseClienteAuthView(APIView):
    """Endpoints pré-sessão: autenticados pelo token de serviço do app."""

    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceClient]


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

class RegistrarClienteView(_BaseClienteAuthView):
    """POST /api/app/cliente/registrar/

    Body: {nome_completo, cpf, data_nascimento (YYYY-MM-DD), email, senha}

    CPF novo   → cria o cadastro (origem="app_cliente") + conta + kit rascunho.
    CPF já existente → vincula à ficha, conferindo nome completo e, quando a
    ficha tiver data de nascimento, também a data.
    """

    throttle_classes = [RegistroThrottle]

    def post(self, request):
        dados = request.data or {}
        nome = str(dados.get("nome_completo") or "").strip()
        cpf = _so_digitos(dados.get("cpf"))
        email = str(dados.get("email") or "").strip().lower()
        senha = str(dados.get("senha") or "")
        data_nascimento = _data_iso(dados.get("data_nascimento"))

        erros = {}
        if len(nome.split()) < 2:
            erros["nome_completo"] = "Informe o nome completo."
        if not _cpf_valido(cpf):
            erros["cpf"] = "CPF inválido."
        if "@" not in email or "." not in email.split("@")[-1]:
            erros["email"] = "E-mail inválido."
        if len(senha) < SENHA_MIN:
            erros["senha"] = f"A senha deve ter ao menos {SENHA_MIN} caracteres."
        if not data_nascimento:
            erros["data_nascimento"] = "Informe a data de nascimento no formato AAAA-MM-DD."
        if erros:
            return response.Response(erros, status=status.HTTP_400_BAD_REQUEST)

        if ContaClienteApp.objects.filter(email__iexact=email).exists():
            return response.Response(
                {"detail": "Já existe uma conta com este e-mail. Faça login."},
                status=status.HTTP_409_CONFLICT,
            )

        cliente = Cliente.objects.filter(cpf=cpf).first()
        vinculou_ficha_existente = False

        if cliente is None:
            novo = Cliente(
                nome_completo=nome,
                cpf=cpf,
                data_nascimento=data_nascimento,
                origem="app_cliente",
            )
            novo.save()
            cliente = novo
            logger.info(f"Pré-cadastro: cliente #{cliente.id} criado pelo app (CPF {cpf[:3]}***)")
        else:
            if ContaClienteApp.objects.filter(cliente=cliente).exists():
                return response.Response(
                    {"detail": "Já existe uma conta para este CPF. Faça login ou altere a senha."},
                    status=status.HTTP_409_CONFLICT,
                )

            # Confere nome; a data entra como segundo fator quando a ficha tem uma
            if _normalizar_nome(cliente.nome_completo) != _normalizar_nome(nome):
                logger.warning(f"Pré-cadastro: nome não confere para o CPF {cpf[:3]}***")
                return response.Response(
                    {"detail": "Os dados informados não conferem com o cadastro. Procure o escritório."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if cliente.data_nascimento and str(cliente.data_nascimento) != data_nascimento:
                logger.warning(f"Pré-cadastro: data de nascimento não confere para o CPF {cpf[:3]}***")
                return response.Response(
                    {"detail": "Os dados informados não conferem com o cadastro. Procure o escritório."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            campos = []
            if not cliente.is_active:
                cliente.is_active = True
                campos.append("is_active")
            if not cliente.data_nascimento:
                cliente.data_nascimento = data_nascimento
                campos.append("data_nascimento")
            if campos:
                cliente.save(update_fields=campos)

            vinculou_ficha_existente = True
            logger.info(
                f"Pré-cadastro: conta vinculada à ficha existente #{cliente.id} (CPF {cpf[:3]}***)"
            )

        conta = ContaClienteApp(
            cliente=cliente,
            email=email,
            vinculada_a_ficha_existente=vinculou_ficha_existente,
        )
        conta.set_senha(senha)
        try:
            conta.save()
        except IntegrityError:
            # Corrida entre duas tentativas com o mesmo e-mail/CPF: o índice
            # único do banco é a autoridade final, não a checagem acima.
            logger.warning(f"Pré-cadastro: conflito de unicidade para '{email[:40]}'")
            return response.Response(
                {"detail": "Já existe uma conta com estes dados. Faça login."},
                status=status.HTTP_409_CONFLICT,
            )

        kit_id = _criar_kit_rascunho(cliente)
        token, expira_em = issue_cliente_token(conta.id)

        return response.Response(
            {
                "token": token,
                "expira_em": expira_em,
                "cliente": _resumo_cliente(cliente),
                "kit_id": kit_id,
                "vinculado_a_cadastro_existente": vinculou_ficha_existente,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class LoginClienteView(_BaseClienteAuthView):
    """POST /api/app/cliente/login/ — body {email, senha}.

    Sempre HTTP 200: `valido` diz se a credencial do cliente confere. Um 401
    aqui significa que o token de serviço do APP está inválido.
    """

    throttle_classes = [LoginClienteThrottle]

    def post(self, request):
        dados = request.data or {}
        email = str(dados.get("email") or "").strip().lower()
        senha = str(dados.get("senha") or "")

        conta = (
            ContaClienteApp.objects
            .select_related("cliente")
            .filter(email__iexact=email, is_active=True, cliente__is_active=True)
            .first()
        )

        if conta is None or not conta.checar_senha(senha):
            logger.info(f"Login de cliente recusado para '{email[:40]}'")
            return response.Response(
                {"valido": False, "motivo": "credenciais_invalidas"},
                status=status.HTTP_200_OK,
            )

        conta.ultimo_login_em = timezone.now()
        conta.save(update_fields=["ultimo_login_em"])

        token, expira_em = issue_cliente_token(conta.id)
        return response.Response(
            {
                "valido": True,
                "token": token,
                "expira_em": expira_em,
                "cliente": _resumo_cliente(conta.cliente),
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Troca de senha esquecida
# ---------------------------------------------------------------------------

class AlterarSenhaClienteView(_BaseClienteAuthView):
    """POST /api/app/cliente/alterar-senha/ — body {cpf, data_nascimento, nova_senha}.

    Sem e-mail de verificação, por decisão do escritório: a identidade é provada
    por CPF + data de nascimento. Só funciona quando a ficha tem data de
    nascimento registrada — sem ela não há o que conferir, e o cliente é
    orientado a procurar o escritório.
    """

    throttle_classes = [SenhaClienteThrottle]

    def post(self, request):
        dados = request.data or {}
        cpf = _so_digitos(dados.get("cpf"))
        data_nascimento = _data_iso(dados.get("data_nascimento"))
        nova_senha = str(dados.get("nova_senha") or "")

        if len(nova_senha) < SENHA_MIN:
            return response.Response(
                {"nova_senha": f"A senha deve ter ao menos {SENHA_MIN} caracteres."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conta = (
            ContaClienteApp.objects
            .select_related("cliente")
            .filter(cliente__cpf=cpf, is_active=True, cliente__is_active=True)
            .first()
        )

        # Resposta única para conta inexistente e dados que não conferem — não
        # revela quais CPFs têm conta no app.
        generico = response.Response(
            {"detail": "Os dados informados não conferem. Procure o escritório."},
            status=status.HTTP_400_BAD_REQUEST,
        )

        if conta is None or data_nascimento is None:
            return generico

        if not conta.cliente.data_nascimento:
            logger.info(f"Troca de senha bloqueada: ficha sem data de nascimento (CPF {cpf[:3]}***)")
            return response.Response(
                {"detail": "Não é possível alterar a senha automaticamente. Procure o escritório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if str(conta.cliente.data_nascimento) != data_nascimento:
            return generico

        conta.set_senha(nova_senha)
        conta.senha_alterada_em = timezone.now()
        conta.save(update_fields=["senha_hash", "senha_alterada_em"])
        logger.info(f"Senha alterada pelo app para o cliente #{conta.cliente_id}")

        token, expira_em = issue_cliente_token(conta.id)
        return response.Response(
            {
                "alterada": True,
                "token": token,
                "expira_em": expira_em,
                "cliente": _resumo_cliente(conta.cliente),
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Meus dados — herda os uploads do viewset do app, mas travado no próprio cadastro
# ---------------------------------------------------------------------------

class MeusDadosSerializer(ClienteSerializer):
    """Mesmos campos do cadastro, mas com a identidade travada.

    `cpf` é a chave da ficha: se o cliente pudesse alterá-lo, escreveria por cima
    do cadastro de outra pessoa (ou colidiria com o índice único). `origem` e
    `is_active` também ficam de fora — são controle do escritório.
    """

    class Meta(ClienteSerializer.Meta):
        read_only_fields = list(
            getattr(ClienteSerializer.Meta, "read_only_fields", []) or []
        ) + ["cpf", "origem", "is_active", "criado_em", "atualizado_em"]


class MeusDadosClienteViewSet(ClienteAppViewSet):
    """CRUD do próprio cadastro, para o cliente final.

    Herda de `ClienteAppViewSet` para reaproveitar todas as actions de upload e
    remoção de arquivos já validadas em produção. O que muda:
      - autenticação/permissão: sessão do cliente, não token de serviço admin
      - `get_object()` ignora o id da URL e devolve sempre o cliente da sessão
      - operações que atravessam cadastros (listar, criar, buscar por CPF,
        restaurar) ficam bloqueadas
    """

    authentication_classes = [ClienteAppAuthentication]
    permission_classes = [IsClienteApp]
    serializer_class = MeusDadosSerializer

    def get_serializer_class(self):
        return MeusDadosSerializer

    def get_queryset(self):
        return Cliente.objects.filter(pk=self.request.user.cliente.pk)

    def get_object(self):
        """Sempre o cliente da sessão — id divergente na URL é recusado."""
        cliente = self.request.user.cliente
        pk = self.kwargs.get("pk")
        if pk is not None and str(pk) != str(cliente.pk):
            raise exceptions.PermissionDenied("Você só pode acessar o seu próprio cadastro.")
        return cliente

    # ── Operações que atravessam cadastros: bloqueadas ──

    def _bloqueado(self, *args, **kwargs):
        raise exceptions.PermissionDenied("Operação não disponível para o cliente.")

    list = _bloqueado
    create = _bloqueado

    @decorators.action(detail=False, methods=["get"], url_path="buscar-por-cpf")
    def buscar_por_cpf(self, request):
        raise exceptions.PermissionDenied("Operação não disponível para o cliente.")

    @decorators.action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        raise exceptions.PermissionDenied("Operação não disponível para o cliente.")

    def destroy(self, request, *args, **kwargs):
        """Exclui o próprio cadastro — só enquanto o escritório não tiver tocado nele.

        Bloqueia diante de QUALQUER kit que não seja o rascunho gerado pelo
        próprio pré-cadastro: um rascunho que o escritório abriu já representa
        trabalho iniciado, e o cliente não pode apagá-lo pelo app.
        """
        from kits.models import Kit

        cliente = self.get_object()
        kits = Kit.objects.filter(cliente=cliente)
        rascunhos_do_app = kits.filter(status="rascunho", origem="app")

        if kits.exclude(pk__in=rascunhos_do_app.values("pk")).exists():
            return response.Response(
                {
                    "detail": (
                        "Seu cadastro já está vinculado a um atendimento do escritório e "
                        "não pode ser excluído pelo app. Solicite a exclusão ao escritório."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            rascunhos_do_app.delete()
            cliente.is_active = False
            cliente.save(update_fields=["is_active"])
            ContaClienteApp.objects.filter(cliente=cliente).update(is_active=False)

        logger.info(f"Cliente #{cliente.id} excluiu o próprio pré-cadastro pelo app")
        return response.Response(status=status.HTTP_204_NO_CONTENT)

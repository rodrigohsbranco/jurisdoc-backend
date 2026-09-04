"""Área "Sou cliente" do app FlowALR — autoatendimento do cliente final.

O cliente se cadastra no app, preenche os próprios dados e para por aí: não vê
ações, advogados nem kit final. O objetivo é adiantar o cadastro para o advogado
que depois monta o kit.

A porta de entrada é o código por WhatsApp (`views_cliente_whatsapp.py`).
Aqui ficam a área de dados e o ACESSO ALTERNATIVO — e-mail e senha, usados só
quando o WhatsApp falha.

Dois níveis de autenticação:
  - login / alterar-senha → token de serviço do app (IsServiceClient), porque
    ainda não há sessão de cliente
  - meus-dados e uploads → token de sessão do cliente (IsClienteApp), sempre
    resolvido para o próprio cadastro, nunca por id vindo da requisição

Decisões de produto (escritório, 2026-08-17 e 2026-08-28):
  - O telefone é a identidade; a ficha (`Cliente`) só nasce quando o cliente
    salva o cadastro, porque o CPF é obrigatório e único no JurisDoc.
  - Ficha existente do escritório é oferecida para vínculo apenas DEPOIS que o
    código do WhatsApp é validado — antes disso o nome não é revelado.
  - Troca de senha do acesso alternativo é feita com CPF + data de nascimento.
  - O pré-cadastro cria um Kit em rascunho para o escritório enxergar a demanda.
  - O cliente só exclui a própria ficha enquanto o escritório não a tiver tocado.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
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

from .models import CadastroAppEnviado, Cliente, ContaClienteApp
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


def _resumo_cliente(cliente: Cliente | None) -> dict | None:
    """Resumo da ficha. `None` quando a conta ainda não tem cadastro criado."""
    if cliente is None:
        return None
    return {
        "id": cliente.id,
        "nome_completo": cliente.nome_completo,
        "cpf": cliente.cpf,
    }


def resolver_indicador(valor) -> "object | None":
    """Usuário do JurisDoc que enviou o link do pré-cadastro.

    O app conhece esse id porque o SSO (`/api/app/auth/validar-credenciais/`)
    devolve o `id` do colaborador. Valor ausente ou desconhecido não é erro: o
    kit simplesmente cai para o usuário de sistema do app.
    """
    if valor in (None, "", 0):
        return None
    User = get_user_model()
    try:
        return User.objects.filter(pk=int(valor), is_active=True).first()
    except (TypeError, ValueError):
        return None


def _criar_kit_rascunho(cliente: Cliente, indicado_por=None) -> int | None:
    """Cria o kit em rascunho do pré-cadastro, quando faz sentido.

    Não cria quando o cliente já tem qualquer kit: se o escritório já abriu um
    caso para ele, um rascunho novo só polui a lista de produção.

    `criado_por` define quem enxerga o kit na produção: admins veem todos, e os
    demais só os próprios. Por isso o kit fica no nome de quem enviou o link,
    quando o app informa — assim o colaborador acompanha o pré-cadastro que ele
    mesmo originou. Sem essa informação, cai para o usuário de sistema do app.

    Falha aqui não derruba o cadastro — o kit é conveniência para o escritório,
    não parte da identidade do cliente. O savepoint é o que garante isso: sem
    ele, um erro de banco aqui dentro invalidaria a transação inteira do
    cadastro, e a ficha seria perdida junto.
    """
    from kits.models import Kit

    try:
        with transaction.atomic():
            if Kit.objects.filter(cliente=cliente).exists():
                return None

            User = get_user_model()
            dono = indicado_por or User.objects.filter(username=_APP_SYSTEM_USERNAME).first()
            if dono is None:
                logger.error(
                    f"Kit do pré-cadastro não criado: usuário '{_APP_SYSTEM_USERNAME}' não existe."
                )
                return None

            origem_link = (
                f" (link de {indicado_por.nome_completo or indicado_por.username})"
                if indicado_por else ""
            )
            kit = Kit.objects.create(
                cliente=cliente,
                criado_por=dono,
                tipo="bancario",
                status="rascunho",
                origem="app",
                app_criado_por_nome=f"Pré-cadastro — {cliente.nome_completo}{origem_link}",
            )
            logger.info(
                f"Kit #{kit.id} de pré-cadastro criado para o cliente #{cliente.id} "
                f"(visível para {dono.username} e admins)"
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

        # `cliente__isnull=True` é essencial: a conta pode existir sem ficha
        # (login por WhatsApp cria a conta antes do cadastro).
        conta = (
            ContaClienteApp.objects
            .select_related("cliente")
            .filter(email__iexact=email, is_active=True)
            .filter(Q(cliente__isnull=True) | Q(cliente__is_active=True))
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
        cliente = self.request.user.cliente
        if cliente is None:
            return Cliente.objects.none()
        return Cliente.objects.filter(pk=cliente.pk)

    def get_object(self):
        """Sempre o cliente da sessão — id divergente na URL é recusado."""
        cliente = self.request.user.cliente
        if cliente is None:
            raise exceptions.NotFound(
                "Seu cadastro ainda não foi criado. Preencha os dados em 'criar-ficha'."
            )
        pk = self.kwargs.get("pk")
        if pk is not None and str(pk) != str(cliente.pk):
            raise exceptions.PermissionDenied("Você só pode acessar o seu próprio cadastro.")
        return cliente

    # ── Estado da conta (o app chama logo após o login) ──

    @decorators.action(detail=False, methods=["get"])
    def estado(self, request):
        """Diz ao app se já existe ficha e se há vínculo a oferecer."""
        from .views_cliente_whatsapp import _ficha_sugerida

        conta = request.user.conta
        cliente = request.user.cliente

        sugestao = None
        if cliente is None and not conta.vinculo_recusado and conta.telefone:
            ficha = _ficha_sugerida(conta.telefone)
            if ficha is not None:
                sugestao = {"cliente_id": ficha.id, "nome_completo": ficha.nome_completo}

        return response.Response({
            "telefone": conta.telefone,
            "cadastro_pendente": cliente is None,
            "cliente_id": cliente.id if cliente else None,
            "vinculo_sugerido": sugestao,
            "acesso_alternativo_configurado": bool(conta.email and conta.senha_hash),
        })

    # ── Criação da ficha (primeiro salvamento do cadastro) ──

    @decorators.action(detail=False, methods=["post"], url_path="criar-ficha")
    def criar_ficha(self, request):
        """Cria o `Cliente` da conta. Exige nome completo, CPF e data de nascimento.

        A ficha só nasce aqui porque o CPF é obrigatório e único no JurisDoc — no
        login por WhatsApp a conta existe antes de qualquer dado de cadastro.
        """
        conta = request.user.conta
        if conta.cliente_id:
            return response.Response(
                {"detail": "Seu cadastro já existe.", "cliente_id": conta.cliente_id},
                status=status.HTTP_409_CONFLICT,
            )

        dados = request.data or {}
        nome = str(dados.get("nome_completo") or "").strip()
        cpf = _so_digitos(dados.get("cpf"))
        data_nascimento = _data_iso(dados.get("data_nascimento"))

        erros = {}
        if len(nome.split()) < 2:
            erros["nome_completo"] = "Informe o nome completo."
        if not _cpf_valido(cpf):
            erros["cpf"] = "CPF inválido."
        if not data_nascimento:
            erros["data_nascimento"] = "Informe a data de nascimento no formato AAAA-MM-DD."
        if erros:
            return response.Response(erros, status=status.HTTP_400_BAD_REQUEST)

        # Trava por CPF: dados já enviados ao escritório não se reabrem pelo app.
        if CadastroAppEnviado.objects.filter(cpf=cpf).exists():
            logger.info(f"criar-ficha recusado: CPF {cpf[:3]}*** já enviado pelo app")
            return response.Response(
                {
                    "detail": (
                        "Os dados deste CPF já foram enviados ao escritório e não podem "
                        "ser alterados pelo app. Em caso de dúvida, entre em contato com "
                        "o escritório."
                    ),
                    "motivo": "cadastro_ja_enviado",
                },
                status=status.HTTP_409_CONFLICT,
            )

        existente = Cliente.objects.filter(cpf=cpf).first()
        if existente is not None:
            # Se a ficha já é de outra conta, não há o que fazer pelo app.
            if ContaClienteApp.objects.filter(cliente=existente).exclude(pk=conta.pk).exists():
                return response.Response(
                    {"detail": "Este CPF já possui acesso no app. Procure o escritório."},
                    status=status.HTTP_409_CONFLICT,
                )
            if _normalizar_nome(existente.nome_completo) != _normalizar_nome(nome):
                return response.Response(
                    {"detail": "Os dados informados não conferem com o cadastro. Procure o escritório."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cliente = existente
            if not cliente.is_active:
                cliente.is_active = True
                cliente.save(update_fields=["is_active"])
        else:
            cliente = Cliente.objects.create(
                nome_completo=nome,
                cpf=cpf,
                data_nascimento=data_nascimento,
                telefone=conta.telefone or "",
                origem="app_cliente",
            )

        conta.cliente = cliente
        conta.vinculada_a_ficha_existente = existente is not None
        conta.save(update_fields=["cliente", "vinculada_a_ficha_existente"])

        indicador = conta.indicado_por or resolver_indicador(dados.get("indicado_por_id"))
        if indicador and not conta.indicado_por_id:
            conta.indicado_por = indicador
            conta.save(update_fields=["indicado_por"])

        kit_id = _criar_kit_rascunho(cliente, indicador)
        logger.info(f"Ficha criada pelo app para a conta #{conta.id} → cliente #{cliente.id}")

        return response.Response(
            {"cliente_id": cliente.id, "kit_id": kit_id, "cliente": _resumo_cliente(cliente)},
            status=status.HTTP_201_CREATED,
        )

    # ── Conclusão do cadastro (o "salvar" final da tela) ──

    @decorators.action(detail=False, methods=["post"])
    def concluir(self, request):
        """Encerra o autocadastro: entrega ao escritório e fecha o acesso.

        A partir daqui o cliente não volta mais àqueles dados — a trava é por
        CPF. O mesmo telefone continua livre para cadastrar OUTRA pessoa, por
        isso a conta é desvinculada em vez de desativada.

        O aviso ao escritório é acessório: se o WhatsApp falhar, a conclusão
        acontece do mesmo jeito e o problema fica no log.
        """
        from kits.models import Kit

        from .services_notificacao_app import notificar_escritorio

        conta = request.user.conta
        cliente = conta.cliente
        if cliente is None:
            return response.Response(
                {"detail": "Não há cadastro para concluir.", "motivo": "sem_cadastro"},
                status=status.HTTP_409_CONFLICT,
            )

        if CadastroAppEnviado.objects.filter(cpf=cliente.cpf).exists():
            return response.Response(
                {
                    "detail": "Este cadastro já foi enviado ao escritório.",
                    "motivo": "cadastro_ja_enviado",
                },
                status=status.HTTP_409_CONFLICT,
            )

        kit = Kit.objects.filter(cliente=cliente, origem="app").order_by("id").first()
        indicador = conta.indicado_por
        telefone_acesso = conta.telefone or ""

        with transaction.atomic():
            envio = CadastroAppEnviado.objects.create(
                cpf=cliente.cpf,
                cliente=cliente,
                telefone=telefone_acesso,
                indicado_por=indicador,
                kit_id=kit.id if kit else None,
            )
            # Solta o vínculo: o telefone segue servindo para cadastrar outra
            # pessoa, mas esta ficha fica fora do alcance do app.
            conta.cliente = None
            conta.vinculo_recusado = False
            conta.save(update_fields=["cliente", "vinculo_recusado"])

        enviada = notificar_escritorio(
            cliente, telefone_acesso, indicador, kit.id if kit else None
        )
        if enviada:
            CadastroAppEnviado.objects.filter(pk=envio.pk).update(notificacao_enviada=True)

        logger.info(
            f"Cadastro do cliente #{cliente.id} concluído pelo app "
            f"(aviso ao escritório: {'enviado' if enviada else 'falhou'})"
        )
        return response.Response(
            {
                "concluido": True,
                "acesso_encerrado": True,
                "cliente_id": cliente.id,
                "kit_id": kit.id if kit else None,
                "escritorio_notificado": enviada,
                "detail": (
                    "Cadastro enviado ao escritório. Em caso de dúvida, entre em "
                    "contato com o escritório."
                ),
            },
            status=status.HTTP_200_OK,
        )

    # ── Vínculo com ficha que o escritório já tinha ──

    @decorators.action(detail=False, methods=["post"])
    def vinculo(self, request):
        """Aceita ou recusa a ficha sugerida pelo telefone.

        Só chega aqui quem já validou o código do WhatsApp, ou seja, provou ser
        dono do número. Recusar NÃO apaga a ficha do escritório — apenas para de
        oferecer o vínculo para esta conta.
        """
        from .views_cliente_whatsapp import _ficha_sugerida

        conta = request.user.conta
        if conta.cliente_id:
            return response.Response(
                {"detail": "Sua conta já está vinculada a um cadastro."},
                status=status.HTTP_409_CONFLICT,
            )

        aceitar = bool((request.data or {}).get("aceitar"))
        if not aceitar:
            conta.vinculo_recusado = True
            conta.save(update_fields=["vinculo_recusado"])
            logger.info(f"Conta #{conta.id} recusou o vínculo sugerido pelo telefone")
            return response.Response({"vinculado": False})

        ficha = _ficha_sugerida(conta.telefone or "")
        if ficha is None:
            return response.Response(
                {"detail": "Não há cadastro disponível para vincular a este número."},
                status=status.HTTP_404_NOT_FOUND,
            )

        conta.cliente = ficha
        conta.vinculada_a_ficha_existente = True
        conta.save(update_fields=["cliente", "vinculada_a_ficha_existente"])
        logger.info(f"Conta #{conta.id} vinculada à ficha existente #{ficha.id} pelo telefone")

        # Ficha do escritório sem kit nenhum também merece o rascunho inicial.
        kit_id = _criar_kit_rascunho(ficha, conta.indicado_por)

        return response.Response(
            {
                "vinculado": True,
                "cliente_id": ficha.id,
                "kit_id": kit_id,
                "cliente": _resumo_cliente(ficha),
            }
        )

    # ── Acesso alternativo (plano B para quando o WhatsApp falha) ──

    @decorators.action(detail=False, methods=["post"], url_path="acesso-alternativo")
    def acesso_alternativo(self, request):
        """Define e-mail e senha de reserva para a própria conta."""
        dados = request.data or {}
        email = str(dados.get("email") or "").strip().lower()
        senha = str(dados.get("senha") or "")

        erros = {}
        if "@" not in email or "." not in email.split("@")[-1]:
            erros["email"] = "E-mail inválido."
        if len(senha) < SENHA_MIN:
            erros["senha"] = f"A senha deve ter ao menos {SENHA_MIN} caracteres."
        if erros:
            return response.Response(erros, status=status.HTTP_400_BAD_REQUEST)

        conta = request.user.conta
        if ContaClienteApp.objects.filter(email__iexact=email).exclude(pk=conta.pk).exists():
            return response.Response(
                {"detail": "Este e-mail já está em uso por outra conta."},
                status=status.HTTP_409_CONFLICT,
            )

        conta.email = email
        conta.set_senha(senha)
        conta.senha_alterada_em = timezone.now()
        try:
            conta.save(update_fields=["email", "senha_hash", "senha_alterada_em"])
        except IntegrityError:
            return response.Response(
                {"detail": "Este e-mail já está em uso por outra conta."},
                status=status.HTTP_409_CONFLICT,
            )

        logger.info(f"Conta #{conta.id} configurou acesso alternativo")
        return response.Response({"configurado": True, "email": email})

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
            # Desliga a conta E solta o vínculo com a ficha. Soltar é o que
            # distingue "o cliente apagou o próprio cadastro" de "o escritório
            # desativou a ficha": no primeiro caso ele volta pelo WhatsApp e
            # cadastra de novo do zero; no segundo, o login é recusado com
            # `cadastro_inativo` (ver views_cliente_whatsapp).
            ContaClienteApp.objects.filter(cliente=cliente).update(
                is_active=False, cliente=None
            )

        logger.info(f"Cliente #{cliente.id} excluiu o próprio pré-cadastro pelo app")
        return response.Response(status=status.HTTP_204_NO_CONTENT)

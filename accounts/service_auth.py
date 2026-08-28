"""
Autenticação Client Credentials para comunicação server-to-server.

Fluxo:
  1. Backend parceiro envia POST /api/auth/app-token/ com client_id + client_secret
  2. Este sistema valida as credenciais e retorna um access_token JWT de serviço
  3. Backend parceiro usa esse token no header: Authorization: Bearer <token>
  4. ServiceClientAuthentication decodifica e autentica o token de serviço
  5. IsServiceClient garante que só service tokens acessam os endpoints protegidos
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from rest_framework import authentication, exceptions, permissions

SERVICE_TOKEN_TYPE = "service_client"
SERVICE_TOKEN_LIFETIME = timedelta(hours=1)

# Token do CLIENTE FINAL no app (área "Sou cliente"). Vida mais longa que o de
# serviço porque o cliente preenche um formulário extenso e o app não guarda a
# senha para renovar sozinho. A revogação não depende do prazo: a conta é
# recarregada do banco a cada requisição (ver ClienteAppAuthentication).
CLIENTE_TOKEN_TYPE = "cliente_app"
CLIENTE_TOKEN_LIFETIME = timedelta(hours=12)

_SECRET: str = getattr(settings, "APP_INTEGRATION_SECRET", settings.SECRET_KEY)
_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Objeto pseudo-user para representar um App Client autenticado
# ---------------------------------------------------------------------------

class ServiceClientPrincipal:
    """
    Substituto de User para requests autenticados via Client Credentials.
    Nunca é um usuário humano — é a identidade do sistema parceiro.
    """

    is_authenticated: bool = True
    is_anonymous: bool = False
    pk = None

    def __init__(self, client_id: str, is_admin: bool = False) -> None:
        self.client_id = client_id
        self.is_admin = is_admin

    def __str__(self) -> str:
        return f"AppClient:{self.client_id}"


# ---------------------------------------------------------------------------
# Emissão de tokens de serviço
# ---------------------------------------------------------------------------

def issue_service_token(client_id: str, is_admin: bool = False) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {
        "type": SERVICE_TOKEN_TYPE,
        "client_id": client_id,
        "is_admin": is_admin,
        "iat": now,
        "exp": now + SERVICE_TOKEN_LIFETIME,
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


# ---------------------------------------------------------------------------
# Classe de autenticação DRF
# ---------------------------------------------------------------------------

class ServiceClientAuthentication(authentication.BaseAuthentication):
    """
    Autentica tokens de serviço emitidos por /api/auth/app-token/.

    - Tokens de usuário comum são ignorados (retorna None → próximo authenticator).
    - Tokens de serviço expirados ou malformados levantam AuthenticationFailed.
    """

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()

        if not header or header[0].lower() != b"bearer":
            return None

        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Formato de Authorization inválido.")

        raw_token = header[1]

        try:
            payload = jwt.decode(raw_token, _SECRET, algorithms=[_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed("Token de serviço expirado.")
        except jwt.InvalidTokenError:
            # Não é um service token — deixa outro authenticator tentar
            return None

        if payload.get("type") != SERVICE_TOKEN_TYPE:
            # Token JWT válido mas não é de serviço — ignora
            return None

        return ServiceClientPrincipal(payload["client_id"], is_admin=payload.get("is_admin", False)), payload

    def authenticate_header(self, request) -> str:
        return "Bearer"


# ---------------------------------------------------------------------------
# Classe de permissão DRF
# ---------------------------------------------------------------------------

class IsServiceClient(permissions.BasePermission):
    """
    Concede acesso apenas a requisições autenticadas como App Client.
    Bloqueia usuários humanos e requisições não autenticadas.
    """

    message = "Acesso restrito a App Clients autorizados (Client Credentials)."

    def has_permission(self, request, view) -> bool:
        return isinstance(getattr(request, "user", None), ServiceClientPrincipal)


# ---------------------------------------------------------------------------
# Cliente final (área "Sou cliente" do app)
# ---------------------------------------------------------------------------

class ClienteAppPrincipal:
    """Identidade de um cliente final autenticado no app.

    Carrega a conta e o cliente já resolvidos do banco — as views nunca aceitam
    um id de cliente vindo da requisição, sempre usam `principal.cliente`.
    """

    is_authenticated: bool = True
    is_anonymous: bool = False
    pk = None

    def __init__(self, conta) -> None:
        self.conta = conta
        self.cliente = conta.cliente

    def __str__(self) -> str:
        return f"ClienteApp:{self.conta.email}"


def issue_cliente_token(conta_id: int) -> tuple[str, int]:
    """Emite o token de sessão do cliente. Retorna (token, segundos_de_validade)."""
    now = datetime.now(tz=timezone.utc)
    payload = {
        "type": CLIENTE_TOKEN_TYPE,
        "conta_id": conta_id,
        "iat": now,
        "exp": now + CLIENTE_TOKEN_LIFETIME,
    }
    token = jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)
    return token, int(CLIENTE_TOKEN_LIFETIME.total_seconds())


class ClienteAppAuthentication(authentication.BaseAuthentication):
    """Autentica o token de sessão do cliente final.

    Recarrega a conta do banco a cada requisição: desativar a conta ou o cliente
    corta o acesso na hora, sem esperar o token expirar.
    """

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()

        if not header or header[0].lower() != b"bearer":
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Formato de Authorization inválido.")

        try:
            payload = jwt.decode(header[1], _SECRET, algorithms=[_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed("Sessão expirada. Entre novamente.")
        except jwt.InvalidTokenError:
            return None

        if payload.get("type") != CLIENTE_TOKEN_TYPE:
            return None  # outro tipo de token — deixa o próximo authenticator tentar

        from django.db.models import Q

        from cadastro.models import ContaClienteApp

        # `cliente__isnull=True` é essencial: no login por WhatsApp a conta nasce
        # sem ficha (o CPF só chega no cadastro). Filtrar por `cliente__is_active`
        # sozinho faria o JOIN descartar justamente essas contas.
        conta = (
            ContaClienteApp.objects
            .select_related("cliente")
            .filter(pk=payload.get("conta_id"), is_active=True)
            .filter(Q(cliente__isnull=True) | Q(cliente__is_active=True))
            .first()
        )
        if conta is None:
            raise exceptions.AuthenticationFailed("Acesso revogado. Procure o escritório.")

        return ClienteAppPrincipal(conta), payload

    def authenticate_header(self, request) -> str:
        return "Bearer"


class IsClienteApp(permissions.BasePermission):
    """Acesso restrito ao cliente final autenticado pelo app."""

    message = "Acesso restrito ao cliente autenticado no app."

    def has_permission(self, request, view) -> bool:
        return isinstance(getattr(request, "user", None), ClienteAppPrincipal)


class IsServiceAdmin(permissions.BasePermission):
    """
    Concede acesso apenas a App Clients com is_admin=True no token.
    Usado em endpoints de escrita (CRUD completo de clientes etc.).
    App Clients sem flag de admin recebem 403.
    """

    message = "Acesso restrito a App Clients com perfil de administrador."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return isinstance(user, ServiceClientPrincipal) and user.is_admin is True

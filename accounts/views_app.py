"""SSO para o app FlowALR — o app valida as credenciais aqui.

O app não guarda senha própria: na tela de login dele, o backend (FastAPI) chama
`POST /api/app/auth/validar-credenciais/` com o que o colaborador digitou, e o
JurisDoc responde se confere. Assim "mesmas credenciais" é literal e permanente:
trocar a senha no JurisDoc reflete no app na hora, sem sincronização.

Só passam usuários que atendem às três condições ao mesmo tempo:
  is_active=True  +  is_admin=True  +  acesso_app=True

Dois níveis de erro, que não devem ser confundidos:
  HTTP 401 → o token de serviço do app está inválido/expirado (problema do app)
  HTTP 200 + {"valido": false} → as credenciais do colaborador não conferem
"""
from __future__ import annotations

import logging

from django.contrib.auth import authenticate, get_user_model
from rest_framework import status, throttling
from rest_framework.response import Response
from rest_framework.views import APIView

from .service_auth import IsServiceClient, ServiceClientAuthentication

logger = logging.getLogger(__name__)
User = get_user_model()


class LoginAppThrottle(throttling.SimpleRateThrottle):
    """Limita tentativas por usuário informado, não por IP.

    O app chama sempre do mesmo servidor, então throttle por IP puniria todo
    mundo junto. Chavear pelo username barra ataque de força bruta contra uma
    conta específica sem atrapalhar os demais colaboradores.
    """

    scope = "app_login"

    def get_cache_key(self, request, view):
        username = str((request.data or {}).get("username") or "").strip().lower()[:150]
        ident = username or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ValidarCredenciaisAppView(APIView):
    """POST /api/app/auth/validar-credenciais/ — valida login de colaborador.

    Autenticação: token de serviço (Client Credentials) do app.
    Body: {"username": str, "password": str}

    Resposta 200 (sucesso):
        {"valido": true, "usuario": {id, username, nome_completo, email,
                                     telefone, is_admin}}

    Resposta 200 (falha):
        {"valido": false, "motivo": "credenciais_invalidas" | "sem_acesso_app"}

    `sem_acesso_app` só é devolvido quando a senha está CORRETA mas o usuário não
    tem o acesso liberado — assim a resposta nunca revela se um username existe.
    """

    authentication_classes = [ServiceClientAuthentication]
    permission_classes = [IsServiceClient]
    throttle_classes = [LoginAppThrottle]

    def post(self, request):
        dados = request.data or {}
        username = str(dados.get("username") or "").strip()
        password = str(dados.get("password") or "")

        if not username or not password:
            return Response(
                {"valido": False, "motivo": "credenciais_invalidas"},
                status=status.HTTP_200_OK,
            )

        # authenticate() já equaliza o tempo de resposta quando o usuário não
        # existe (o ModelBackend roda o hash mesmo assim) e recusa conta inativa.
        user = authenticate(request=request, username=username, password=password)

        if user is None:
            logger.info(f"App SSO: credenciais inválidas para '{username[:40]}'")
            return Response(
                {"valido": False, "motivo": "credenciais_invalidas"},
                status=status.HTTP_200_OK,
            )

        if not (user.is_admin and user.acesso_app):
            logger.info(
                f"App SSO: '{user.username}' autenticou mas não tem acesso ao app "
                f"(is_admin={user.is_admin}, acesso_app={user.acesso_app})"
            )
            return Response(
                {"valido": False, "motivo": "sem_acesso_app"},
                status=status.HTTP_200_OK,
            )

        logger.info(f"App SSO: '{user.username}' validado com sucesso")
        return Response(
            {
                "valido": True,
                "usuario": {
                    "id": user.id,
                    "username": user.username,
                    "nome_completo": user.nome_completo or user.get_full_name() or user.username,
                    "email": user.email or "",
                    "telefone": user.telefone or "",
                    "is_admin": True,
                },
            },
            status=status.HTTP_200_OK,
        )

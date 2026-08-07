import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    nome_completo = models.CharField(max_length=200, blank=True, default="")
    telefone = models.CharField(max_length=20, blank=True, default="")
    endereco = models.JSONField(blank=True, default=dict)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    is_admin = models.BooleanField(default=True)

    # Acesso ao app FlowALR (SSO): quando ligado, este usuário pode entrar no app
    # com as MESMAS credenciais do JurisDoc — o app valida a senha aqui, via
    # POST /api/app/auth/validar-credenciais/, e não guarda senha própria.
    # Exige is_admin=True; conceder é ação auditada (ver accounts/serializers.py).
    acesso_app = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Permite login no app FlowALR com as credenciais do JurisDoc.",
    )
    acesso_app_liberado_em = models.DateTimeField(null=True, blank=True, editable=False)
    acesso_app_liberado_por = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="acessos_app_concedidos",
    )

    permissao = models.ForeignKey(
        "permissoes.Permissao",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usuarios",
    )
    # Capacidades concedidas DIRETAMENTE ao usuário, fora do perfil. Usado para
    # capacidades sensíveis (ex.: honorários) atribuídas por usuário na página
    # de Permissões. Somam-se às do perfil e NÃO são herdadas por admin.
    capacidades_diretas = models.ManyToManyField(
        "permissoes.Capacidade",
        blank=True,
        related_name="usuarios_diretos",
    )

    def __str__(self):
        return self.username


class AppClient(models.Model):
    """
    Credencial de aplicação para comunicação server-to-server (Client Credentials).
    Nunca expor client_secret_hash; o segredo bruto só existe no momento da criação.
    """

    client_id = models.CharField(max_length=64, unique=True, db_index=True)
    client_secret_hash = models.CharField(max_length=256)
    nome = models.CharField(max_length=120, help_text="Nome identificador da aplicação cliente (ex.: Backend App Colaboradores)")
    is_active = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False, help_text="Permite acesso a endpoints de escrita (CRUD completo de clientes etc.)")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App Client"
        verbose_name_plural = "App Clients"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.client_id})"

    @staticmethod
    def generate_credentials() -> tuple[str, str]:
        """Gera um par (client_id, client_secret) criptograficamente seguro."""
        client_id = secrets.token_urlsafe(24)
        client_secret = secrets.token_urlsafe(48)
        return client_id, client_secret

    def set_secret(self, raw_secret: str) -> None:
        self.client_secret_hash = make_password(raw_secret)

    def check_secret(self, raw_secret: str) -> bool:
        return check_password(raw_secret, self.client_secret_hash)

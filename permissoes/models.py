from django.conf import settings
from django.db import models


class Capacidade(models.Model):
    """
    Capacidade atômica de uso do sistema (recurso x ação).
    O catálogo é mantido em `permissoes/catalog.py` e sincronizado via
    `python manage.py sync_capacidades`. Admin não cria capacidades pela UI —
    ele compõe Permissoes a partir deste catálogo.
    """
    codigo = models.CharField(max_length=80, unique=True)
    recurso = models.CharField(max_length=60)
    acao = models.CharField(max_length=40)
    descricao = models.CharField(max_length=200)
    categoria = models.CharField(max_length=40, default="Outros")

    class Meta:
        ordering = ["categoria", "recurso", "acao"]
        verbose_name = "Capacidade"
        verbose_name_plural = "Capacidades"

    def __str__(self) -> str:
        return self.codigo


class Permissao(models.Model):
    """
    Perfil nomeado (bundle) que agrupa N capacidades.
    Admin cria e edita pela página /permissoes do frontend.
    Usuários têm FK para uma Permissao (User.permissao).
    """
    nome = models.CharField(max_length=80, unique=True)
    descricao = models.TextField(blank=True, default="")
    capacidades = models.ManyToManyField(
        Capacidade,
        related_name="permissoes",
        blank=True,
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="permissoes_criadas",
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "Permissão"
        verbose_name_plural = "Permissões"

    def __str__(self) -> str:
        return self.nome

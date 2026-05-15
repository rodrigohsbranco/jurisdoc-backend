from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    nome_completo = models.CharField(max_length=200, blank=True, default="")
    telefone = models.CharField(max_length=20, blank=True, default="")
    endereco = models.JSONField(blank=True, default=dict)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    is_admin = models.BooleanField(default=True)
    permissao = models.ForeignKey(
        "permissoes.Permissao",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usuarios",
    )

    def __str__(self):
        return self.username

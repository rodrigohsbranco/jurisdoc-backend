# petitions/models.py
from django.db import models
from django.conf import settings
from templates_app.models import Template
from cadastro.models import Cliente  # ajuste o import conforme o app real


class Petition(models.Model):
    """
    Petição vinculada a um Cliente + Template.
    - O campo 'context' armazena variáveis preenchidas no momento da criação.
    - O campo especial 'banco' (quando usado em templates) é preenchido
      automaticamente com a descrição ativa do banco da conta principal do cliente.
    """

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="petitions"
    )
    template = models.ForeignKey(Template, on_delete=models.PROTECT)
    context = models.JSONField(default=dict, blank=True)
    output = models.FileField(upload_to="petitions/", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Petition {self.id} - {self.template.name} ({self.cliente.nome_completo})"

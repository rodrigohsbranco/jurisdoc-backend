# petitions/models.py
from django.db import models
from django.conf import settings
from templates_app.models import Template
from cadastro.models import Cliente  # ajuste o import conforme o app real

class Petition(models.Model):
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, related_name="petitions"
    )
    template = models.ForeignKey(Template, on_delete=models.PROTECT)
    context = models.JSONField(default=dict, blank=True)
    output = models.FileField(upload_to="petitions/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # <- NOVO
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def __str__(self):
        return f"Petition {self.id} - {self.template.name}"

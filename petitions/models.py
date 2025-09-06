from django.db import models
from django.conf import settings
from templates_app.models import Template

class Petition(models.Model):
    template = models.ForeignKey(Template, on_delete=models.PROTECT)
    context = models.JSONField()
    output = models.FileField(upload_to="output/")
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def __str__(self):
        return f"Petition {self.id} - {self.template.name}"

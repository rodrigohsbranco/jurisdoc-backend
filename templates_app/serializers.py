from rest_framework import serializers
from .models import Template
from django.core.exceptions import ValidationError
import os


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = ["id", "name", "file", "active"]

    def validate_file(self, f):
        """Valida o upload de template:
        - Apenas arquivos .docx
        - Máx 25MB (limite realista)
        """
        ext = os.path.splitext(f.name)[1].lower()
        if ext != ".docx":
            raise ValidationError("Envie um arquivo .docx válido (apenas .docx é aceito).")
        if getattr(f, "size", 0) and f.size > 50 * 1024 * 1024:
            raise ValidationError("Tamanho máximo permitido: 50MB.")
        return f

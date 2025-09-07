from rest_framework import serializers
from .models import Template
from django.core.exceptions import ValidationError
import os

class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = ["id","name","file","active"]
    
    def validate_file(self, f):
        ext = os.path.splitext(f.name)[1].lower()
        if ext != ".docx":
            raise ValidationError("Envie um arquivo .docx válido.")
        if getattr(f, "size", 0) and f.size > 25 * 1024 * 1024:
            raise ValidationError("Tamanho máximo de 25MB.")
        return f


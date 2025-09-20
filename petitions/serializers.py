# petitions/serializers.py
from rest_framework import serializers
from .models import Petition


class PetitionSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    output = serializers.FileField(read_only=True, required=False, allow_null=True)
    cliente_nome = serializers.CharField(
        source="cliente.nome_completo",
        read_only=True,
        default=""
    )  # evita erro se cliente=None

    class Meta:
        model = Petition
        fields = [
            "id",
            "cliente",
            "cliente_nome",   # útil pro front
            "template",
            "context",
            "output",
            "created_at",
            "updated_at",     # garante no JSON
            "user",
        ]
        read_only_fields = ["output", "created_at", "updated_at", "user"]

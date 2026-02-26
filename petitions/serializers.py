# petitions/serializers.py
from rest_framework import serializers
from .models import Petition


class PetitionSerializer(serializers.ModelSerializer):
    """
    Serializer principal de Petitions.
    - O campo 'context' armazena as variáveis usadas no template (.docx).
    - Durante a renderização, o backend completa automaticamente as variáveis
      de banco: nome_banco, cnpj e endereco_banco.
    """

    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    output = serializers.FileField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="Arquivo gerado (.docx) após renderização do template."
    )

    cliente_nome = serializers.CharField(
        source="cliente.nome_completo",
        read_only=True,
        default="",
        help_text="Nome completo do cliente vinculado à petição."
    )

    context = serializers.JSONField(
        required=False,
        default=dict,
        help_text=(
            "Dicionário de variáveis do template. "
            "Durante a renderização, o sistema preenche automaticamente as variáveis "
            "de banco (nome_banco, cnpj, endereco_banco) conforme a conta principal do cliente."
        )
    )

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
            "updated_at",
            "user",
        ]
        read_only_fields = ["output", "created_at", "updated_at", "user"]

from rest_framework import serializers

from cadastro.serializers import ClienteSerializer

from .models import Kit
from .serializers import AcaoKitSerializer, DocumentoKitSerializer


class KitAppListSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome_completo", read_only=True)
    cliente_cpf = serializers.CharField(source="cliente.cpf", read_only=True)
    total_acoes = serializers.IntegerField(source="acoes.count", read_only=True)

    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "cliente",
            "cliente_nome",
            "cliente_cpf",
            "status",
            "total_acoes",
            "origem",
            "app_criado_por_nome",
            "criado_em",
            "atualizado_em",
        ]


class KitAppDetailSerializer(serializers.ModelSerializer):
    cliente_detail = ClienteSerializer(source="cliente", read_only=True)
    acoes = AcaoKitSerializer(many=True, read_only=True)
    documentos = DocumentoKitSerializer(many=True, read_only=True)

    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "cliente",
            "cliente_detail",
            "status",
            "acoes",
            "documentos",
            "advogados_snapshot",
            "clausula_porcentagem_snapshot",
            "origem",
            "app_criado_por_nome",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = [
            "id",
            "criado_em",
            "atualizado_em",
            "origem",
            "app_criado_por_nome",
            "advogados_snapshot",
            "clausula_porcentagem_snapshot",
        ]


class KitAppCreateSerializer(serializers.ModelSerializer):
    app_criado_por_nome = serializers.CharField(required=True, max_length=200)

    class Meta:
        model = Kit
        fields = [
            "id",
            "tipo",
            "cliente",
            "app_criado_por_nome",
            "status",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "status", "criado_em", "atualizado_em"]

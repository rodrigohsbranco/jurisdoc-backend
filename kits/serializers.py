from rest_framework import serializers

from cadastro.serializers import ClienteSerializer
from .models import AcaoKit, DocumentoKit, Kit


class AcaoKitSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcaoKit
        fields = [
            "id",
            "kit",
            "tipo_acao",
            "nome_banco",
            "banco_outro",
            "numero_contrato",
            "tarifa_questionada",
            "tipo_seguro",
            "tipo_contribuicao",
            "historico_emprestimo",
            "historico_credito",
            "extrato_bancario",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "kit": {"required": False},
        }


class DocumentoKitSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoKit
        fields = [
            "id",
            "kit",
            "tipo",
            "arquivo",
            "gerado_em",
        ]
        read_only_fields = ["id", "gerado_em"]


class KitListSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome_completo", read_only=True)
    cliente_cpf = serializers.CharField(source="cliente.cpf", read_only=True)
    criado_por_nome = serializers.CharField(source="criado_por.username", read_only=True)
    total_acoes = serializers.IntegerField(source="acoes.count", read_only=True)

    class Meta:
        model = Kit
        fields = [
            "id",
            "cliente",
            "cliente_nome",
            "cliente_cpf",
            "criado_por",
            "criado_por_nome",
            "status",
            "total_acoes",
            "criado_em",
            "atualizado_em",
        ]


class KitDetailSerializer(serializers.ModelSerializer):
    cliente_detail = ClienteSerializer(source="cliente", read_only=True)
    acoes = AcaoKitSerializer(many=True, read_only=True)
    documentos = DocumentoKitSerializer(many=True, read_only=True)
    criado_por_nome = serializers.CharField(source="criado_por.username", read_only=True)

    class Meta:
        model = Kit
        fields = [
            "id",
            "cliente",
            "cliente_detail",
            "criado_por",
            "criado_por_nome",
            "status",
            "acoes",
            "documentos",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_por", "criado_em", "atualizado_em"]


class KitCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Kit
        fields = [
            "id",
            "cliente",
            "status",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "status", "criado_em", "atualizado_em"]

from rest_framework import serializers

from .models import Advogado, OabUf


class OabUfSerializer(serializers.ModelSerializer):
    class Meta:
        model = OabUf
        fields = [
            "id",
            "advogado",
            "uf",
            "numero_oab",
            "unidade_apoio_nome",
            "unidade_apoio_endereco",
        ]
        read_only_fields = ["id", "advogado"]


class AdvogadoListSerializer(serializers.ModelSerializer):
    total_ufs = serializers.IntegerField(source="oabs.count", read_only=True)

    class Meta:
        model = Advogado
        fields = [
            "id",
            "nome_completo",
            "nacionalidade",
            "estado_civil",
            "genero",
            "is_socio",
            "escritorio_nome",
            "escritorio_cnpj",
            "escritorio_endereco",
            "tipos_acao",
            "ativo",
            "total_ufs",
            "criado_em",
            "atualizado_em",
        ]


class AdvogadoDetailSerializer(serializers.ModelSerializer):
    oabs = OabUfSerializer(many=True, read_only=True)

    class Meta:
        model = Advogado
        fields = [
            "id",
            "nome_completo",
            "nacionalidade",
            "estado_civil",
            "genero",
            "is_socio",
            "escritorio_nome",
            "escritorio_cnpj",
            "escritorio_endereco",
            "tipos_acao",
            "ativo",
            "oabs",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

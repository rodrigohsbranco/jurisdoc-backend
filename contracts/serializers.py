from rest_framework import serializers
from .models import Contrato


class ContratoSerializer(serializers.ModelSerializer):
    # Campos extras apenas de leitura
    cliente_nome = serializers.CharField(source="cliente.nome_completo", read_only=True)
    usuario_nome = serializers.CharField(source="criado_por.username", read_only=True)

    class Meta:
        model = Contrato
        fields = [
            "id",
            "cliente",
            "cliente_nome",
            "numero_contrato",
            "banco_nome",
            "banco_id",
            "situacao",
            "origem_averbacao",
            "data_inclusao",
            "data_inicio_desconto",
            "data_fim_desconto",
            "quantidade_parcelas",
            "valor_parcela",
            "iof",
            "valor_emprestado",
            "valor_liberado",
            "observacoes",
            "criado_em",
            "atualizado_em",
            "criado_por",
            "usuario_nome",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em", "criado_por"]

    def create(self, validated_data):
        # Preenche o usuário automaticamente
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            validated_data["criado_por"] = request.user
        return super().create(validated_data)

    def validate(self, attrs):
        """
        Regras simples de consistência de datas e valores.
        """
        data_inicio = attrs.get("data_inicio_desconto")
        data_fim = attrs.get("data_fim_desconto")
        if data_inicio and data_fim and data_inicio > data_fim:
            raise serializers.ValidationError(
                {"data_fim_desconto": "Data fim não pode ser anterior à data de início do desconto."}
            )

        valor_parcela = attrs.get("valor_parcela")
        qtd_parcelas = attrs.get("quantidade_parcelas")
        if valor_parcela and qtd_parcelas and valor_parcela < 0:
            raise serializers.ValidationError({"valor_parcela": "Valor da parcela inválido."})

        return attrs

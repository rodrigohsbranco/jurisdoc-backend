from rest_framework import serializers
from .models import Cliente, ContaBancaria
from .validators import only_digits, validate_cpf, validate_cep, validate_uf

class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = [
            "id", "nome_completo", "cpf", "rg", "orgao_expedidor",
            "qualificacao", "se_idoso",
            "logradouro", "numero", "bairro", "cidade", "cep", "uf",
            "criado_em", "atualizado_em",
        ]
        read_only_fields = ["criado_em", "atualizado_em"]

    def validate_cpf(self, v):
        v = only_digits(v)
        validate_cpf(v)
        return v

    def validate_cep(self, v):
        v = only_digits(v)
        validate_cep(v)
        return v

    def validate_uf(self, v):
        v = (v or "").upper()
        validate_uf(v)
        return v


class ContaBancariaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContaBancaria
        fields = [
            "id", "cliente", "banco_nome", "agencia", "conta", "digito",
            "tipo", "is_principal", "criado_em", "atualizado_em"
        ]
        read_only_fields = ["criado_em", "atualizado_em"]

    def validate_agencia(self, v):
        return only_digits(v)

    def validate_conta(self, v):
        return only_digits(v)

    def validate_digito(self, v):
        return only_digits(v)

    def validate(self, attrs):
        # mantém sua regra: apenas uma principal por cliente
        is_principal = attrs.get("is_principal", False)
        cliente = attrs.get("cliente") or getattr(getattr(self, "instance", None), "cliente", None)
        if is_principal and cliente:
            qs = ContaBancaria.objects.filter(cliente=cliente, is_principal=True)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("Este cliente já possui uma conta principal.")
        return attrs
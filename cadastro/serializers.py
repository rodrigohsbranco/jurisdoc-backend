from django.db import transaction
from rest_framework import serializers

from .models import Cliente, ContaBancaria, DescricaoBanco
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
    # ---- Campos opcionais (write-only) para a funcionalidade de descrições por banco) ----
    # Se enviados, o backend cria uma NOVA variação de descrição para o banco
    # e, se 'descricao_set_ativa' = True, a marca como ATIVA (desativando as demais do mesmo banco_id).
    banco_id = serializers.CharField(write_only=True, required=False, allow_blank=True)
    descricao_banco = serializers.CharField(write_only=True, required=False, allow_blank=True)
    descricao_set_ativa = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = ContaBancaria
        fields = [
            "id", "cliente", "banco_nome", "agencia", "conta", "digito",
            "tipo", "is_principal", "criado_em", "atualizado_em",
            # novos write-only (não aparecem na resposta)
            "banco_id", "descricao_banco", "descricao_set_ativa",
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

    # --------- hooks para criação de uma nova variação de DescricaoBanco (opcional) ---------
    def _maybe_create_descricao_banco(
        self, *, banco_id: str | None, banco_nome: str, descricao: str | None, set_ativa: bool
    ):
        banco_id = (banco_id or "").strip()
        descricao = (descricao or "").strip()
        if not banco_id or descricao == "":
            # nada a fazer; recurso é opcional
            return

        req = self.context.get("request") if hasattr(self, "context") else None
        user = getattr(req, "user", None) if req else None

        with transaction.atomic():
            if set_ativa:
                # Desativa outras ativas do mesmo banco_id
                DescricaoBanco.objects.filter(banco_id=banco_id, is_ativa=True).update(is_ativa=False)
            obj = DescricaoBanco.objects.create(
                banco_id=banco_id,
                banco_nome=banco_nome,
                descricao=descricao,
                is_ativa=bool(set_ativa),
                atualizado_por=user if (user and getattr(user, "is_authenticated", False)) else None,
            )
            return obj

    def create(self, validated_data):
        # retira campos write-only antes do create
        banco_id = validated_data.pop("banco_id", None)
        descricao_banco = validated_data.pop("descricao_banco", None)
        descricao_set_ativa = bool(validated_data.pop("descricao_set_ativa", False))

        obj = super().create(validated_data)

        # cria uma NOVA variação de descrição (se veio info suficiente)
        self._maybe_create_descricao_banco(
            banco_id=banco_id,
            banco_nome=obj.banco_nome,
            descricao=descricao_banco,
            set_ativa=descricao_set_ativa,
        )
        return obj

    def update(self, instance, validated_data):
        # retira campos write-only antes do update
        banco_id = validated_data.pop("banco_id", None)
        descricao_banco = validated_data.pop("descricao_banco", None)
        descricao_set_ativa = bool(validated_data.pop("descricao_set_ativa", False))

        obj = super().update(instance, validated_data)

        # cria uma NOVA variação de descrição (se veio info suficiente)
        self._maybe_create_descricao_banco(
            banco_id=banco_id,
            banco_nome=obj.banco_nome,
            descricao=descricao_banco,
            set_ativa=descricao_set_ativa,
        )
        return obj


class DescricaoBancoSerializer(serializers.ModelSerializer):
    """
    Serializer do recurso 'descrição por banco' com suporte a múltiplas variações.
    - Se 'is_ativa' for True no create/update, desativa as demais do mesmo banco_id.
    """
    class Meta:
        model = DescricaoBanco
        fields = [
            "id",
            "banco_id",
            "banco_nome",
            "descricao",
            "is_ativa",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["criado_em", "atualizado_em"]

    def _set_user(self, obj):
        req = self.context.get("request") if hasattr(self, "context") else None
        user = getattr(req, "user", None)
        if user and getattr(user, "is_authenticated", False):
            obj.atualizado_por = user
            obj.save(update_fields=["atualizado_por"])

    @transaction.atomic
    def create(self, validated_data):
        set_ativa = bool(validated_data.get("is_ativa", False))
        banco_id = validated_data.get("banco_id")
        if set_ativa and banco_id:
            # Desativa outras ativas do mesmo banco antes de criar esta
            DescricaoBanco.objects.filter(banco_id=banco_id, is_ativa=True).update(is_ativa=False)

        obj = super().create(validated_data)
        self._set_user(obj)
        return obj

    @transaction.atomic
    def update(self, instance, validated_data):
        set_ativa = bool(validated_data.get("is_ativa", instance.is_ativa))
        banco_id = validated_data.get("banco_id", instance.banco_id)
        if set_ativa and banco_id:
            # Desativa outras ativas do mesmo banco (exceto esta)
            DescricaoBanco.objects.filter(banco_id=banco_id, is_ativa=True).exclude(pk=instance.pk).update(is_ativa=False)

        obj = super().update(instance, validated_data)
        self._set_user(obj)
        return obj

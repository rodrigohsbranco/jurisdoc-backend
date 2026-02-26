from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import Cliente, ContaBancaria, DescricaoBanco, Representante
from .validators import only_digits, validate_cpf, validate_cep, validate_uf, validate_banco_id


# =========================
# Cliente
# =========================
class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = [
            "id",
            "nome_completo",
            "cpf",
            "rg",
            "orgao_expedidor",
            # Mantido por compatibilidade (ocultar no front, mas não remover do schema)
            "qualificacao",               # [DEPRECADO] manter no back
            # Sinalizadores
            "se_idoso",
            "se_incapaz",
            "se_crianca_adolescente",
            # Dados civis
            "nacionalidade",
            "estado_civil",
            "profissao",
            # Endereço
            "logradouro",
            "numero",
            "bairro",
            "cidade",
            "cep",
            "uf",
            # Auditoria
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["criado_em", "atualizado_em"]

    # Normalizações/validações
    def validate_cpf(self, v):
        v = only_digits(v)
        validate_cpf(v)
        return v

    def validate_cep(self, v):
        v = only_digits(v or "")
        if v:
            validate_cep(v)
        return v

    def validate_uf(self, v):
        v = (v or "").upper()
        if v:
            validate_uf(v)
        return v


# =========================
# Conta Bancária
# =========================
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
            "id",
            "cliente",
            "banco_nome",
            "banco_codigo",   # 🔹 Exposto para o front (hidratar descrições por ID)
            "agencia",
            "conta",
            "digito",
            "tipo",
            "is_principal",
            "criado_em",
            "atualizado_em",
            # novos write-only (não aparecem na resposta)
            "banco_id",
            "descricao_banco",
            "descricao_set_ativa",
        ]
        read_only_fields = ["criado_em", "atualizado_em"]

    # Normalizações
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


# =========================
# Descrição de Banco
# =========================
# cadastro/serializers.py

class DescricaoBancoSerializer(serializers.ModelSerializer):
    """
    Serializer do recurso 'descrição por banco' com suporte a múltiplas variações.
    Agora usa campos estruturados (nome_banco, cnpj, endereco).
    """

    class Meta:
        model = DescricaoBanco
        fields = [
            "id",
            "banco_id",
            "banco_nome",
            "nome_banco",
            "cnpj",
            "endereco",
            "is_ativa",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["criado_em", "atualizado_em"]

    # --- Validadores individuais ---
    def validate_banco_id(self, v: str) -> str:
        return validate_banco_id(v)

    def validate_banco_nome(self, v: str) -> str:
        return (v or "").strip()

    # --- Criação com controle de "is_ativa" ---
    @transaction.atomic
    def create(self, validated_data):
        set_ativa = bool(validated_data.get("is_ativa", False))
        banco_id = validated_data.get("banco_id")

        # Se marcamos esta como ativa, desativa as demais do mesmo banco
        if set_ativa and banco_id:
            DescricaoBanco.objects.filter(
                banco_id=banco_id, is_ativa=True
            ).update(is_ativa=False)

        # Cria o novo registro normalmente
        obj = super().create(validated_data)
        return obj

    # --- Atualização com controle de "is_ativa" ---
    @transaction.atomic
    def update(self, instance, validated_data):
        set_ativa = bool(validated_data.get("is_ativa", instance.is_ativa))
        banco_id = validated_data.get("banco_id", instance.banco_id)

        # Se esta variação for marcada como ativa, desativa as demais
        if set_ativa and banco_id:
            DescricaoBanco.objects.filter(
                banco_id=banco_id, is_ativa=True
            ).exclude(pk=instance.pk).update(is_ativa=False)

        obj = super().update(instance, validated_data)
        return obj


# =========================
# Representante
# =========================
class RepresentanteSerializer(serializers.ModelSerializer):
    """
    CRUD de Representante.
    - Se 'usa_endereco_do_cliente' for True, copiamos o endereço do cliente no create/update.
      (Sempre copiamos — a flag funciona como "usar o do cliente", não apenas "preencher se vazio".)
    """
    class Meta:
        model = Representante
        fields = [
            "id",
            "cliente",
            # Identificação
            "nome_completo",
            "cpf",
            "rg",
            "orgao_expedidor",
            # Sinalizadores
            "se_idoso",
            "se_incapaz",
            "se_crianca_adolescente",
            # Dados civis
            "nacionalidade",
            "estado_civil",
            "profissao",
            # Endereço
            "usa_endereco_do_cliente",
            "logradouro",
            "numero",
            "bairro",
            "cidade",
            "cep",
            "uf",
            # Auditoria
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["criado_em", "atualizado_em"]

    # Normalizações
    def validate_cpf(self, v):
        v = only_digits(v)
        validate_cpf(v)
        return v

    def validate_cep(self, v):
        v = only_digits(v or "")
        if v:
            validate_cep(v)
        return v

    def validate_uf(self, v):
        v = (v or "").upper()
        if v:
            validate_uf(v)
        return v

    def validate(self, attrs):
        # Garante unicidade (cliente, cpf)
        cliente = attrs.get("cliente") or getattr(getattr(self, "instance", None), "cliente", None)
        cpf = attrs.get("cpf") or getattr(getattr(self, "instance", None), "cpf", None)
        if cliente and cpf:
            cpf_norm = only_digits(cpf)
            qs = Representante.objects.filter(cliente=cliente, cpf=cpf_norm)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError({"cpf": "Já existe um representante com este CPF para este cliente."})
        return attrs

    def _copy_client_address_if_needed(self, obj: Representante):
        """
        Copia endereço do cliente para o representante se usa_endereco_do_cliente=True.
        """
        if not obj.usa_endereco_do_cliente:
            return

        cliente = obj.cliente
        dirty = False

        for field in ["logradouro", "numero", "bairro", "cidade", "cep", "uf"]:
            new_val = getattr(cliente, field)
            if getattr(obj, field) != new_val:
                setattr(obj, field, new_val)
                dirty = True

        if dirty:
            obj.save(update_fields=["logradouro", "numero", "bairro", "cidade", "cep", "uf"])

    @transaction.atomic
    def create(self, validated_data):
        obj = super().create(validated_data)
        self._copy_client_address_if_needed(obj)
        return obj

    @transaction.atomic
    def update(self, instance, validated_data):
        obj = super().update(instance, validated_data)
        self._copy_client_address_if_needed(obj)
        return obj

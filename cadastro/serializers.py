from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import Cliente, ContaBancaria, ContaBancariaReu, DescricaoBanco, Representante, Contrato
from .validators import only_digits, validate_cpf, validate_cnpj, validate_cep, validate_uf, validate_banco_id


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
            # Status
            "is_active",
            # Auditoria
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["criado_em", "atualizado_em"]
        extra_kwargs = {
            "cpf": {"validators": []}  # Remove validadores padrão de unicidade
        }

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

    def validate(self, attrs):
        """
        Validação customizada: permite CPF duplicado se o cliente estiver inativo.
        Valida manualmente a unicidade do CPF (já que removemos os validadores padrão).
        """
        # Só valida se estamos criando (não editando)
        if not self.instance:
            cpf = attrs.get("cpf")
            if cpf:
                cpf_normalizado = only_digits(cpf)
                # Verifica se já existe cliente com este CPF
                cliente_existente = Cliente.objects.filter(cpf=cpf_normalizado).first()
                if cliente_existente:
                    if cliente_existente.is_active:
                        # Se está ativo, não permite duplicar
                        raise ValidationError(
                            {"cpf": ["Já existe um cliente ativo com este CPF."]}
                        )
                    # Se está inativo, não levanta erro aqui (será tratado no create)
        return attrs

    def create(self, validated_data):
        """
        Cria um novo cliente ou restaura um cliente inativo com o mesmo CPF.
        - Se o CPF não existe: cria normalmente
        - Se o CPF existe e está ativo: retorna erro
        - Se o CPF existe e está inativo: atualiza com os novos dados e ativa
        (retorna como se fosse um novo cadastro, sem indicar que já existia)
        """
        cpf = validated_data.get("cpf")
        cpf_normalizado = only_digits(cpf) if cpf else None

        if cpf_normalizado:
            # Busca cliente existente com este CPF (ativo ou inativo)
            cliente_existente = Cliente.objects.filter(cpf=cpf_normalizado).first()

            if cliente_existente:
                if cliente_existente.is_active:
                    # Cliente ativo já existe com este CPF
                    raise ValidationError(
                        {"cpf": ["Já existe um cliente ativo com este CPF."]}
                    )
                else:
                    # Cliente inativo encontrado: atualiza e ativa
                    # Remove campos que não devem ser atualizados diretamente
                    validated_data.pop("id", None)
                    validated_data.pop("criado_em", None)
                    validated_data.pop("atualizado_em", None)
                    
                    # Atualiza o cliente existente com os novos dados
                    for attr, value in validated_data.items():
                        if hasattr(cliente_existente, attr) and attr not in ["id", "criado_em", "atualizado_em"]:
                            setattr(cliente_existente, attr, value)
                    
                    # Ativa o cliente
                    cliente_existente.is_active = True
                    
                    # Salva o cliente (update_fields não é necessário aqui pois estamos atualizando o mesmo registro)
                    # O Django não valida unicidade do CPF ao atualizar o mesmo registro
                    cliente_existente.save()
                    
                    # Retorna o cliente restaurado (como se fosse um novo cadastro)
                    return cliente_existente

        # CPF não existe ou não foi fornecido: cria novo cliente
        return super().create(validated_data)


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
# Conta Bancária do Réu
# =========================
class ContaBancariaReuSerializer(serializers.ModelSerializer):
    """
    Serializer para bancos dos réus.
    Armazena informações do banco: nome, CNPJ e endereço.
    """
    class Meta:
        model = ContaBancariaReu
        fields = [
            "id",
            "banco_nome",
            "banco_codigo",
            "cnpj",
            "descricao",
            # Endereço
            "logradouro",
            "numero",
            "bairro",
            "cidade",
            "estado",
            "cep",
            # Auditoria
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["criado_em", "atualizado_em"]

    # Normalizações
    def validate_cnpj(self, v):
        v = only_digits(v)
        validate_cnpj(v)
        return v

    def validate_cep(self, v):
        v = only_digits(v or "")
        if v:
            validate_cep(v)
        return v

    def validate_estado(self, v):
        v = (v or "").upper()
        if v:
            validate_uf(v)
        return v


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


# =========================
# Contrato
# =========================
class ContratoSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome_completo", read_only=True)
    template_nome = serializers.CharField(source="template.name", read_only=True)

    class Meta:
        model = Contrato
        fields = [
            "id",
            "cliente",
            "cliente_nome",
            "template",
            "template_nome",
            "contratos",
            "verifica_documento",
            "imagem_do_contrato",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["criado_em", "atualizado_em"]

    def validate_contratos(self, value):
        """
        Valida que contratos é uma lista e que cada item tem a estrutura esperada.
        Campos esperados em cada item:
        - numero_do_contrato: string (opcional)
        - banco_do_contrato: string (opcional)
        - situacao: string (opcional)
        - origem_averbacao: string (opcional)
        - data_inclusao: string (opcional)
        - data_inicio_desconto: string (opcional)
        - data_fim_desconto: string (opcional)
        - quantidade_parcelas: number (opcional)
        - valor_parcela: number (opcional)
        - iof: number (opcional)
        - valor_emprestado: number (opcional)
        - valor_liberado: number (opcional)
        """
        if not isinstance(value, list):
            raise ValidationError("O campo 'contratos' deve ser uma lista.")
        
        # Valida que cada item é um dicionário (objeto)
        for idx, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValidationError(
                    f"O item {idx} do array 'contratos' deve ser um objeto (dicionário)."
                )
        
        return value

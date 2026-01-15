from django.conf import settings
from django.db import models
from django.db.models import Q

from .validators import validate_cpf, validate_cnpj, validate_cep, validate_uf, only_digits


# (Opcional) choices simples para estado civil — pode ajustar no futuro no front/back
ESTADO_CIVIL_CHOICES = [
    ("solteiro", "Solteiro(a)"),
    ("casado", "Casado(a)"),
    ("divorciado", "Divorciado(a)"),
    ("viuvo", "Viúvo(a)"),
    ("uniao_estavel", "União estável"),
]


class Cliente(models.Model):
    # Identificação
    nome_completo = models.CharField(max_length=200, db_index=True)
    cpf = models.CharField(max_length=11, unique=True, validators=[validate_cpf])
    rg = models.CharField(max_length=20, blank=True)
    orgao_expedidor = models.CharField(max_length=20, blank=True)

    # ⚠️ Campo legado: mantido no schema, mas não usar no front (deixar oculto na UI)
    qualificacao = models.TextField(blank=True)  # [DEPRECADO] manter por compatibilidade

    # Sinalizadores de prioridade/condição
    se_idoso = models.BooleanField(default=False)
    se_incapaz = models.BooleanField(default=False)
    se_crianca_adolescente = models.BooleanField(default=False)

    # Dados civis
    nacionalidade = models.CharField(max_length=60, blank=True)
    estado_civil = models.CharField(max_length=20, blank=True)  # ou choices=ESTADO_CIVIL_CHOICES
    profissao = models.CharField(max_length=120, blank=True)

    # Endereço
    logradouro = models.CharField(max_length=120, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    cep = models.CharField(max_length=8, blank=True, validators=[validate_cep])
    uf = models.CharField(max_length=2, blank=True, validators=[validate_uf])

    # Status (soft delete)
    is_active = models.BooleanField(default=True, db_index=True)

    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome_completo"]

    def clean(self):
        # Normalizações simples
        self.cpf = only_digits(self.cpf)
        self.cep = only_digits(self.cep)
        self.uf = (self.uf or "").upper()

    def __str__(self):
        return f"{self.nome_completo} ({self.cpf})"


TIPO_CONTA_CHOICES = [
    ("corrente", "Corrente"),
    ("poupanca", "Poupança"),
    ("salario", "Salário"),
]


class ContaBancaria(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="contas")
    banco_nome = models.CharField(max_length=100)               # Ex.: "Banco do Brasil"
    banco_codigo = models.CharField(max_length=5, blank=True)   # Ex.: "001" (COMPE/ISPB curta)
    agencia = models.CharField(max_length=10)
    conta = models.CharField(max_length=20)
    digito = models.CharField(max_length=5, blank=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CONTA_CHOICES, default="corrente")
    is_principal = models.BooleanField(default=False)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("cliente", "banco_nome", "agencia", "conta", "digito")]
        ordering = ["cliente", "banco_nome", "agencia", "conta"]
        constraints = [
            models.UniqueConstraint(
                fields=["cliente"],
                condition=Q(is_principal=True),
                name="unique_principal_per_cliente",
            )
        ]

    def __str__(self):
        dd = f"-{self.digito}" if self.digito else ""
        return f"{self.cliente.nome_completo} | {self.banco_nome} ag {self.agencia} conta {self.conta}{dd}"


class DescricaoBanco(models.Model):
    """
    Múltiplas descrições por banco (persistência local).
    - 'banco_id': identificador estável (ISPB preferencial; se não houver, COMPE).
    - 'is_ativa': somente uma descrição pode estar ativa por banco (enforced por constraint).
    """
    banco_id = models.CharField(max_length=32, db_index=True)     # <- REMOVIDO unique=True
    banco_nome = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)
    is_ativa = models.BooleanField(default=False)

    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="descricoes_banco_editadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Descrição de Banco"
        verbose_name_plural = "Descrições de Banco"
        ordering = ["banco_nome", "-is_ativa", "-atualizado_em"]
        constraints = [
            # Garante no máximo 1 ativa por banco_id
            models.UniqueConstraint(
                fields=["banco_id"],
                condition=Q(is_ativa=True),
                name="unique_active_descricaobanco_per_bank",
            ),
        ]
        indexes = [
            models.Index(fields=["banco_id", "atualizado_em"]),
        ]

    def __str__(self) -> str:
        estrela = " *" if self.is_ativa else ""
        return f"{self.banco_nome} ({self.banco_id}){estrela}"


# --------------------------------------------------------------------
# Representantes do Cliente
# --------------------------------------------------------------------
class Representante(models.Model):
    """
    Pessoa que representa o Cliente (pode haver vários).
    - Se 'usa_endereco_do_cliente' for True, o front pode copiar os campos de endereço do Cliente.
      (Manteremos apenas a flag aqui; a cópia efetiva pode ser feita no front/serializer.)
    - Evitamos duplicidade por (cliente, cpf).
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="representantes")

    # Identificação
    nome_completo = models.CharField(max_length=200, db_index=True)
    cpf = models.CharField(max_length=11, validators=[validate_cpf])
    rg = models.CharField(max_length=20, blank=True)
    orgao_expedidor = models.CharField(max_length=20, blank=True)

    # Sinalizadores (mantidos iguais ao Cliente, caso necessários em templates)
    se_idoso = models.BooleanField(default=False)
    se_incapaz = models.BooleanField(default=False)
    se_crianca_adolescente = models.BooleanField(default=False)

    # Dados civis
    nacionalidade = models.CharField(max_length=60, blank=True)
    estado_civil = models.CharField(max_length=20, blank=True)  # ou choices=ESTADO_CIVIL_CHOICES
    profissao = models.CharField(max_length=120, blank=True)

    # Endereço
    usa_endereco_do_cliente = models.BooleanField(default=False)
    logradouro = models.CharField(max_length=120, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    cep = models.CharField(max_length=8, blank=True, validators=[validate_cep])
    uf = models.CharField(max_length=2, blank=True, validators=[validate_uf])

    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cliente", "nome_completo"]
        constraints = [
            # Evita duplicar o mesmo CPF para o mesmo cliente (mas permite o mesmo CPF representar clientes diferentes)
            models.UniqueConstraint(
                fields=["cliente", "cpf"],
                name="unique_representante_por_cliente",
            ),
        ]
        indexes = [
            models.Index(fields=["cliente", "nome_completo"]),
        ]

    def clean(self):
        self.cpf = only_digits(self.cpf)
        self.cep = only_digits(self.cep)
        self.uf = (self.uf or "").upper()

    def __str__(self):
        return f"{self.nome_completo} (rep. de {self.cliente.nome_completo})"


# --------------------------------------------------------------------
# Bancos dos Réus (Clientes como Réus)
# --------------------------------------------------------------------
class ContaBancariaReu(models.Model):
    """
    Banco do réu.
    Armazena informações do banco: nome, CNPJ e endereço.
    Não está mais atrelado a um cliente específico.
    """
    banco_nome = models.CharField(max_length=100)               # Ex.: "Banco do Brasil"
    banco_codigo = models.CharField(max_length=5, blank=True)   # Ex.: "001" (COMPE/ISPB curta)
    cnpj = models.CharField(max_length=14, unique=True, validators=[validate_cnpj])  # CNPJ do banco (único)
    descricao = models.TextField(blank=True)                   # Descrição do banco
    
    # Endereço do banco
    logradouro = models.CharField(max_length=120, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    estado = models.CharField(max_length=2, blank=True, validators=[validate_uf])  # UF do estado
    cep = models.CharField(max_length=8, blank=True, validators=[validate_cep])

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Banco do Réu"
        verbose_name_plural = "Bancos dos Réus"
        ordering = ["banco_nome"]

    def clean(self):
        self.cnpj = only_digits(self.cnpj)
        self.cep = only_digits(self.cep)
        self.estado = (self.estado or "").upper()

    def __str__(self):
        return f"{self.banco_nome} - CNPJ: {self.cnpj}"


# --------------------------------------------------------------------
# Contratos
# --------------------------------------------------------------------
class Contrato(models.Model):
    """
    Contrato vinculado a um Cliente e Template.
    - O campo 'contratos' armazena um array JSONB com os dados de cada contrato.
    - Pode haver múltiplos contratos no array.
    - Cada item do array pode conter:
      * numero_do_contrato: string
      * banco_do_contrato: string
      * situacao: string
      * origem_averbacao: string
      * data_inclusao: string (date)
      * data_inicio_desconto: string (date)
      * data_fim_desconto: string (date)
      * quantidade_parcelas: number
      * valor_parcela: number
      * iof: number
      * valor_emprestado: number
      * valor_liberado: number
    """
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,  # Não permite deletar cliente se tiver contratos
        related_name="contratos"
    )
    template = models.ForeignKey(
        "templates_app.Template",  # Importação lazy para evitar dependência circular
        on_delete=models.PROTECT,  # Não permite deletar template se tiver contratos
        related_name="contratos"
    )
    contratos = models.JSONField(
        default=list,
        blank=True,
        help_text="Array JSONB com os dados de cada contrato"
    )
    verifica_documento = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="JSONB com todos os dados do formulário de verificação do documento"
    )
    imagem_do_contrato = models.ImageField(
        upload_to="contratos/",
        null=True,
        blank=True,
        help_text="Imagem do contrato"
    )

    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"
        ordering = ["-criado_em"]

    def __str__(self):
        num_contratos = len(self.contratos) if isinstance(self.contratos, list) else 0
        return f"Contrato #{self.id} - {self.cliente.nome_completo} ({num_contratos} contrato(s))"

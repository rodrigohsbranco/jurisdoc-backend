from django.conf import settings
from django.db import models
from django.db.models import Q

from .validators import validate_cpf, validate_cep, validate_uf, only_digits


class Cliente(models.Model):
    # Identificação
    nome_completo = models.CharField(max_length=200, db_index=True)
    cpf = models.CharField(max_length=11, unique=True, validators=[validate_cpf])
    rg = models.CharField(max_length=20, blank=True)
    orgao_expedidor = models.CharField(max_length=20, blank=True)
    qualificacao = models.TextField(blank=True)  # narrativa livre opcional
    se_idoso = models.BooleanField(default=False)

    # Endereço
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
    banco_codigo = models.CharField(max_length=5, blank=True)   # Ex.: "001" (COMPE)
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

from django.db import models
from django.conf import settings

from cadastro.models import Cliente

# Opcional: você pode mover esses choices para outro lugar depois
SITUACAO_CONTRATO_CHOICES = [
    ("ativo", "Ativo"),
    ("suspenso", "Suspenso"),
    ("baixado", "Baixado"),
    ("encerrado", "Encerrado"),
]

ORIGEM_AVERBACAO_CHOICES = [
    ("consignado", "Consignado"),
    ("cartao", "Cartão consignado"),
    ("refin", "Refinanciamento"),
    ("portabilidade", "Portabilidade"),
    ("outros", "Outros"),
]


class Contrato(models.Model):
    """
    Contrato financeiro vinculado a um Cliente.
    Esses dados vão alimentar depois a geração de petição/arquivo.
    Um cliente pode ter N contratos.
    """

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name="contratos",
    )

    # Identificação
    numero_contrato = models.CharField(max_length=50, db_index=True)

    # Banco (pode vir de cadastro, mas aqui deixamos livre)
    banco_nome = models.CharField("Banco", max_length=120)
    # opcional: para integrar com DescricaoBanco, se quiser
    banco_id = models.CharField(
        "Código do banco",
        max_length=32,
        blank=True,
        help_text="COMPE/ISPB ou identificador interno",
    )

    situacao = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name='Situação'
    )


    origem_averbacao = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name='Origem da Averbação'
    )


    # Datas
    data_inclusao = models.DateField(null=True, blank=True)
    data_inicio_desconto = models.DateField(null=True, blank=True)
    data_fim_desconto = models.DateField(null=True, blank=True)

    # Financeiro
    quantidade_parcelas = models.PositiveIntegerField(null=True, blank=True)
    valor_parcela = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    iof = models.DecimalField(
        "IOF",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    valor_emprestado = models.DecimalField(
        "Emprestado",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    valor_liberado = models.DecimalField(
        "Liberado",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Livre para o advogado
    observacoes = models.TextField(blank=True)

    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contratos_criados",
    )

    class Meta:
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"
        ordering = ["-criado_em", "cliente", "numero_contrato"]
        indexes = [
            models.Index(fields=["cliente", "numero_contrato"]),
        ]
        constraints = [
            # não é UNIQUE duro porque pode haver recontratação mesmo número,
            # mas podemos impedir duplicação simples por cliente+numero_contrato se vc quiser
            # models.UniqueConstraint(
            #     fields=["cliente", "numero_contrato"],
            #     name="unique_contrato_por_cliente",
            # ),
        ]

    def __str__(self) -> str:
        return f"{self.cliente.nome_completo} - {self.numero_contrato}"

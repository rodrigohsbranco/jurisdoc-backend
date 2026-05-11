from django.conf import settings
from django.db import models

from cadastro.models import Cliente


class Kit(models.Model):
    TIPO_CHOICES = [
        ("bancario", "Bancário"),
        ("previdenciario", "Previdenciário"),
        ("marketing", "Marketing"),
    ]

    STATUS_CHOICES = [
        ("rascunho", "Rascunho"),
        ("acoes", "Em andamento"),
        ("finalizado", "Finalizado"),
        ("assinado", "Assinado"),
    ]

    tipo = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        default="bancario",
    )
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name="kits",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kits_criados",
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default="rascunho",
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        indexes = [
            models.Index(fields=["criado_por", "-criado_em"]),
            models.Index(fields=["cliente", "-criado_em"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Kit #{self.id} ({self.get_tipo_display()}) - {self.cliente.nome_completo} ({self.get_status_display()})"


class AcaoKit(models.Model):
    TIPO_ACAO_CHOICES = [
        ("cartao_credito_consignado", "Cartão de Crédito Consignado"),
        ("rmc", "RMC"),
        ("rcc", "RCC"),
        ("emprestimo_nao_autorizado", "Empréstimo Não Autorizado"),
        ("tarifa_bancaria", "Tarifa Bancária"),
        ("contribuicao_sindical_nao_autorizada", "Contribuição Sindical Não Autorizada"),
        ("seguro_nao_autorizado", "Seguro Não Autorizado"),
    ]

    kit = models.ForeignKey(
        Kit,
        on_delete=models.CASCADE,
        related_name="acoes",
    )
    tipo_acao = models.CharField(max_length=50, choices=TIPO_ACAO_CHOICES)
    nome_banco = models.CharField(max_length=100, blank=True)
    banco_outro = models.CharField(max_length=100, blank=True)
    numero_contrato = models.CharField(max_length=500, blank=True)
    tarifa_questionada = models.CharField(max_length=100, blank=True)
    tarifa_questionada_outro = models.CharField(max_length=255, blank=True)
    tipo_seguro = models.TextField(blank=True)
    tipo_contribuicao = models.TextField(blank=True)

    historico_emprestimo = models.FileField(upload_to="kits/acoes/", blank=True)
    historico_credito = models.FileField(upload_to="kits/acoes/", blank=True)
    extrato_bancario = models.FileField(upload_to="kits/acoes/", blank=True)
    historico_emprestimo_arquivos = models.JSONField(default=list, blank=True)
    historico_credito_arquivos = models.JSONField(default=list, blank=True)
    extrato_bancario_arquivos = models.JSONField(default=list, blank=True)

    associacao = models.ForeignKey(
        "AssociacaoKit",
        on_delete=models.SET_NULL,
        related_name="acoes",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Ação do Kit"
        verbose_name_plural = "Ações do Kit"
        ordering = ["id"]

    def __str__(self):
        banco = self.banco_outro if self.nome_banco == "Outro" else self.nome_banco
        return f"{self.get_tipo_acao_display()} - {banco}"


class DocumentoKit(models.Model):
    TIPO_CHOICES = [
        ("contrato", "Contrato de Prestação de Serviços"),
        ("procuracao", "Procuração"),
        ("hipossuficiencia", "Declaração de Hipossuficiência"),
        ("ciencia", "Declaração de Ciência"),
        ("domicilio", "Declaração de Domicílio"),
    ]

    kit = models.ForeignKey(
        Kit,
        on_delete=models.CASCADE,
        related_name="documentos",
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    arquivo = models.FileField(upload_to="kits/documentos/")
    gerado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Documento do Kit"
        verbose_name_plural = "Documentos do Kit"
        ordering = ["tipo"]

    def __str__(self):
        return f"{self.get_tipo_display()} - Kit #{self.kit_id}"


class BancoKit(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    ativo = models.BooleanField(default=True)
    ordem = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Banco"
        verbose_name_plural = "Bancos"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class TarifaKit(models.Model):
    nome = models.CharField(max_length=200, unique=True)
    ativo = models.BooleanField(default=True)
    ordem = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Tarifa"
        verbose_name_plural = "Tarifas"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class AssociacaoKit(models.Model):
    nome = models.CharField(max_length=200, unique=True)
    abreviacao = models.CharField(max_length=30, blank=True)
    ativo = models.BooleanField(default=True)
    ordem = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Associação"
        verbose_name_plural = "Associações"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.abreviacao or self.nome

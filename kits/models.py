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

    ORIGEM_CHOICES = [
        ("jurisdoc", "JurisDoc"),
        ("app", "App Flowalr"),
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

    origem = models.CharField(
        max_length=10,
        choices=ORIGEM_CHOICES,
        default="jurisdoc",
        db_index=True,
    )
    app_criado_por_nome = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Nome do usuário do app que criou o kit (preenchido quando origem='app')",
    )

    clausula_porcentagem_snapshot = models.TextField(blank=True, default="")
    advogados_snapshot = models.JSONField(default=list, blank=True)

    # Integração ZapSign — assinatura eletrônica
    zapsign_doc_token = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    zapsign_sign_url = models.URLField(max_length=500, null=True, blank=True)
    zapsign_status = models.CharField(max_length=20, null=True, blank=True)

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
        ("assinado_zapsign", "Kit Assinado (ZapSign)"),
    ]

    kit = models.ForeignKey(
        Kit,
        on_delete=models.CASCADE,
        related_name="documentos",
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    arquivo = models.FileField(upload_to="kits/documentos/")
    gerado_em = models.DateTimeField(auto_now_add=True)
    zapsign_doc_token = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    zapsign_sign_url = models.URLField(max_length=500, null=True, blank=True)
    zapsign_status = models.CharField(max_length=20, null=True, blank=True)

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


class ClausulaPorcentagemPadrao(models.Model):
    """Texto padrão da cláusula de porcentagem do contrato do Kit.

    Singleton: sempre existe exatamente uma linha (pk=1). Usado quando a
    UF do cliente não tem variação cadastrada em ClausulaPorcentagemUF.
    """

    texto = models.TextField(blank=True, default="")
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "Cláusula de porcentagem — padrão"
        verbose_name_plural = "Cláusula de porcentagem — padrão"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Não permite apagar o singleton.
        return

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Cláusula de porcentagem — padrão"


class ClausulaPorcentagemUF(models.Model):
    """Variação da cláusula de porcentagem para uma UF (opcionalmente
    restrita a um tipo de ação específico).

    Sobrescreve o ClausulaPorcentagemPadrao. Quando tipo_acao=="",
    é uma variação genérica daquela UF (vale para qualquer ação).
    """

    uf = models.CharField(max_length=2)
    tipo_acao = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Tipo de ação ao qual a variação se aplica. "
        "Vazio = variação genérica para qualquer ação naquela UF.",
    )
    texto = models.TextField()
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["uf", "tipo_acao"]
        verbose_name = "Cláusula de porcentagem — variação por UF"
        verbose_name_plural = "Cláusula de porcentagem — variações por UF"
        constraints = [
            models.UniqueConstraint(
                fields=["uf", "tipo_acao"],
                name="unique_clausula_uf_tipo",
            ),
        ]

    def __str__(self):
        suf = f"/{self.tipo_acao}" if self.tipo_acao else ""
        return f"Cláusula de porcentagem — {self.uf}{suf}"


def resolver_clausula_porcentagem(
    uf: str | None,
    tipos_acao: list[str] | None = None,
) -> tuple[str, str]:
    """Retorna (texto, fonte) para a UF/tipos de ação do kit.

    Cascata:
      1) Para cada tipo em tipos_acao (ordem): se existir (UF, tipo) → "uf_tipo"
      2) Se nada bateu: (UF, "") → "uf"
      3) Senão: padrão → "padrao"

    fonte ∈ {"uf_tipo", "uf", "padrao"}.

    Precedência: "tarifa_bancaria" sempre vem primeiro. Em kits com ações
    mistas (ex.: tarifa + RMC), a cláusula de tarifa (40% direto) deve
    prevalecer sobre as demais (30% + 10%), independentemente da ordem de
    criação das ações.
    """
    uf = (uf or "").strip().upper()
    tipos_acao = [t for t in (tipos_acao or []) if t]
    # Ordenação estável: tarifa_bancaria à frente, resto mantém ordem original.
    tipos_acao = sorted(tipos_acao, key=lambda t: 0 if t == "tarifa_bancaria" else 1)

    if uf:
        # 1) Específica (UF + tipo) — primeira que bater
        for tipo in tipos_acao:
            var = (
                ClausulaPorcentagemUF.objects
                .filter(uf=uf, tipo_acao=tipo)
                .first()
            )
            if var:
                return var.texto, "uf_tipo"

        # 2) Genérica (UF + tipo_acao="")
        var = (
            ClausulaPorcentagemUF.objects
            .filter(uf=uf, tipo_acao="")
            .first()
        )
        if var:
            return var.texto, "uf"

    return ClausulaPorcentagemPadrao.get_solo().texto, "padrao"

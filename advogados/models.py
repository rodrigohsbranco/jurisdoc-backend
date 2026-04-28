from django.db import models


class Advogado(models.Model):
    GENERO_CHOICES = [
        ("masculino", "Masculino"),
        ("feminino", "Feminino"),
    ]

    nome_completo = models.CharField(max_length=200)
    nacionalidade = models.CharField(max_length=60, default="brasileiro")
    estado_civil = models.CharField(max_length=20, blank=True)
    genero = models.CharField(max_length=15, choices=GENERO_CHOICES, default="masculino")
    is_socio = models.BooleanField(default=False, help_text="Sócio do escritório Azevedo Lima & Rebonatto")
    escritorio_nome = models.CharField(max_length=200, blank=True, help_text="Nome do escritório individual (não-sócios)")
    escritorio_cnpj = models.CharField(max_length=20, blank=True, help_text="CNPJ do escritório individual")
    escritorio_endereco = models.TextField(blank=True, help_text="Endereço completo do escritório individual")
    ativo = models.BooleanField(default=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_socio", "nome_completo"]
        verbose_name = "Advogado"
        verbose_name_plural = "Advogados"

    def __str__(self):
        sufixo = " (sócio)" if self.is_socio else ""
        return f"{self.nome_completo}{sufixo}"


class OabUf(models.Model):
    advogado = models.ForeignKey(
        Advogado,
        on_delete=models.CASCADE,
        related_name="oabs",
    )
    uf = models.CharField(max_length=2)
    numero_oab = models.CharField(max_length=50, help_text="Ex: OAB/SC nº 36672")
    unidade_apoio_nome = models.CharField(max_length=100, blank=True, help_text="Ex: Salvador")
    unidade_apoio_endereco = models.TextField(blank=True, help_text="Endereço completo da unidade de apoio")

    class Meta:
        ordering = ["uf"]
        verbose_name = "OAB por UF"
        verbose_name_plural = "OABs por UF"
        constraints = [
            models.UniqueConstraint(
                fields=["advogado", "uf"],
                name="unique_advogado_uf",
            ),
        ]

    def __str__(self):
        return f"{self.advogado.nome_completo} — {self.numero_oab} ({self.uf})"

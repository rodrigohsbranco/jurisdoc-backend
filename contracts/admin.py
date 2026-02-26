from django.contrib import admin
from .models import Contrato


@admin.register(Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = (
        "numero_contrato",
        "cliente",
        "banco_nome",
        "situacao",
        "origem_averbacao",
        "valor_emprestado",
        "valor_liberado",
        "data_inclusao",
        "criado_por",
        "criado_em",
    )

    list_filter = (
        "situacao",
        "origem_averbacao",
        "banco_nome",
        "criado_em",
    )

    search_fields = (
        "numero_contrato",
        "cliente__nome_completo",
        "banco_nome",
    )

    date_hierarchy = "data_inclusao"
    ordering = ("-criado_em",)
    autocomplete_fields = ("cliente",)
    readonly_fields = ("criado_em", "atualizado_em")

    fieldsets = (
        ("Informações do Contrato", {
            "fields": (
                "cliente",
                "numero_contrato",
                "banco_nome",
                "banco_id",
                "situacao",
                "origem_averbacao",
                "observacoes",
            )
        }),
        ("Datas", {
            "fields": (
                "data_inclusao",
                "data_inicio_desconto",
                "data_fim_desconto",
            )
        }),
        ("Valores", {
            "fields": (
                "quantidade_parcelas",
                "valor_parcela",
                "iof",
                "valor_emprestado",
                "valor_liberado",
            )
        }),
        ("Auditoria", {
            "fields": (
                "criado_por",
                "criado_em",
                "atualizado_em",
            )
        }),
    )

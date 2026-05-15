from django.contrib import admin

from .models import Capacidade, Permissao


@admin.register(Capacidade)
class CapacidadeAdmin(admin.ModelAdmin):
    list_display = ("codigo", "categoria", "recurso", "acao")
    list_filter = ("categoria", "recurso")
    search_fields = ("codigo", "recurso", "acao", "descricao")
    ordering = ("categoria", "recurso", "acao")


@admin.register(Permissao)
class PermissaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "qtd_capacidades", "criado_em", "atualizado_em")
    search_fields = ("nome", "descricao")
    filter_horizontal = ("capacidades",)
    readonly_fields = ("criado_em", "atualizado_em", "criado_por")

    @admin.display(description="Capacidades")
    def qtd_capacidades(self, obj):
        return obj.capacidades.count()

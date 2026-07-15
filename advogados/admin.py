from django.contrib import admin

from .models import Advogado, OabUf


class OabUfInline(admin.TabularInline):
    model = OabUf
    extra = 1


@admin.register(Advogado)
class AdvogadoAdmin(admin.ModelAdmin):
    list_display = ["nome_completo", "is_socio", "fixo_previdenciario", "ativo", "criado_em"]
    list_filter = ["is_socio", "fixo_previdenciario", "ativo"]
    search_fields = ["nome_completo"]
    inlines = [OabUfInline]
    readonly_fields = ["criado_em", "atualizado_em"]

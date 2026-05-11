from django.contrib import admin

from .models import AcaoKit, AssociacaoKit, BancoKit, DocumentoKit, Kit, TarifaKit


class AcaoKitInline(admin.TabularInline):
    model = AcaoKit
    extra = 0


class DocumentoKitInline(admin.TabularInline):
    model = DocumentoKit
    extra = 0
    readonly_fields = ["gerado_em"]


@admin.register(Kit)
class KitAdmin(admin.ModelAdmin):
    list_display = ["id", "cliente", "criado_por", "status", "criado_em", "atualizado_em"]
    list_filter = ["status", "criado_em"]
    search_fields = ["cliente__nome_completo", "cliente__cpf", "criado_por__username"]
    raw_id_fields = ["cliente", "criado_por"]
    inlines = [AcaoKitInline, DocumentoKitInline]
    readonly_fields = ["criado_em", "atualizado_em"]


@admin.register(AcaoKit)
class AcaoKitAdmin(admin.ModelAdmin):
    list_display = ["id", "kit", "tipo_acao", "nome_banco", "numero_contrato"]
    list_filter = ["tipo_acao"]
    search_fields = ["nome_banco", "numero_contrato"]
    raw_id_fields = ["kit"]


@admin.register(DocumentoKit)
class DocumentoKitAdmin(admin.ModelAdmin):
    list_display = ["id", "kit", "tipo", "gerado_em"]
    list_filter = ["tipo"]
    raw_id_fields = ["kit"]
    readonly_fields = ["gerado_em"]


@admin.register(AssociacaoKit)
class AssociacaoKitAdmin(admin.ModelAdmin):
    list_display = ["id", "nome", "abreviacao", "ativo", "ordem"]
    list_filter = ["ativo"]
    search_fields = ["nome", "abreviacao"]
    ordering = ["ordem", "nome"]

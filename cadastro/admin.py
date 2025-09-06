from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Cliente, ContaBancaria

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("id","nome_completo","cpf","cidade","uf","se_idoso","criado_em")
    search_fields = ("nome_completo","cpf","rg","cidade")
    list_filter = ("uf","se_idoso")
    autocomplete_fields = ()
    ordering = ("nome_completo",)

@admin.register(ContaBancaria)
class ContaBancariaAdmin(admin.ModelAdmin):
    list_display = ("id","cliente","banco_nome","agencia","conta","tipo","is_principal","criado_em")
    search_fields = ("cliente__nome_completo","banco_nome","agencia","conta")
    list_filter = ("tipo","is_principal")
    autocomplete_fields = ("cliente",)

from django.contrib import admin
from django.db import transaction

from .models import Cliente, ContaBancaria, DescricaoBanco, Representante


# =========================
# Cliente
# =========================
@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nome_completo",
        "cpf",
        "cidade",
        "uf",
        "se_idoso",
        "se_incapaz",
        "se_crianca_adolescente",
        "estado_civil",
        "profissao",
        "criado_em",
    )
    search_fields = ("nome_completo", "cpf", "rg", "cidade", "bairro", "profissao", "nacionalidade")
    list_filter = ("uf", "se_idoso", "se_incapaz", "se_crianca_adolescente", "estado_civil")
    ordering = ("nome_completo",)
    list_per_page = 50
    readonly_fields = ("criado_em", "atualizado_em")

    fieldsets = (
        ("Identificação", {
            "fields": ("nome_completo", "cpf", "rg", "orgao_expedidor"),
        }),
        ("Dados civis", {
            "fields": ("nacionalidade", "estado_civil", "profissao"),
        }),
        ("Endereço", {
            "fields": ("cep", "logradouro", "numero", "bairro", "cidade", "uf"),
        }),
        ("Sinalizadores", {
            "fields": ("se_idoso", "se_incapaz", "se_crianca_adolescente"),
        }),
        ("Outros", {
            # Mantemos no banco, mas você pode ocultar no front
            "classes": ("collapse",),
            "fields": ("qualificacao",),
        }),
        ("Auditoria", {
            "classes": ("collapse",),
            "fields": ("criado_em", "atualizado_em"),
        }),
    )


# =========================
# Conta Bancária
# =========================
@admin.register(ContaBancaria)
class ContaBancariaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cliente",
        "banco_nome",
        "banco_codigo",
        "agencia",
        "conta",
        "tipo",
        "is_principal",
        "criado_em",
    )
    search_fields = ("cliente__nome_completo", "banco_nome", "banco_codigo", "agencia", "conta")
    list_filter = ("tipo", "is_principal", "banco_nome", "banco_codigo")
    autocomplete_fields = ("cliente",)
    list_select_related = ("cliente",)  # evita N+1 no changelist
    list_per_page = 50
    readonly_fields = ("criado_em", "atualizado_em")


# =========================
# Descrição de Banco
# =========================
@admin.register(DescricaoBanco)
class DescricaoBancoAdmin(admin.ModelAdmin):
    """
    Admin para 'descrições por banco' (múltiplas por banco_id; 1 ativa por vez).
    """
    list_display = ("banco_id", "banco_nome", "is_ativa", "atualizado_por", "atualizado_em")
    search_fields = ("banco_id", "banco_nome", "descricao", "atualizado_por__username")
    list_filter = ("is_ativa", "banco_nome", "banco_id")
    ordering = ("banco_nome", "-is_ativa", "-atualizado_em")
    readonly_fields = ("criado_em", "atualizado_em")
    actions = ("marcar_como_ativa",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("atualizado_por")

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        # auditoria
        if request.user.is_authenticated:
            obj.atualizado_por = request.user
        super().save_model(request, obj, form, change)

        # se marcou esta como ativa, desativa as demais do mesmo banco_id
        if obj.is_ativa and obj.banco_id:
            DescricaoBanco.objects.filter(banco_id=obj.banco_id).exclude(pk=obj.pk).update(is_ativa=False)

    @admin.action(description="Marcar como ativa (desativando as demais do mesmo banco)")
    @transaction.atomic
    def marcar_como_ativa(self, request, queryset):
        """
        Para cada banco_id presente no queryset:
          - escolhe UMA descrição (a mais recente) para ficar ativa
          - desativa as demais daquele banco_id
        """
        by_bank = {}
        for obj in queryset:
            by_bank.setdefault(obj.banco_id, []).append(obj)

        total_ativadas = 0
        for bank_id, rows in by_bank.items():
            # escolhe a mais recente no queryset
            chosen = sorted(rows, key=lambda r: (r.atualizado_em, r.pk), reverse=True)[0]
            # desativa todas daquele banco_id
            DescricaoBanco.objects.filter(banco_id=bank_id, is_ativa=True).update(is_ativa=False)
            # ativa a escolhida
            if request.user.is_authenticated:
                chosen.atualizado_por = request.user
            chosen.is_ativa = True
            chosen.save(update_fields=["is_ativa", "atualizado_por", "atualizado_em"])
            total_ativadas += 1

        self.message_user(request, f"{total_ativadas} descrição(ões) marcada(s) como ativa(s).")


# =========================
# Representante
# =========================
@admin.register(Representante)
class RepresentanteAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cliente",
        "nome_completo",
        "cpf",
        "cidade",
        "uf",
        "usa_endereco_do_cliente",
        "se_idoso",
        "se_incapaz",
        "se_crianca_adolescente",
        "criado_em",
    )
    search_fields = (
        "nome_completo",
        "cpf",
        "cidade",
        "bairro",
        "profissao",
        "nacionalidade",
        "cliente__nome_completo",
    )
    list_filter = (
        "uf",
        "usa_endereco_do_cliente",
        "se_idoso",
        "se_incapaz",
        "se_crianca_adolescente",
        "estado_civil",
    )
    ordering = ("cliente__nome_completo", "nome_completo")
    autocomplete_fields = ("cliente",)
    list_select_related = ("cliente",)
    list_per_page = 50
    readonly_fields = ("criado_em", "atualizado_em")
    actions = ("usar_endereco_do_cliente",)

    fieldsets = (
        ("Vínculo", {"fields": ("cliente",)}),
        ("Identificação", {"fields": ("nome_completo", "cpf", "rg", "orgao_expedidor")}),
        ("Dados civis", {"fields": ("nacionalidade", "estado_civil", "profissao")}),
        ("Endereço", {
            "fields": ("usa_endereco_do_cliente", "cep", "logradouro", "numero", "bairro", "cidade", "uf"),
        }),
        ("Sinalizadores", {"fields": ("se_idoso", "se_incapaz", "se_crianca_adolescente")}),
        ("Auditoria", {"classes": ("collapse",), "fields": ("criado_em", "atualizado_em")}),
    )

    @admin.action(description="Copiar endereço do cliente para o(s) representante(s) selecionado(s)")
    @transaction.atomic
    def usar_endereco_do_cliente(self, request, queryset):
        atualizados = 0
        for rep in queryset.select_related("cliente"):
            c = rep.cliente
            # marca a flag e copia os campos
            rep.usa_endereco_do_cliente = True
            rep.cep = c.cep
            rep.logradouro = c.logradouro
            rep.numero = c.numero
            rep.bairro = c.bairro
            rep.cidade = c.cidade
            rep.uf = c.uf
            rep.save(update_fields=[
                "usa_endereco_do_cliente",
                "cep", "logradouro", "numero", "bairro", "cidade", "uf",
                "atualizado_em",
            ])
            atualizados += 1
        self.message_user(request, f"Endereço copiado para {atualizados} representante(s).")

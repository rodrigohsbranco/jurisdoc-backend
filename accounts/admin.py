from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AppClient, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Herda do UserAdmin do Django para usar formulário próprio de senha
    (hash automático) e o link "alterar senha" via /admin/.
    """
    list_display = (
        "id", "username", "email", "nome_completo",
        "is_admin", "is_staff", "is_active", "permissao",
    )
    list_filter = ("is_admin", "is_staff", "is_active", "permissao")
    search_fields = ("username", "email", "nome_completo", "first_name", "last_name")
    ordering = ("username",)

    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Dados pessoais (JurisDoc)", {
            "fields": ("nome_completo", "telefone", "endereco", "avatar"),
        }),
        ("Perfil JurisDoc", {
            "fields": ("is_admin", "permissao"),
        }),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("JurisDoc", {
            "classes": ("wide",),
            "fields": ("email", "nome_completo", "is_admin", "permissao"),
        }),
    )


@admin.register(AppClient)
class AppClientAdmin(admin.ModelAdmin):
    list_display = ("nome", "client_id", "is_active", "criado_em")
    list_filter = ("is_active",)
    search_fields = ("nome", "client_id")
    readonly_fields = ("client_id", "client_secret_hash", "criado_em", "atualizado_em")
    fields = ("nome", "client_id", "client_secret_hash", "is_active", "criado_em", "atualizado_em")

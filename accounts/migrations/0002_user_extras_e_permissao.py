from django.db import migrations, models


OPERADOR_CODES = [
    # Cadastro (CRUD completo + restaurar)
    "clientes.visualizar", "clientes.criar", "clientes.editar", "clientes.deletar", "clientes.restaurar",
    "contas.visualizar", "contas.criar", "contas.editar", "contas.deletar",
    "representantes.visualizar", "representantes.criar", "representantes.editar", "representantes.deletar",
    "conta_reu.visualizar", "conta_reu.criar", "conta_reu.editar", "conta_reu.deletar",
    # Documentos
    "templates.visualizar", "templates.renderizar",
    "peticoes.visualizar", "peticoes.criar", "peticoes.editar", "peticoes.deletar", "peticoes.renderizar",
    "contratos.visualizar", "contratos.criar", "contratos.editar", "contratos.deletar",
    "kits.visualizar", "kits.criar", "kits.editar", "kits.deletar",
    # Leitura de referências de sistema
    "advogados.visualizar",
    "bancos_tarifas.visualizar",
]


def backfill_and_seed(apps, schema_editor):
    """
    1) Preenche nome_completo a partir de first_name + last_name (ou username).
    2) Cria a Permissao "Operador" com capacidades operacionais padrão.
    3) Atribui "Operador" a todos os não-admins sem permissão.
    """
    User = apps.get_model("accounts", "User")
    Permissao = apps.get_model("permissoes", "Permissao")
    Capacidade = apps.get_model("permissoes", "Capacidade")

    # 1) Backfill nome_completo
    for u in User.objects.all():
        if not (u.nome_completo or "").strip():
            full = f"{u.first_name or ''} {u.last_name or ''}".strip()
            u.nome_completo = full or u.username
            u.save(update_fields=["nome_completo"])

    # 2) Cria Operador
    operador, _ = Permissao.objects.get_or_create(
        nome="Operador",
        defaults={
            "descricao": (
                "Perfil padrão com acesso operacional: cadastro de clientes, "
                "petições, contratos e produção de kits. Sem acesso à "
                "administração do sistema."
            ),
        },
    )
    caps = Capacidade.objects.filter(codigo__in=OPERADOR_CODES)
    operador.capacidades.add(*caps)

    # 3) Atribui Operador a não-admins sem permissão
    User.objects.filter(is_admin=False, permissao__isnull=True).update(permissao=operador)


def reverse_noop(apps, schema_editor):
    """Reverso é no-op para preservar dados; remoção manual via admin se preciso."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("permissoes", "0002_seed_capacidades"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="nome_completo",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="user",
            name="telefone",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="user",
            name="endereco",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="user",
            name="avatar",
            field=models.ImageField(blank=True, null=True, upload_to="avatars/"),
        ),
        migrations.AddField(
            model_name="user",
            name="permissao",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="usuarios",
                to="permissoes.permissao",
            ),
        ),
        migrations.RunPython(backfill_and_seed, reverse_noop),
    ]

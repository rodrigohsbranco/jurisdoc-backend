from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Capacidade",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(max_length=80, unique=True)),
                ("recurso", models.CharField(max_length=60)),
                ("acao", models.CharField(max_length=40)),
                ("descricao", models.CharField(max_length=200)),
                ("categoria", models.CharField(default="Outros", max_length=40)),
            ],
            options={
                "verbose_name": "Capacidade",
                "verbose_name_plural": "Capacidades",
                "ordering": ["categoria", "recurso", "acao"],
            },
        ),
        migrations.CreateModel(
            name="Permissao",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=80, unique=True)),
                ("descricao", models.TextField(blank=True, default="")),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                (
                    "capacidades",
                    models.ManyToManyField(
                        blank=True,
                        related_name="permissoes",
                        to="permissoes.capacidade",
                    ),
                ),
                (
                    "criado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="permissoes_criadas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Permissão",
                "verbose_name_plural": "Permissões",
                "ordering": ["nome"],
            },
        ),
    ]

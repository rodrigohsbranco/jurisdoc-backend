from django.db import migrations


def seed(apps, schema_editor):
    """Popula a tabela Capacidade com o catálogo inicial.
    Idempotente — pode rodar de novo sem efeito colateral."""
    Capacidade = apps.get_model("permissoes", "Capacidade")
    from permissoes.catalog import CAPACIDADES

    for entry in CAPACIDADES:
        Capacidade.objects.update_or_create(
            codigo=entry["codigo"],
            defaults={
                "recurso": entry["recurso"],
                "acao": entry["acao"],
                "descricao": entry["descricao"],
                "categoria": entry.get("categoria", "Outros"),
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("permissoes", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]

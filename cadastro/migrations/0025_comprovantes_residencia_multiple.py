from django.db import migrations, models


def migrate_files_to_json(apps, schema_editor):
    """Copia paths dos FileFields antigos para a lista JSON, com {path, name}."""
    Cliente = apps.get_model("cadastro", "Cliente")
    for c in Cliente.objects.all():
        comprovantes = []
        old_compr = getattr(c, "comprovante_residencia", None)
        if old_compr and getattr(old_compr, "name", ""):
            comprovantes.append({"path": old_compr.name, "name": old_compr.name.rsplit("/", 1)[-1]})

        docs = []
        old_resp_doc = getattr(c, "responsavel_imovel_doc", None)
        if old_resp_doc and getattr(old_resp_doc, "name", ""):
            docs.append({"path": old_resp_doc.name, "name": old_resp_doc.name.rsplit("/", 1)[-1]})

        if comprovantes or docs:
            c.comprovantes_residencia = comprovantes
            c.responsavel_imovel_docs = docs
            c.save(update_fields=["comprovantes_residencia", "responsavel_imovel_docs"])


def reverse_noop(apps, schema_editor):
    # Reverso não restaura os FileFields — os JSONFields ainda contêm os paths.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("cadastro", "0024_cliente_telefones_extras"),
    ]

    operations = [
        migrations.AddField(
            model_name="cliente",
            name="comprovantes_residencia",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Array JSON de comprovantes do cliente. Cada item: {path, name}",
            ),
        ),
        migrations.AddField(
            model_name="cliente",
            name="responsavel_imovel_docs",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Array JSON de documentos do responsável pelo imóvel. Cada item: {path, name}",
            ),
        ),
        migrations.RunPython(migrate_files_to_json, reverse_noop),
        migrations.RemoveField(model_name="cliente", name="comprovante_residencia"),
        migrations.RemoveField(model_name="cliente", name="responsavel_imovel_doc"),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kits", "0014_kit_app_fields"),
    ]

    operations = [
        # Campos ZapSign no Kit
        migrations.AddField(
            model_name="kit",
            name="zapsign_doc_token",
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="kit",
            name="zapsign_sign_url",
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name="kit",
            name="zapsign_status",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        # Novo tipo de documento para o PDF assinado via ZapSign
        migrations.AlterField(
            model_name="documentokit",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("contrato", "Contrato de Prestação de Serviços"),
                    ("procuracao", "Procuração"),
                    ("hipossuficiencia", "Declaração de Hipossuficiência"),
                    ("ciencia", "Declaração de Ciência"),
                    ("domicilio", "Declaração de Domicílio"),
                    ("assinado_zapsign", "Kit Assinado (ZapSign)"),
                ],
                max_length=20,
            ),
        ),
    ]

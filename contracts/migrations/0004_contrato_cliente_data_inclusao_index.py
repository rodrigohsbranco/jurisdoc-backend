# Generated manually for query performance.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0003_alter_contrato_origem_averbacao_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="contrato",
            index=models.Index(
                fields=["cliente", "-data_inclusao"],
                name="cont_cli_datainc_desc_idx",
            ),
        ),
    ]

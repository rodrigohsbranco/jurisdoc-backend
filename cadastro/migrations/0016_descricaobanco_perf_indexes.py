# Generated manually for performance indexes.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cadastro", "0015_merge_0007_alter_descricaobanco_options_and_more_0014_contabancariareu_descricao"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="descricaobanco",
            index=models.Index(
                fields=["banco_id", "is_ativa", "-atualizado_em"],
                name="cad_desc_bid_act_upd_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="descricaobanco",
            index=models.Index(
                fields=["banco_nome", "is_ativa", "-atualizado_em"],
                name="cad_desc_bname_act_upd_idx",
            ),
        ),
    ]

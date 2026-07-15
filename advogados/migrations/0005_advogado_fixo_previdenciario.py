from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("advogados", "0004_remove_advogado_tipos_acao_oabuf_tipos_acao"),
    ]

    operations = [
        migrations.AddField(
            model_name="advogado",
            name="fixo_previdenciario",
            field=models.BooleanField(
                default=False,
                help_text="Incluído automaticamente em todo kit previdenciário — o app não exibe etapa de seleção de advogados para esse tipo",
            ),
        ),
    ]

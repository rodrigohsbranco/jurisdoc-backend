from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kits", "0018_kit_honorarios_iniciais"),
    ]

    operations = [
        migrations.AddField(
            model_name="kit",
            name="zapsign_portal_token",
            field=models.UUIDField(
                blank=True,
                editable=False,
                help_text="Token público do portal de assinatura (/assinar/<token>/).",
                null=True,
                unique=True,
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_add_app_client"),
    ]

    operations = [
        migrations.AddField(
            model_name="appclient",
            name="is_admin",
            field=models.BooleanField(
                default=False,
                help_text="Permite acesso a endpoints de escrita (CRUD completo de clientes etc.)",
            ),
        ),
    ]

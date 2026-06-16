import secrets
from django.db import migrations


def create_app_flowalr(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    if not User.objects.filter(username="app_flowalr").exists():
        User.objects.create(
            username="app_flowalr",
            # Senha inutilizável — usuário nunca faz login direto
            password="!",
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )


def remove_app_flowalr(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(username="app_flowalr").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_appclient_is_admin"),
    ]

    operations = [
        migrations.RunPython(create_app_flowalr, reverse_code=remove_app_flowalr),
    ]

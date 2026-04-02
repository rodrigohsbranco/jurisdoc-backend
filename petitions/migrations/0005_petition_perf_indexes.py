# Generated manually for report/list performance.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("petitions", "0004_alter_petition_options"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="petition",
            index=models.Index(fields=["created_at"], name="pet_created_at_idx"),
        ),
        migrations.AddIndex(
            model_name="petition",
            index=models.Index(fields=["updated_at"], name="pet_updated_at_idx"),
        ),
        migrations.AddIndex(
            model_name="petition",
            index=models.Index(
                fields=["cliente", "-created_at"],
                name="pet_cliente_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="petition",
            index=models.Index(
                fields=["template", "-created_at"],
                name="pet_template_created_idx",
            ),
        ),
    ]

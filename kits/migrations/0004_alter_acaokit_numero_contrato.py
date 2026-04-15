from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kits", "0003_acaokit_tarifa_questionada_outro"),
    ]

    operations = [
        migrations.AlterField(
            model_name="acaokit",
            name="numero_contrato",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]

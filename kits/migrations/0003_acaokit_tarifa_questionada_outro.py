from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kits", "0002_acaokit_multiplos_arquivos"),
    ]

    operations = [
        migrations.AddField(
            model_name="acaokit",
            name="tarifa_questionada_outro",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]

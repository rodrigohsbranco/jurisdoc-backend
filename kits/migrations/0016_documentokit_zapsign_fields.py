from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kits", "0015_kit_zapsign_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentokit",
            name="zapsign_doc_token",
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="documentokit",
            name="zapsign_sign_url",
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name="documentokit",
            name="zapsign_status",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]

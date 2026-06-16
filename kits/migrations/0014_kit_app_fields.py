from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kits', '0013_alter_clausulaporcentagemuf_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='kit',
            name='origem',
            field=models.CharField(
                choices=[('jurisdoc', 'JurisDoc'), ('app', 'App Flowalr')],
                default='jurisdoc',
                max_length=10,
                db_index=True,
            ),
        ),
        migrations.AddField(
            model_name='kit',
            name='app_criado_por_nome',
            field=models.CharField(
                blank=True,
                default='',
                help_text="Nome do usuário do app que criou o kit (preenchido quando origem='app')",
                max_length=200,
            ),
        ),
    ]

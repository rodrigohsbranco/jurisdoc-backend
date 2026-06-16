from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cadastro', '0025_comprovantes_residencia_multiple'),
    ]

    operations = [
        migrations.AddField(
            model_name='cliente',
            name='complemento',
            field=models.CharField(blank=True, default='', max_length=100),
            preserve_default=False,
        ),
    ]

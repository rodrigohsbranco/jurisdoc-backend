# Generated manually to merge diverging migration branches in cadastro.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cadastro", "0007_alter_descricaobanco_options_and_more"),
        ("cadastro", "0014_contabancariareu_descricao"),
    ]

    operations = []

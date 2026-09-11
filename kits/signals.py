"""Limpeza de arquivos órfãos no storage.

Apagar um `DocumentoKit` no banco não apaga o arquivo em disco: o Django não faz
isso por conta própria. Sem este signal, todo caminho que remove registros deixa
lixo acumulando no MEDIA_ROOT — e os caminhos são vários, alguns indiretos:

  - o operador anexa a digitalização errada e remove;
  - o kit é excluído e o CASCADE leva os documentos junto (views.py e views_app.py);
  - qualquer `queryset.delete()` futuro, que nem passa pelo `Model.delete()`.

Centralizar aqui é o que garante que nenhum desses caminhos precise lembrar de
limpar — inclusive os que ainda não existem.
"""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import DocumentoKit


@receiver(post_delete, sender=DocumentoKit)
def apagar_arquivo_do_documento(sender, instance: DocumentoKit, **kwargs):
    """Remove o arquivo do storage depois que a remoção do registro efetiva.

    `on_commit` é essencial: se a transação que apagou o registro sofrer rollback,
    a linha volta ao banco — e um arquivo já apagado deixaria esse registro
    apontando para o vazio, que é pior do que o órfão que queremos evitar.
    """
    arquivo = instance.arquivo
    if not arquivo or not arquivo.name:
        return

    nome = arquivo.name
    storage = arquivo.storage

    def _remover():
        # `delete()` do storage é silencioso quando o arquivo já não existe, o
        # que cobre o caso de alguém ter limpado o disco por fora.
        storage.delete(nome)

    transaction.on_commit(_remover)

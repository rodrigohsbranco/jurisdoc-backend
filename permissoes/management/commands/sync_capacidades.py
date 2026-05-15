"""
Sincroniza o catálogo `permissoes/catalog.py` com a tabela Capacidade.

Uso:
    python manage.py sync_capacidades             # upsert
    python manage.py sync_capacidades --prune     # remove capacidades fora do catálogo
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from permissoes.catalog import CAPACIDADES
from permissoes.models import Capacidade


class Command(BaseCommand):
    help = "Sincroniza o catálogo de capacidades com a tabela Capacidade."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Remove capacidades existentes que não estão mais no catálogo.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        codigos_catalog = {c["codigo"] for c in CAPACIDADES}
        criadas, atualizadas = 0, 0

        for entry in CAPACIDADES:
            obj, created = Capacidade.objects.update_or_create(
                codigo=entry["codigo"],
                defaults={
                    "recurso": entry["recurso"],
                    "acao": entry["acao"],
                    "descricao": entry["descricao"],
                    "categoria": entry.get("categoria", "Outros"),
                },
            )
            if created:
                criadas += 1
            else:
                atualizadas += 1

        removidas = 0
        if options.get("prune"):
            qs = Capacidade.objects.exclude(codigo__in=codigos_catalog)
            removidas = qs.count()
            qs.delete()

        self.stdout.write(self.style.SUCCESS(
            f"OK: {criadas} criadas, {atualizadas} atualizadas, {removidas} removidas."
        ))

from django.apps import AppConfig


class KitsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'kits'

    def ready(self):
        # Limpeza de arquivos órfãos ao remover DocumentoKit.
        from . import signals  # noqa: F401

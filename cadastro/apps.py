from django.apps import AppConfig


class CadastroConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cadastro"
    verbose_name = "Cadastro"

    def ready(self):
        # Ponto de extensão para signals/hooks futuros.
        # Ex.: from . import signals  # noqa: F401
        pass

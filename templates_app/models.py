from django.db import models


class Template(models.Model):
    """
    Modelo de Template .docx usado para geração de petições/documentos.
    - Os placeholders devem seguir sintaxe Jinja {{ variavel }}.
    - Exemplo: {{ cliente_nome }}, {{ cpf }}, {{ banco }}.
    - O campo {{ banco }} será automaticamente preenchido com a
      descrição ativa do banco da conta principal do cliente.
    """

    name = models.CharField(max_length=120, unique=True)
    file = models.FileField(upload_to="templates/")
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

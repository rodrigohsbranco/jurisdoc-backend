from django.db import models

class Template(models.Model):
    name = models.CharField(max_length=120, unique=True)
    file = models.FileField(upload_to="templates/")
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

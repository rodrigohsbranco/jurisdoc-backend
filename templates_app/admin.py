from django.contrib import admin
from .models import Template
@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ("id","name","active")
    search_fields = ("name",)
    list_filter = ("active",)

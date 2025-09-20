from django.contrib import admin
from .models import Template
@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "active", "created_at", "updated_at")
    search_fields = ("name",)
    list_filter = ("active", "created_at")

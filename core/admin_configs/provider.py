from django.contrib import admin
from core.models import Provider

@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active")  # ajusta a tus campos reales
    list_filter = ("is_active",)
    search_fields = ("name",)

from django.contrib import admin
from core.models import CurrentResult

@admin.register(CurrentResult)
class CurrentResultAdmin(admin.ModelAdmin):
    list_display = ("id", "provider")  # pon campos reales
    list_filter = ("provider",)

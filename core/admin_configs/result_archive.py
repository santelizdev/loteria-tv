from django.contrib import admin
from core.models import ResultArchive

@admin.register(ResultArchive)
class ResultArchiveAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "draw_date")  # ajusta campos
    list_filter = ("provider",)

from django.contrib import admin
from core.models import AnimalitoArchive

@admin.register(AnimalitoArchive)
class AnimalitoArchiveAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "draw_date", "draw_time", "animal_number", "animal_name")
    list_filter = ("provider", "draw_date")
    search_fields = ("provider__name", "animal_name")
    ordering = ("-draw_date", "provider__name", "draw_time")

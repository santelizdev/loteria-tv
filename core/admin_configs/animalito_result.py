# core/admin_configs/animalito_result.py
from django.contrib import admin
from core.models.animalito_result import AnimalitoResult

@admin.register(AnimalitoResult)
class AnimalitoResultAdmin(admin.ModelAdmin):
    list_display = ("provider", "draw_date", "draw_time", "animal_number", "animal_name")
    list_filter = ("provider", "draw_date")
    search_fields = ("provider__name", "animal_name", "animal_number")
    ordering = ("provider__name", "draw_time")

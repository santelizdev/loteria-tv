# core/admin_configs/animalito_result.py
from django.contrib import admin
from core.models.animalito_result import AnimalitoResult

@admin.register(AnimalitoResult)
class AnimalitoResultAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "draw_date",
        "draw_time",
        "animal_number",
        "animal_name",
        "result_origin",
        "source_incident",
    )
    list_filter = ("provider", "draw_date")
    search_fields = ("provider__name", "animal_name", "animal_number")
    ordering = ("provider__name", "draw_time")
    readonly_fields = (
        "provider",
        "draw_date",
        "draw_time",
        "animal_number",
        "animal_name",
        "animal_image_url",
        "provider_logo_url",
        "result_origin",
        "source_incident",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

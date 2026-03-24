from django.contrib import admin
from core.models import CurrentResult

@admin.register(CurrentResult)
class CurrentResultAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "draw_date", "draw_time", "winning_number", "result_origin", "source_incident")
    list_filter = ("provider", "draw_date")
    search_fields = ("provider__name", "winning_number")
    ordering = ("provider__name", "draw_time")
    readonly_fields = (
        "provider",
        "draw_date",
        "draw_time",
        "winning_number",
        "image_url",
        "extra",
        "result_origin",
        "source_incident",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

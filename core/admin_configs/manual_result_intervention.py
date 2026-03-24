from __future__ import annotations

from django.contrib import admin

from core.models import ManualResultIntervention
from core.services.scraper_permission_service import ScraperPermissionService


@admin.register(ManualResultIntervention)
class ManualResultInterventionAdmin(admin.ModelAdmin):
    list_display = (
        "result_model",
        "action_type",
        "provider",
        "draw_date",
        "draw_time",
        "performed_by",
        "performed_at",
        "incident",
    )
    list_filter = ("result_model", "action_type", "draw_date")
    search_fields = ("provider__name", "incident__scraper_key", "incident__provider_name", "note")
    readonly_fields = (
        "incident",
        "result_model",
        "action_type",
        "provider",
        "draw_date",
        "draw_time",
        "previous_snapshot",
        "new_snapshot",
        "note",
        "performed_by",
        "performed_at",
        "created_at",
    )

    def has_module_permission(self, request):
        return ScraperPermissionService.user_can_view_incidents(request.user)

    def has_view_permission(self, request, obj=None):
        return ScraperPermissionService.user_can_view_incidents(request.user)

    def has_change_permission(self, request, obj=None):
        return ScraperPermissionService.user_can_view_incidents(request.user)

from __future__ import annotations

from django.contrib import admin

from core.models import ScraperExecution
from core.services.scraper_permission_service import ScraperPermissionService


@admin.register(ScraperExecution)
class ScraperExecutionAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "draw_date",
        "status",
        "validation_profile",
        "incident_detected",
        "incident_count",
        "started_at",
        "finished_at",
    )
    list_filter = ("status", "validation_profile", "incident_detected", "draw_date")
    search_fields = ("label", "scraper_key", "command_name", "failure_reason_code", "error_message")
    readonly_fields = (
        "scraper_key",
        "label",
        "command_name",
        "draw_date",
        "validation_profile",
        "status",
        "started_at",
        "finished_at",
        "provider_scope",
        "expected_groups",
        "persisted_groups",
        "missing_groups",
        "failure_reason_code",
        "evidence_summary",
        "error_message",
        "incident_detected",
        "incident_count",
        "created_at",
        "updated_at",
    )

    def has_module_permission(self, request):
        return ScraperPermissionService.user_can_view_incidents(request.user)

    def has_view_permission(self, request, obj=None):
        return ScraperPermissionService.user_can_view_incidents(request.user)

    def has_change_permission(self, request, obj=None):
        return ScraperPermissionService.user_can_view_incidents(request.user)


from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from core.models import ScraperIncident
from core.forms.scraper_incident_manual_resolution import ScraperIncidentManualResolutionForm
from core.services.manual_result_intervention_service import ManualResultInterventionService
from core.services.scraper_notification_service import ScraperNotificationService
from core.services.scraper_permission_service import ScraperPermissionService


@admin.register(ScraperIncident)
class ScraperIncidentAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "incident_target",
        "draw_date",
        "status",
        "alert_state",
        "severity",
        "failure_reason_code",
        "occurrence_count",
        "resolved_by",
        "last_detected_at",
        "resolved_at",
    )
    list_filter = ("status", "alert_sent", "severity", "detection_scope", "failure_reason_code", "draw_date", "scraper_key")
    search_fields = ("label", "scraper_key", "provider_name", "summary", "fingerprint")
    actions = ("send_telegram_alert_now", "mark_selected_resolved", "reopen_selected_incidents")
    list_select_related = ("resolved_by", "last_execution")
    readonly_fields = (
        "fingerprint",
        "scraper_key",
        "label",
        "command_name",
        "draw_date",
        "provider_name",
        "draw_time",
        "result_model",
        "detection_scope",
        "validation_profile",
        "status",
        "severity",
        "failure_reason_code",
        "summary",
        "evidence_summary",
        "alert_sent",
        "alert_sent_at",
        "occurrence_count",
        "first_detected_at",
        "last_detected_at",
        "last_execution",
        "resolved_at",
        "resolved_by",
        "resolution_note",
        "created_at",
        "updated_at",
        "manual_resolution_link",
    )

    fieldsets = (
        (
            "Incidente",
            {
                "fields": (
                    "fingerprint",
                    "scraper_key",
                    "label",
                    "command_name",
                    "draw_date",
                    "provider_name",
                    "draw_time",
                    "result_model",
                    "detection_scope",
                    "validation_profile",
                    "status",
                    "severity",
                    "failure_reason_code",
                    "manual_resolution_link",
                ),
            },
        ),
        (
            "Alerta",
            {
                "fields": (
                    "alert_sent",
                    "alert_sent_at",
                    "summary",
                    "evidence_summary",
                    "occurrence_count",
                    "first_detected_at",
                    "last_detected_at",
                    "last_execution",
                ),
            },
        ),
        (
            "Resolucion",
            {
                "fields": ("resolved_at", "resolved_by", "resolution_note"),
            },
        ),
        (
            "Sistema",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def incident_target(self, obj):
        draw_time = obj.draw_time.strftime("%H:%M") if obj.draw_time else "-"
        return f"{obj.provider_name or 'scraper'} @ {draw_time}"

    incident_target.short_description = "Grupo afectado"

    def alert_state(self, obj):
        if obj.alert_sent:
            sent_at = obj.alert_sent_at.strftime("%Y-%m-%d %H:%M") if obj.alert_sent_at else "-"
            return f"Enviado {sent_at}"
        return "Pendiente"

    alert_state.short_description = "Telegram"

    def manual_resolution_link(self, obj):
        if obj.status != ScraperIncident.Status.OPEN:
            return "Solo disponible para incidentes abiertos."
        url = reverse("admin:core_scraperincident_manual_resolve", args=[obj.pk])
        return format_html('<a class="button" href="{}">Carga manual controlada</a>', url)

    manual_resolution_link.short_description = "Resolucion manual"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/manual-resolve/",
                self.admin_site.admin_view(self.manual_resolve_view),
                name="core_scraperincident_manual_resolve",
            ),
        ]
        return custom_urls + urls

    def manual_resolve_view(self, request, object_id):
        incident = get_object_or_404(ScraperIncident, pk=object_id)
        if not ScraperPermissionService.user_can_resolve_incidents(request.user):
            raise PermissionDenied("No tienes permiso para resolver incidentes manualmente.")

        form = ScraperIncidentManualResolutionForm(
            request.POST or None,
            incident=incident,
        )

        if request.method == "POST" and form.is_valid():
            intervention = ManualResultInterventionService.resolve_incident_manually(
                incident=incident,
                user=request.user,
                cleaned_data=form.cleaned_data,
            )
            self.message_user(
                request,
                f"Intervencion manual #{intervention.pk} guardada y incidente resuelto.",
                level=messages.SUCCESS,
            )
            return redirect(reverse("admin:core_scraperincident_change", args=[incident.pk]))

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": incident,
            "incident": incident,
            "title": "Carga manual controlada por incidente",
            "form": form,
        }
        return TemplateResponse(
            request,
            "admin/core/scraper_incident/manual_resolution_form.html",
            context,
        )

    @admin.action(description="Enviar alerta Telegram ahora")
    def send_telegram_alert_now(self, request, queryset):
        sent = ScraperNotificationService.notify_pending_incidents(
            incidents=queryset,
            now=timezone.now(),
            force=True,
        )
        if sent:
            self.message_user(request, f"Se enviaron {sent} incidentes por Telegram.", level=messages.SUCCESS)
            return
        self.message_user(
            request,
            "No habia incidentes abiertos para enviar o falta configuracion de Telegram.",
            level=messages.WARNING,
        )

    @admin.action(description="Marcar incidentes seleccionados como resueltos")
    def mark_selected_resolved(self, request, queryset):
        open_qs = queryset.filter(status=ScraperIncident.Status.OPEN)
        updated = open_qs.update(
            status=ScraperIncident.Status.RESOLVED,
            resolved_at=timezone.now(),
            resolved_by=request.user,
            resolution_note="Resuelto manualmente desde Django Admin.",
        )
        self.message_user(
            request,
            f"Se marcaron {updated} incidentes como resueltos.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Reabrir incidentes seleccionados")
    def reopen_selected_incidents(self, request, queryset):
        updated = queryset.update(
            status=ScraperIncident.Status.OPEN,
            resolved_at=None,
            resolved_by=None,
            resolution_note="",
        )
        self.message_user(
            request,
            f"Se reabrieron {updated} incidentes.",
            level=messages.SUCCESS,
        )

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not ScraperPermissionService.user_can_resolve_incidents(request.user):
            for action_name in ("send_telegram_alert_now", "mark_selected_resolved", "reopen_selected_incidents"):
                actions.pop(action_name, None)
        return actions

    def has_module_permission(self, request):
        return ScraperPermissionService.user_can_view_incidents(request.user)

    def has_view_permission(self, request, obj=None):
        return ScraperPermissionService.user_can_view_incidents(request.user)

    def has_change_permission(self, request, obj=None):
        return ScraperPermissionService.user_can_view_incidents(request.user)

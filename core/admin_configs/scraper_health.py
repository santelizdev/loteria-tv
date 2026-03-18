from __future__ import annotations

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from core.models import ScraperHealth
from core.services.scraper_health_service import ScraperHealthService
from core.services.scraper_notification_service import ScraperNotificationService


class ScraperAlertStateFilter(admin.SimpleListFilter):
    title = "alerta"
    parameter_name = "alert_state"

    def lookups(self, request, model_admin):
        return (
            ("active", "Con alerta"),
            ("ok", "Sin alerta"),
            ("failed_today", "Fallo hoy"),
            ("missing_today", "Sin OK hoy"),
            ("stale", "Stale"),
            ("never", "Nunca corrio"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value not in {"active", "ok", "failed_today", "missing_today", "stale", "never"}:
            return queryset

        now = timezone.now()
        matched_ids = []
        for obj in queryset:
            alert = ScraperHealthService.get_alert(obj.scraper_key, now=now)
            if value == "active" and alert:
                matched_ids.append(obj.pk)
            elif value == "ok" and not alert:
                matched_ids.append(obj.pk)
            elif value == "failed_today" and alert and alert["alert_kind"] == "failed_today":
                matched_ids.append(obj.pk)
            elif value == "missing_today" and alert and alert["alert_kind"] == "missing_today":
                matched_ids.append(obj.pk)
            elif value == "stale" and alert and alert["alert_kind"] == "stale":
                matched_ids.append(obj.pk)
            elif value == "never" and obj.last_status == ScraperHealth.Status.NEVER:
                matched_ids.append(obj.pk)
        return queryset.filter(pk__in=matched_ids)


@admin.register(ScraperHealth)
class ScraperHealthAdmin(admin.ModelAdmin):
    change_list_template = "admin/core/scraper_health/change_list.html"
    list_display = (
        "label",
        "health_badge",
        "alert_kind_badge",
        "freshness_summary",
        "last_success_at",
        "last_error_short",
        "consecutive_failures",
        "last_notified_at",
        "alert_status",
    )
    list_filter = ("last_status", ScraperAlertStateFilter)
    search_fields = ("label", "scraper_key", "command_name", "last_error_message")
    actions = ("send_internal_alert_now", "reset_notification_state")
    readonly_fields = (
        "scraper_key",
        "label",
        "command_name",
        "last_status",
        "last_started_at",
        "last_finished_at",
        "last_success_at",
        "current_alert_summary",
        "notification_recipient_summary",
        "last_error_message",
        "last_error_traceback",
        "consecutive_failures",
        "last_notified_at",
        "last_notified_signature",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Identidad",
            {
                "fields": ("scraper_key", "label", "command_name", "last_status", "consecutive_failures"),
            },
        ),
        (
            "Ejecucion",
            {
                "fields": ("last_started_at", "last_finished_at", "last_success_at", "current_alert_summary"),
            },
        ),
        (
            "Notificacion",
            {
                "fields": ("notification_recipient_summary", "last_notified_at", "last_notified_signature"),
            },
        ),
        (
            "Error",
            {
                "fields": ("last_error_message", "last_error_traceback"),
            },
        ),
        (
            "Sistema",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        changelist_response = super().changelist_view(request, extra_context=extra_context)
        try:
            cl = changelist_response.context_data["cl"]
        except (AttributeError, KeyError, TypeError):
            return changelist_response

        summary = ScraperHealthService.build_admin_summary(queryset=cl.queryset, now=timezone.now())
        changelist_response.context_data["scraper_health_summary"] = summary
        changelist_response.context_data["scraper_notification_recipients"] = ScraperNotificationService.get_recipients()
        return changelist_response

    def health_badge(self, obj):
        palette = {
            ScraperHealth.Status.SUCCESS: ("#177245", "#e8fff3", "OK"),
            ScraperHealth.Status.RUNNING: ("#8a5a00", "#fff6df", "RUNNING"),
            ScraperHealth.Status.FAILED: ("#9d1c1c", "#fff0f0", "FAILED"),
            ScraperHealth.Status.NEVER: ("#5f6b7a", "#f2f5f8", "NEVER"),
        }
        color, bg, label = palette.get(obj.last_status, ("#5f6b7a", "#f2f5f8", obj.last_status.upper()))
        return format_html(
            '<span style="display:inline-block;padding:3px 8px;border-radius:999px;'
            'font-weight:700;color:{};background:{};">{}</span>',
            color,
            bg,
            label,
        )

    health_badge.short_description = "Estado"

    def alert_kind_badge(self, obj):
        alert = ScraperHealthService.get_alert(obj.scraper_key, now=timezone.now())
        if not alert:
            return format_html(
                '<span style="display:inline-block;padding:3px 8px;border-radius:999px;'
                'font-weight:700;color:{};background:{};">{}</span>',
                "#177245",
                "#e8fff3",
                "OK",
            )

        palette = {
            "failed_today": ("#9d1c1c", "#fff0f0", "FAILED TODAY"),
            "missing_today": ("#a04300", "#fff2e8", "MISSING TODAY"),
            "stale": ("#8a5a00", "#fff6df", "STALE"),
        }
        color, bg, label = palette.get(alert["alert_kind"], ("#5f6b7a", "#f2f5f8", alert["alert_kind"].upper()))
        return format_html(
            '<span style="display:inline-block;padding:3px 8px;border-radius:999px;'
            'font-weight:700;color:{};background:{};">{}</span>',
            color,
            bg,
            label,
        )

    alert_kind_badge.short_description = "Tipo alerta"

    def freshness_summary(self, obj):
        alert = ScraperHealthService.get_alert(obj.scraper_key, now=timezone.now())
        if alert:
            return alert["message"]
        return "Sin alertas"

    freshness_summary.short_description = "Salud"

    def last_error_short(self, obj):
        text = (obj.last_error_message or "").strip()
        if not text:
            return "-"
        if len(text) <= 80:
            return text
        return f"{text[:77]}..."

    last_error_short.short_description = "Ultimo error"

    def current_alert_summary(self, obj):
        alert = ScraperHealthService.get_alert(obj.scraper_key, now=timezone.now())
        if not alert:
            return "Sin alertas activas."
        return f"{alert['alert_kind']}: {alert['message']}"

    current_alert_summary.short_description = "Alerta actual"

    def notification_recipient_summary(self, obj):
        recipients = ScraperNotificationService.get_recipients()
        if not recipients:
            return "Sin destinatarios configurados."
        return mark_safe("<br>".join(recipients))

    notification_recipient_summary.short_description = "Destinatarios"

    def alert_status(self, obj):
        alert = ScraperHealthService.get_alert(obj.scraper_key, now=timezone.now())
        if not alert:
            return "OK"
        return alert["message"]

    alert_status.short_description = "Alerta"

    @admin.action(description="Enviar notificacion interna ahora")
    def send_internal_alert_now(self, request, queryset):
        sent = ScraperNotificationService.notify_active_alerts(
            now=timezone.now(),
            monitors=queryset,
            force=True,
        )
        if sent:
            self.message_user(request, f"Se enviaron {sent} alertas internas.", level=messages.SUCCESS)
            return
        self.message_user(
            request,
            "No habia alertas activas para los scrapers seleccionados o no hay destinatarios configurados.",
            level=messages.WARNING,
        )

    @admin.action(description="Resetear estado de notificacion")
    def reset_notification_state(self, request, queryset):
        updated = queryset.update(last_notified_at=None, last_notified_signature="")
        self.message_user(
            request,
            f"Se limpiaron las marcas de notificacion en {updated} scrapers.",
            level=messages.SUCCESS,
        )
